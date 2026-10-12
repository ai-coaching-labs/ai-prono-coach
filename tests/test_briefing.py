import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from prono.briefing import daily_briefing, save_briefing
from prono.cli import main
from prono.demo import seed
from prono.workspace import Workspace, timestamp, read_record

ROOT = Path(__file__).resolve().parents[1]


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        shutil.copy(ROOT / 'config/workspace.toml', self.root / 'config/workspace.toml')
        self.ws = Workspace(self.root)
        self.now = timestamp('2026-10-10T22:30:00Z')
        with patch('prono.demo.utcnow', return_value=self.now):
            seed(self.ws)
        self.path = self.ws.path('data/fixtures.json')
        self.rows = json.loads(self.path.read_text())

    def write(self):
        self.path.write_text(json.dumps(self.rows))

    def test_local_midnight_and_started_boundary(self):
        self.rows[0]['kickoff'] = '2026-10-10T23:00:00Z'
        self.rows[1].update(kickoff=self.now.isoformat(), quoted_at=(self.now-timedelta(minutes=1)).isoformat())
        self.rows[2]['kickoff'] = '2026-10-11T22:00:00Z'
        self.write()
        result = daily_briefing(self.ws, self.now)
        self.assertEqual(result['date'], '2026-10-11')
        self.assertEqual([i['status'] for i in result['matches']], ['started', 'analysis_only'])
        self.assertEqual(result['matches'][1]['analysis']['model']['as_of'], self.now.isoformat())
        self.assertTrue(result['matches'][1]['synthetic'])
        self.assertEqual(daily_briefing(self.ws, self.now, 'UTC')['today_count'], 2)

    def test_daylight_saving_repeated_hour(self):
        now = timestamp('2026-10-24T22:00:00Z')
        self.rows = [dict(self.rows[0], event_id=str(i), kickoff=kick, quoted_at=now.isoformat())
                     for i, kick in enumerate(['2026-10-25T00:30:00Z', '2026-10-25T01:30:00Z', '2026-10-25T23:00:00Z'])]
        self.write()
        result = daily_briefing(self.ws, now)
        self.assertEqual(result['today_count'], 2)
        self.assertTrue(result['matches'][0]['kickoff_local'].endswith('+02:00'))
        self.assertTrue(result['matches'][1]['kickoff_local'].endswith('+01:00'))

    def test_abstention_reasons_and_no_writes(self):
        for row in self.rows:
            row['kickoff'] = (self.now+timedelta(hours=2)).isoformat()
        self.rows[0]['quoted_at'] = (self.now-timedelta(hours=7)).isoformat()
        self.rows[1]['quoted_at'] = (self.now+timedelta(minutes=1)).isoformat()
        self.rows[2]['home'] = 'Inconnue'
        self.write()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = daily_briefing(self.ws, self.now)
        self.assertEqual([i['status'] for i in result['matches']], ['stale_odds', 'future_odds', 'insufficient_data'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(result['absences'], 'indisponibles')

    def test_empty_and_invalid_timezone(self):
        self.rows = []
        self.write()
        result = daily_briefing(self.ws, self.now)
        self.assertEqual(result['today_count'], 0)
        self.assertIn('Importer', result['next_steps'][0])
        with self.assertRaisesRegex(ValueError, 'Fuseau'):
            daily_briefing(self.ws, self.now, 'Invalid/Zone')

    def test_report_roundtrip_and_cli(self):
        import contextlib
        import io
        result = daily_briefing(self.ws, self.now)
        path = save_briefing(self.ws, result)
        self.assertEqual(read_record(path)['matches'], result['matches'])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch('prono.briefing.utcnow', return_value=self.now):
            code = main(['--workspace', str(self.root), 'today', '--save'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())['date'], '2026-10-11')
        self.assertFalse(self.ws.path('journal').exists())

    def test_capacity_respects_available_balance(self):
        self.ws.config['paper']['starting_balance'] = 0.5
        result = daily_briefing(self.ws, self.now)
        self.assertEqual(result['remaining_exposure_units'], 0.5)
        self.assertTrue(any('Limite' in a for a in result['next_steps']))
