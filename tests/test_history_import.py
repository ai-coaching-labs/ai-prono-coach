import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from prono.workspace import Workspace, timestamp
from prono.history_import import normalize_history, sync_history, fetch_csv
from prono.model import load_history, predict

CSV = 'Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\nF1,15/08/2025,19:45,Rennes,Marseille,1,0\n'
ROOT = Path(__file__).resolve().parents[1]

class HistoryImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root/'config').mkdir()
        shutil.copy(ROOT/'config/workspace.toml', root/'config/workspace.toml')
        self.ws = Workspace(root)
        self.now = timestamp('2026-10-10T09:00:00Z')

    def test_conversion_and_knowledge_not_backdated(self):
        row = normalize_history(CSV, '2526', self.now.isoformat())[0]
        self.assertEqual(row['kickoff'], '2025-08-15T18:45:00+00:00')
        self.assertEqual(row['result_known_at'], self.now.isoformat())
        prediction = predict([row], 'Rennes', 'Marseille', self.now, self.ws.config['model'])
        self.assertEqual(prediction['sample']['league'], 0)
        winter = normalize_history(CSV.replace('15/08/2025','15/12/2025'), '2526', self.now.isoformat())[0]
        self.assertEqual(winter['kickoff'], '2025-12-15T19:45:00+00:00')

    def test_incomplete_wrong_league_future_duplicates_rejected(self):
        for content in [CSV.replace('F1,','F2,'), CSV.replace('19:45',''), CSV.replace('2025','2027'), CSV+CSV.splitlines()[1]+'\n']:
            with self.subTest(content=content), self.assertRaises(ValueError):
                normalize_history(content, '2526', self.now.isoformat())

    def test_repeat_import_preserves_first_collection_and_correction_refused(self):
        with patch('prono.history_import.fetch_csv', return_value=CSV), patch('prono.history_import.utcnow', return_value=self.now):
            self.assertEqual(sync_history(self.ws, ['2526'])['added'], 1)
        original = self.ws.path('data/history.csv').read_bytes()
        with patch('prono.history_import.fetch_csv', return_value=CSV):
            self.assertEqual(sync_history(self.ws, ['2526'])['added'], 0)
        self.assertEqual(self.ws.path('data/history.csv').read_bytes(), original)
        with patch('prono.history_import.fetch_csv', return_value=CSV.replace(',1,0', ',2,0')):
            with self.assertRaisesRegex(ValueError, 'corrigée'):
                sync_history(self.ws, ['2526'])
        self.assertEqual(self.ws.path('data/history.csv').read_bytes(), original)
        self.assertEqual(len(load_history(self.ws.path('data/history.csv'))), 1)

    def test_demo_refused_before_network(self):
        from prono.demo import seed
        seed(self.ws)
        with patch('prono.history_import.fetch_csv') as fetch:
            with self.assertRaisesRegex(ValueError, 'séparé'):
                sync_history(self.ws, ['2526'])
            fetch.assert_not_called()

    def test_partial_download_does_not_commit(self):
        with patch('prono.history_import.fetch_csv', side_effect=[CSV, ValueError('indisponible')]):
            with self.assertRaises(ValueError):
                sync_history(self.ws, ['2425', '2526'])
        self.assertFalse(self.ws.path('data/history.csv').exists())

    def test_legacy_encoding_is_lossless_and_original_bytes_are_archived(self):
        from unittest.mock import MagicMock
        payload=CSV.replace('Rennes','King’s Lynn').encode('cp1252')
        response=MagicMock();response.__enter__.return_value.read.return_value=payload
        with patch('prono.history_import.urllib.request.urlopen',return_value=response):text=fetch_csv('https://www.football-data.co.uk/mmz4281/2526/F1.csv')
        self.assertIn('King’s Lynn',text);self.assertEqual(text.source_encoding,'windows-1252')
        with patch('prono.history_import.fetch_csv',return_value=text):sync_history(self.ws,['2526'])
        raw=next(self.ws.path('data/sources').glob('*.raw.csv'));self.assertEqual(raw.read_bytes(),payload)
        self.assertEqual(load_history(self.ws.path('data/history.csv'))[0]['home'],'King’s Lynn')
