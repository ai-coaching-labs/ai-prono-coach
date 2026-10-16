"""Archives shown in the coach are local, dated and protected like live reviews."""
import copy
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from prono.review_history import archived_review, list_reviews
from prono.workspace import Workspace, write_record

ROOT = Path(__file__).resolve().parents[1]


class ReviewHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root/'config').mkdir()
        shutil.copy(ROOT/'config/workspace.toml', root/'config/workspace.toml')
        (root/'config/workspace.user.toml').write_text('[tracking]\nenabled = false\n')
        self.ws = Workspace(root)
        self.record = {'run_id': 'a'*32, 'created_at': '2026-10-15T12:00:00+00:00',
                       'status': 'completed', 'provider': 'claude', 'model': 'Archived model',
                       'question': 'Analyse Rennes / Paris',
                       'scope': [{'event_id': 'original-id', 'match': 'Rennes / Paris',
                                  'kickoff': '2026-10-16T18:00:00+00:00'}],
                       'facts': {'selection': {'date': 'original-date'}, 'probabilities': {'home': .4}},
                       'reviews': [{'role': 'match-analyst', 'name': 'Analyste', 'status': 'completed',
                                    'answer': 'Avis sourcé ancien'}],
                       'answer': '**Rennes (1)** · confiance faible · score envisagé 2-1.',
                       'stats': {'model_calls': 3}}
        self.save(self.record)

    def save(self, record):
        write_record(self.ws.path('analyses/team-'+record['run_id']+'.md'), 'team_review', record)

    def test_search_pagination_and_original_dates_without_full_payloads(self):
        newer = {**self.record, 'run_id': 'b'*32, 'created_at': '2026-10-15T14:00:00+00:00',
                 'scope': [{'match': 'Arsenal / Chelsea'}]}
        self.save(newer)
        page = list_reviews(self.ws, limit=1)
        self.assertEqual(page['total'], 2)
        self.assertEqual(page['analyses'][0]['run_id'], 'b'*32)
        self.assertNotIn('answer', page['analyses'][0])
        self.assertNotIn('facts', page['analyses'][0])
        self.assertEqual(list_reviews(self.ws, offset=1, limit=1)['analyses'][0]['run_id'], 'a'*32)
        filtered = list_reviews(self.ws, 'rEnNeS')
        self.assertEqual(filtered['total'], 1)
        self.assertEqual(filtered['analyses'][0]['created_at'], self.record['created_at'])
        self.assertEqual(list_reviews(self.ws, 'missing')['total'], 0)

    def test_open_preserves_verdict_reviews_and_files_without_model_or_recalculation(self):
        files = {p.name: p.read_bytes() for p in self.ws.path('analyses').glob('*.md')}
        with patch('prono.team.call_model', side_effect=AssertionError('No model call')), \
             patch('prono.model.predict', side_effect=AssertionError('No recalculation')):
            result = archived_review(self.ws, 'a'*32)
        self.assertEqual(result['result']['answer'], self.record['answer'])
        self.assertEqual(result['reviews'], self.record['reviews'])
        self.assertEqual(result['result']['stats'], self.record['stats'])
        self.assertEqual(result['scope'], self.record['scope'])
        self.assertTrue(result['archived'])
        self.assertEqual(files, {p.name: p.read_bytes() for p in self.ws.path('analyses').glob('*.md')})

    def test_invalid_files_and_symlinks_are_skipped_and_reported(self):
        self.ws.path('analyses/team-'+('b'*32)+'.md').write_text('broken')
        self.ws.path('analyses/team-'+('c'*32)+'.md').symlink_to(self.ws.path('analyses/team-'+('a'*32)+'.md'))
        invalid = copy.deepcopy(self.record)
        invalid.update(run_id='d'*32, scope=[None])
        self.save(invalid)
        result = list_reviews(self.ws)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['skipped'], 3)
        for run_id in ('../secret', 'bad', 'c'*32, 'f'*32):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                archived_review(self.ws, run_id)
        for kwargs in ({'limit': 0}, {'limit': 100}, {'offset': -1}, {'query': 'a'*201}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                list_reviews(self.ws, **kwargs)

    def test_interrupted_review_is_readable_without_a_fabricated_verdict(self):
        failed = {**self.record, 'run_id': 'b'*32, 'status': 'error', 'error': 'Source unavailable'}
        failed.pop('answer')
        self.save(failed)
        result = archived_review(self.ws, 'b'*32)
        self.assertNotIn('result', result)
        self.assertEqual(result['error'], 'Source unavailable')

    def test_http_history_requires_token_and_survives_server_restart(self):
        for _ in range(2):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            process = subprocess.Popen([sys.executable, '-m', 'prono.cli', '--workspace', str(self.ws.root),
                                        'ui', '--port', str(port)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertIn('Dashboard', process.stdout.readline())
                base = f'http://127.0.0.1:{port}'
                with urllib.request.urlopen(base+'/chat', timeout=3) as response:
                    html = response.read().decode()
                self.assertIn('Mes analyses enregistrées', html)
                token = re.search(r'data-token="([^"]+)"', html).group(1)
                for url in ('/api/chat/analyses', '/api/chat/analyses/'+('a'*32)):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(base+url, timeout=3)
                    self.assertEqual(error.exception.code, 403)
                    error.exception.close()
                def get(url):
                    request = urllib.request.Request(base+url, headers={'X-Prono-Token': token})
                    with urllib.request.urlopen(request, timeout=3) as response:
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                        return json.load(response)
                self.assertEqual(get('/api/chat/analyses?q=Rennes')['total'], 1)
                self.assertEqual(get('/api/chat/analyses/'+('a'*32))['result']['answer'], self.record['answer'])
                with self.assertRaises(urllib.error.HTTPError) as invalid:
                    get('/api/chat/analyses?limit=999')
                self.assertEqual(invalid.exception.code, 400)
                invalid.exception.close()
            finally:
                process.terminate()
                process.communicate(timeout=5)
