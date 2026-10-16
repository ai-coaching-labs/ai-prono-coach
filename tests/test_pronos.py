import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from prono.workspace import Workspace, timestamp, atomic_write
from prono.leagues import league_workspace
from prono.demo import seed
from prono.pronos import selections

ROOT = Path(__file__).resolve().parents[1]

class PronosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root/'config').mkdir()
        shutil.copy(ROOT/'config/workspace.toml', root/'config/workspace.toml')
        self.ws = Workspace(root)
        self.child = league_workspace(self.ws, 'F1', create=True)
        self.now = timestamp('2026-10-10T22:30:00Z')  # 11 octobre à Paris
        with patch('prono.demo.utcnow', return_value=self.now-timedelta(hours=1)):
            seed(self.child)
        self.fixture = json.loads(self.child.path('data/fixtures.json').read_text())[0]
        self.fixture.update(kickoff=(self.now+timedelta(hours=1)).isoformat(), quoted_at=(self.now-timedelta(minutes=1)).isoformat())
        self.write([self.fixture])

    def write(self, rows):
        atomic_write(self.child.path('data/fixtures.json'), json.dumps(rows))

    def test_today_and_next_three_local_days_exclude_started(self):
        rows = [dict(self.fixture,event_id=str(i),kickoff=t) for i,t in enumerate([
            self.now.isoformat(), '2026-10-11T20:00:00Z','2026-10-11T22:00:00Z',
            '2026-10-14T21:59:00Z','2026-10-14T22:00:00Z'])]
        self.write(rows)
        today = selections(self.ws, 'today', 'F1', now=self.now)
        next3 = selections(self.ws, 'next3', 'F1', now=self.now)
        self.assertEqual([r['fixture']['event_id'] for r in today['matches']], ['1'])
        self.assertEqual([r['fixture']['event_id'] for r in next3['matches']], ['2','3'])
        self.assertEqual((next3['start'],next3['end']), ('2026-10-12','2026-10-14'))

    def test_watch_is_observation_and_no_market_comparison(self):
        self.write([])
        f=dict(self.fixture,division='F1',quoted_at=None,offers=[])
        atomic_write(self.ws.path('data/market-watch.json'),json.dumps({'matches':[f]}))
        r=selections(self.ws,league='F1',now=self.now)['matches'][0]
        self.assertTrue(r['model']['available'])
        self.assertEqual(r['status'],'abstention')
        self.assertIsNone(r['comparison'])
        self.assertEqual(r['model']['as_of'],self.now.isoformat())

    def test_coach_receives_computed_score_and_btts_without_changing_pick(self):
        from prono.chat import coach_facts
        from prono.forecast_details import forecast_details
        expected = selections(self.ws, league='F1', now=self.now)['matches'][0]
        with patch('prono.pronos.utcnow', return_value=self.now), patch('prono.chat.utcnow', return_value=self.now):
            facts = coach_facts(self.ws, league='F1', event_id=self.fixture['event_id'])
        row = facts['matches'][0]
        self.assertEqual(row['probabilities'], expected['model']['probabilities'])
        self.assertEqual(row['model_pick'], expected['outcome'])
        self.assertEqual(row['forecast_details'], forecast_details(expected['model']))
        self.assertIsNotNone(row['forecast_details'])

    def test_xg_context_is_local_and_keeps_production_probabilities(self):
        from prono.chat import coach_facts
        from prono.understat import save_capture
        expected = selections(self.ws, league='F1', now=self.now)['matches'][0]
        raw = {'id':'100', 'isResult':True,
               'h':{'id':'1', 'title':self.fixture['home']},
               'a':{'id':'2', 'title':self.fixture['away']},
               'goals':{'h':'2','a':'1'}, 'xG':{'h':'1.2','a':'0.7'},
               'datetime':(self.now-timedelta(days=3)).replace(tzinfo=None).isoformat(sep=' ')}
        save_capture(self.ws, 'F1', 2026, {'dates':[raw]}, self.now-timedelta(minutes=1))
        with patch('prono.pronos.utcnow',return_value=self.now), patch('prono.chat.utcnow',return_value=self.now), patch('prono.understat.fetch_season') as network:
            facts=coach_facts(self.ws,league='F1',event_id=self.fixture['event_id'])
        network.assert_not_called()
        row=facts['matches'][0]
        self.assertEqual(row['probabilities'],expected['model']['probabilities'])
        self.assertEqual(row['model_pick'],expected['outcome'])
        self.assertAlmostEqual(row['understat_xg']['home']['last5']['xg_for_per_match'],1.2)
        self.assertAlmostEqual(row['understat_xg']['away']['last5']['xg_for_per_match'],0.7)

    def test_model_pick_display_is_separate_from_simulation_abstention(self):
        import html
        from prono.pronos import render
        self.write([])
        f=dict(self.fixture,division='F1',quoted_at=None,
               offers=[{'bookmaker':'Test Book','odds':{'home':2.0,'draw':3.5,'away':4.0}}])
        atomic_write(self.ws.path('data/market-watch.json'),json.dumps({'matches':[f]}))
        result=selections(self.ws,league='F1',now=self.now)
        row=result['matches'][0]
        self.assertEqual(row['status'],'abstention')
        self.assertIsNone(row['comparison'])
        expected=max(row['model']['probabilities'],key=row['model']['probabilities'].get)
        self.assertEqual(row['outcome'],expected)
        body=render(result,lambda **kw:'/',html.escape)
        self.assertIn('1 prono(s) calculé(s)',body)
        self.assertIn('Prono du modèle',body)
        self.assertIn('Test Book : 2.00 / 3.50 / 4.00',body)
        self.assertIn('Simulation fictive : abstention',html.unescape(body))
        self.assertNotIn('Espérance théorique :',body)

    def test_fresh_selection_stale_future_unknown_and_limit(self):
        self.fixture['odds']={'home':100,'draw':100,'away':100}
        self.write([self.fixture])
        r=selections(self.ws,league='F1',now=self.now)['matches'][0]
        self.assertEqual(r['status'],'candidate')
        self.assertTrue(r['synthetic'])
        self.assertEqual(r['model']['as_of'],self.fixture['quoted_at'])
        for change in [dict(quoted_at=(self.now-timedelta(hours=7)).isoformat()),dict(quoted_at=(self.now+timedelta(minutes=1)).isoformat()),dict(home='Unknown')]:
            with self.subTest(change=change):
                self.write([dict(self.fixture,**change)])
                self.assertEqual(selections(self.ws,league='F1',now=self.now)['matches'][0]['status'],'abstention')
        self.write([self.fixture])
        atomic_write(self.child.path('config/workspace.user.toml'),'[data]\nfootball_data_division="F1"\n[paper]\nstarting_balance=0.5\n')
        self.assertEqual(selections(self.ws,league='F1',now=self.now)['candidates'],0)

    def test_no_lookahead_from_future_known_results(self):
        import csv,io
        path=self.child.path('data/history.csv')
        reader=csv.DictReader(io.StringIO(path.read_text()))
        rows=list(reader); fields=reader.fieldnames
        for row in rows: row['result_known_at']=(self.now+timedelta(minutes=1)).isoformat()
        output=io.StringIO(); writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        atomic_write(path,output.getvalue())
        r=selections(self.ws,league='F1',now=self.now)['matches'][0]
        self.assertFalse(r['model']['available'])
        self.assertEqual(r['status'],'abstention')

    def test_daylight_saving_and_no_writes(self):
        now=timestamp('2026-10-24T22:15:00Z')
        self.write([dict(self.fixture,event_id=str(i),kickoff=kick) for i,kick in enumerate(['2026-10-25T00:30:00Z','2026-10-25T01:30:00Z','2026-10-25T23:00:00Z'])])
        before={str(p):p.read_bytes() for p in self.ws.root.rglob('*') if p.is_file()}
        result=selections(self.ws,league='F1',now=now)
        self.assertEqual(len(result['matches']),2)
        self.assertTrue(result['matches'][0]['kickoff_local'].endswith('+02:00'))
        self.assertTrue(result['matches'][1]['kickoff_local'].endswith('+01:00'))
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.ws.root.rglob('*') if p.is_file()})

    def test_hub_pronos_route_and_filters(self):
        from prono.hub_dashboard import page
        with patch('prono.hub_dashboard.utcnow',return_value=self.now):
            body=page(self.ws,{'tab':'pronos','league':'F1','horizon':'today'})
            self.assertIn('Prono du modèle',body)
            self.assertIn('name="horizon" value="today"',body)
            self.assertNotIn('Prono du modèle',page(self.ws,{'tab':'pronos','league':'F1','q':'absent'}))
