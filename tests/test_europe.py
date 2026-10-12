import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from prono.workspace import Workspace,timestamp
from prono.leagues import league_workspace,history_seasons
from prono.europe import normalize,decimal_odds,sync_europe,sync_europe_history,BASE
from prono.market_watch import public_calendar,sync_markets
from prono.model import load_history
from prono.pronos import selections

ROOT=Path(__file__).resolve().parents[1]

class EuropeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);(root/'config').mkdir();shutil.copy(ROOT/'config/workspace.toml',root/'config/workspace.toml')
        self.ws=Workspace(root);self.now=timestamp('2026-10-12T10:00:00Z')
        self.source=BASE+'uefa.champions/scoreboard?dates=202610&limit=1000'
        self.event={'id':'123','competitions':[{'date':'2026-10-13T16:45:00Z','timeValid':True,
            'status':{'period':0,'type':{'state':'pre','name':'STATUS_SCHEDULED','completed':False}},
            'competitors':[{'homeAway':'home','score':'0','team':{'displayName':'Lens'}},
                           {'homeAway':'away','score':'0','team':{'displayName':'Sporting CP'}}],
            'odds':[{'provider':{'name':'Example'},'moneyline':{k:{'close':{'odds':v}} for k,v in [('home','+150'),('draw','+280'),('away','-120')]}}]}]}

    def parsed(self,event=None):return normalize({'events':[event or self.event]},'UCL',self.source,self.now.isoformat())

    def test_triplet_conversion_and_utc_kickoff_without_invented_quote_time(self):
        result=self.parsed();self.assertEqual(result['results'],[])
        f=result['matches'][0];self.assertEqual(f['kickoff'],'2026-10-13T16:45:00+00:00');self.assertIsNone(f['quoted_at'])
        self.assertEqual(f['offers'][0]['odds']['home'],2.5);self.assertAlmostEqual(f['offers'][0]['odds']['away'],1+100/120)
        self.assertFalse(f['analysis_eligible'])
        with self.assertRaises(ValueError):decimal_odds(0)

    def test_missing_draw_or_mixed_open_close_does_not_create_offer(self):
        event=copy.deepcopy(self.event);market=event['competitions'][0]['odds'][0]['moneyline'];market['draw']={'open':{'odds':'+280'}}
        self.assertEqual(self.parsed(event)['matches'][0]['offers'],[])

    def finished(self):
        event=copy.deepcopy(self.event);c=event['competitions'][0];c['date']='2026-10-01T19:00:00Z'
        c['status']={'period':2,'type':{'state':'post','name':'STATUS_FULL_TIME','completed':True}}
        c['competitors'][0]['score']='2';c['competitors'][1]['score']='1';return event

    def test_only_completed_regulation_result_and_actual_collection_time(self):
        result=self.parsed(self.finished());r=result['results'][0]
        self.assertEqual((r['home_goals'],r['away_goals']),(2,1));self.assertEqual(r['result_known_at'],self.now.isoformat())
        self.assertEqual(result['matches'],[])
        for period,name in [(4,'STATUS_FULL_TIME'),(2,'STATUS_FINAL_PEN'),(0,'STATUS_POSTPONED')]:
            event=self.finished();event['competitions'][0]['status'].update(period=period)
            event['competitions'][0]['status']['type']['name']=name
            self.assertEqual(self.parsed(event)['results'],[])

    def test_future_finished_unknown_time_and_live_match_are_not_predictions(self):
        event=self.finished();event['competitions'][0]['date']='2026-10-13T19:00:00Z'
        self.assertEqual(self.parsed(event)['results'],[])
        event=copy.deepcopy(self.event);event['competitions'][0]['timeValid']=False
        self.assertEqual(self.parsed(event)['matches'],[])
        event['competitions'][0]['timeValid']=True;event['competitions'][0]['status']['type'].update(state='in',name='STATUS_IN_PROGRESS')
        self.assertEqual(self.parsed(event)['matches'],[])

    def test_separate_calendar_survives_domestic_refresh_and_failed_europe_refresh(self):
        initial=self.parsed();self.ws.path('data').mkdir();self.ws.path('data/europe-watch.json').write_text(json.dumps(initial))
        csv='Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A\nF1,13/10/2026,20:00,A,B,2,3,4\n'
        with patch('prono.market_watch.fetch_csv',return_value=csv),patch('prono.europe.sync_europe',return_value={'matches':0,'offers':0}):sync_markets(self.ws)
        self.assertEqual(len(public_calendar(self.ws)['matches']),2)
        with patch('prono.europe.archive',side_effect=ValueError('indisponible')):
            result=sync_europe(self.ws,['UCL'])
        self.assertEqual(result['sources']['UCL']['status'],'error');self.assertEqual(len(public_calendar(self.ws)['matches']),2)

    def test_history_repeat_preserves_knowledge_and_correction_or_partial_failure_cannot_replace(self):
        child=league_workspace(self.ws,'UCL',create=True);part=self.parsed(self.finished())
        with patch('prono.europe.archive',return_value=part):self.assertEqual(sync_europe_history(child,['2627'])['added'],1)
        p=child.path('data/history.csv');original=p.read_bytes();r=load_history(p)[0]
        self.assertEqual(r['result_known_at'],self.now.isoformat())
        with patch('prono.europe.archive',return_value=part):self.assertEqual(sync_europe_history(child,['2627'])['added'],0)
        changed=copy.deepcopy(part);changed['results'][0]['home_goals']=3
        with patch('prono.europe.archive',return_value=changed),self.assertRaisesRegex(ValueError,'corrigé'):sync_europe_history(child,['2627'])
        with patch('prono.europe.archive',side_effect=[part,ValueError('indisponible')]),self.assertRaises(ValueError):sync_europe_history(child,['2526','2627'])
        self.assertEqual(p.read_bytes(),original)

    def test_europe_fixture_reaches_pronos_with_no_domestic_training_or_invented_probability(self):
        league_workspace(self.ws,'UCL',create=True);self.ws.path('data/europe-watch.json').write_text(json.dumps(self.parsed()))
        result=selections(self.ws,'next3','UCL',now=self.now)
        self.assertEqual(len(result['matches']),1);row=result['matches'][0]
        self.assertFalse(row['model']['available']);self.assertIsNone(row['outcome']);self.assertEqual(row['status'],'abstention')
        self.assertTrue(any('exploratoire' in r for r in row['reasons']))
        from prono.chat import coach_facts
        with patch('prono.pronos.selections',return_value=result):facts=coach_facts(self.ws,'UCL','next3')
        self.assertEqual(facts['matches'][0]['sample_period'],row['model']['sample_period'])

    def test_history_policy_is_ten_years_for_europe_and_does_not_predate_conference(self):
        self.assertEqual(history_seasons(self.ws,'UCL',self.now)[0],'1617')
        self.assertEqual(history_seasons(self.ws,'UCL',self.now)[-1],'2627')
        self.assertEqual(history_seasons(self.ws,'F1',self.now),['2122','2223','2324','2425','2526','2627'])
        self.assertEqual(history_seasons(self.ws,'UECL',self.now)[0],'2122')
        self.assertEqual(history_seasons(self.ws,'UCL',timestamp('2027-02-01T12:00:00Z'))[-1],'2627')
        self.ws.config['europe']['history_years']=0
        with self.assertRaises(ValueError):history_seasons(self.ws,'UCL',self.now)

    def test_europe_window_default_and_explicit_user_override_are_preserved(self):
        child=league_workspace(self.ws,'UCL',create=True)
        self.assertEqual(child.config['model']['max_history_days'],3653)
        p=child.path('config/workspace.user.toml');s=p.read_text().replace('3653','1096');p.write_text(s)
        self.assertEqual(league_workspace(self.ws,'UCL').config['model']['max_history_days'],1096)
        self.assertEqual(p.read_text(),s)
        self.assertEqual(self.ws.config['model']['max_history_days'],1826)
