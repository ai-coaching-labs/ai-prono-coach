import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from prono.workspace import Workspace, timestamp, atomic_write
from prono.leagues import league_workspace, division_for
from prono.market_watch import normalize_markets
from prono.history_import import normalize_history
from prono.context import import_context, contexts
from prono.hub_dashboard import page

ROOT = Path(__file__).resolve().parents[1]
CSV = 'Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,BWH,BWD,BWA\nF1,10/10/2026,16:15,Lille,Le Havre,2.1,3.4,3.5,2.2,,3.4\n'

class LeagueContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root/'config').mkdir()
        shutil.copy(ROOT/'config/workspace.toml', root/'config/workspace.toml')
        self.ws = Workspace(root)
        self.now = timestamp('2026-10-10T09:00:00Z')
        self.watch = normalize_markets(CSV, self.now.isoformat())
        atomic_write(root/'data/market-watch.json', json.dumps(self.watch))
        self.payload = {'event_id': self.watch['matches'][0]['event_id'], 'as_of': self.now.isoformat(),
                        'findings': [{'team': 'Lille', 'category': 'club_news', 'status': 'reported',
                        'claim': 'Annonce à vérifier.', 'sources': [{'type': 'club', 'url': 'https://example.com/news',
                        'title': 'Annonce', 'checked_at': self.now.isoformat(), 'published_at': None,
                        'publication_date': '2026-10-09'}]}], 'missing': ['Composition officielle']}

    def test_workspace_isolation(self):
        france = league_workspace(self.ws, 'F1', create=True)
        england = league_workspace(self.ws, 'E0', create=True)
        self.assertNotEqual(france.root, england.root)
        self.assertEqual(division_for(france), 'F1')
        self.assertEqual(division_for(england), 'E0')
        with self.assertRaises(ValueError):
            league_workspace(self.ws, '../escape', create=True)

    def test_existing_domestic_window_inherits_hub_and_preserves_explicit_user_setting(self):
        child=league_workspace(self.ws,'F1',create=True);path=child.path('config/workspace.user.toml');original=path.read_bytes()
        self.ws.config['model']['max_history_days']=1096
        self.assertEqual(league_workspace(self.ws,'F1').config['model']['max_history_days'],1096)
        self.assertEqual(path.read_bytes(),original)
        path.write_text(path.read_text()+'\n[model]\nmax_history_days = 1826\n');configured=path.read_bytes()
        self.assertEqual(league_workspace(self.ws,'F1').config['model']['max_history_days'],1826)
        self.assertEqual(path.read_bytes(),configured)

    def test_market_never_invents_quote_time_or_mixes_bookmakers(self):
        row = self.watch['matches'][0]
        self.assertIsNone(row['quoted_at'])
        self.assertFalse(row['analysis_eligible'])
        self.assertEqual(len(row['offers']), 1)
        self.assertEqual(row['offers'][0]['bookmaker'], 'Bet365')
        self.assertEqual(row['kickoff'], '2026-10-10T15:15:00+00:00')
        self.assertFalse(self.ws.path('data/fixtures.json').exists())

    def test_missing_scores_are_traced_and_other_divisions_rejected(self):
        data = 'Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\nF2,01/10/2026,19:00,A,B,,\nF2,02/10/2026,19:00,C,D,1,0\n'
        rejected = []
        rows = normalize_history(data, '2627', self.now.isoformat(), 'F2', rejected)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rejected[0]['home'], 'A')
        with self.assertRaises(ValueError):
            normalize_history(data, '2627', self.now.isoformat(), 'E0', [])

    def test_context_roundtrip_and_no_model_side_effect(self):
        result = import_context(self.ws, self.payload, self.now)
        self.assertFalse(result['probabilities_modified'])
        self.assertEqual(contexts(self.ws)[0]['findings'], result['findings'])
        self.assertFalse(self.ws.path('journal').exists())
        self.assertFalse(self.ws.path('data/fixtures.json').exists())

    def test_context_rejects_future_and_postmatch_evidence(self):
        for field, value in [('checked_at','2026-10-10T10:00:00Z'), ('published_at','2026-10-10T10:00:00Z'), ('publication_date','2026-10-11')]:
            payload = copy.deepcopy(self.payload)
            payload['findings'][0]['sources'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                import_context(self.ws, payload, self.now)
        with self.assertRaises(ValueError):
            import_context(self.ws, self.payload, timestamp('2026-10-10T16:00:00Z'))
        self.assertEqual(contexts(self.ws), [])

    def test_context_requires_match_and_citations(self):
        for key,value in [('event_id','unknown'), ('findings',[dict(self.payload['findings'][0], sources=[])])]:
            payload = dict(self.payload, **{key:value})
            with self.assertRaises(ValueError):
                import_context(self.ws, payload, self.now)

    def test_hub_filters_and_escapes(self):
        with patch('prono.hub_dashboard.utcnow', return_value=self.now):
            markup = page(self.ws, {'league':'F1','tab':'matches'})
            self.assertIn('Le Havre', markup)
            self.assertNotIn('Le Havre', page(self.ws, {'league':'E0','tab':'matches'}))
            search = page(self.ws, {'q':'<script>alert(1)</script>'})
            self.assertNotIn('<script>', search)
            self.assertIn('&lt;script&gt;', search)
            self.assertIn('Journaliste sportif', page(self.ws, {'tab':'team'}))
            self.assertIn('Cotation non horodatée', markup)

    def test_calendar_does_not_read_unrelated_histories_or_journals(self):
        # Un fichier d’archives absent ou invalide ne doit pas bloquer le calendrier.
        with patch('prono.hub_dashboard.load_history', side_effect=AssertionError('lecture inutile')), patch('prono.journal.summary', side_effect=AssertionError('journal inutile')):
            markup = page(self.ws, {'tab':'matches'})
        self.assertIn('Le calendrier', markup)

    def test_results_read_only_selected_competition(self):
        league_workspace(self.ws, 'F1', create=True)
        league_workspace(self.ws, 'E0', create=True)
        with patch('prono.hub_dashboard.load_history', return_value=[]) as reader:
            page(self.ws, {'tab':'results','league':'F1'})
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(reader.call_args.args[0], self.ws.path('data/workspaces/ligue1/data/history.csv'))
