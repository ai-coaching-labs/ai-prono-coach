import copy
import csv
import json
import math
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from prono.workspace import Workspace,timestamp,read_record,write_record_once
from prono.leagues import league_workspace
from prono.identity import register_matches,team_id,freshness,price_changes,link_schedule
from prono.tracking import capture,reconcile,tracking_summary,refresh_due_results
from prono.evaluation import evaluate_league,paired_interval
from prono.metrics import performance
from prono.model import score_probabilities,predict_rows,predict
from prono.history_import import FIELDS
from prono.market_watch import normalize_markets

ROOT=Path(__file__).resolve().parents[1]

class TrackingEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);(root/'config').mkdir();shutil.copy(ROOT/'config/workspace.toml',root/'config/workspace.toml')
        self.ws=Workspace(root);self.child=league_workspace(self.ws,'F1',create=True)
        self.now=timestamp('2026-10-10T10:00:00Z')
        self.fixture={'event_id':'fixture-test','division':'F1','home':'A','away':'B','kickoff':'2026-10-10T18:00:00Z',
                      'source':'test-only','collected_at':self.now.isoformat(),'quoted_at':None,'offers':[]}
        self.row={'division':'F1','fixture':self.fixture,'model':{'available':True,'model':'poisson-baseline-v1',
                  'as_of':self.now.isoformat(),'probabilities':{'home':.5,'draw':.3,'away':.2}},
                  'outcome':'home','status':'abstention','reasons':['Cotation inconnue'],'synthetic':False}

    def save(self):
        with patch('prono.pronos.selections',return_value={'matches':[self.row]}):return capture(self.ws,self.now)

    def history(self,rows):
        p=self.child.path('data/history.csv');p.parent.mkdir(exist_ok=True)
        with p.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)

    def result_row(self,**changes):
        return {'event_id':'result-test','kickoff':self.fixture['kickoff'],'home':'A','away':'B',
                'home_goals':2,'away_goals':0,'result_known_at':'2026-10-10T21:00:00Z','source':'test-result',**changes}

    def test_forecast_is_immutable_despite_new_probabilities_and_no_quote_time(self):
        self.assertEqual(self.save()['added'],1)
        path=next(self.ws.path('analyses').glob('forecast-*.md'));original=path.read_bytes()
        self.row['model']['probabilities']={'home':.2,'draw':.3,'away':.5}
        self.assertEqual(self.save()['added'],0);self.assertEqual(path.read_bytes(),original)
        record=read_record(path);self.assertEqual(record['probabilities']['home'],.5)
        self.assertIsNone(record['fixture']['quoted_at']);self.assertEqual(record['paper_status'],'abstention')
        self.assertFalse(list(self.ws.path('journal').glob('*.md')))

    def test_known_result_only_settles_after_knowledge_and_original_is_unchanged(self):
        self.save();forecast=next(self.ws.path('analyses').glob('forecast-*.md'));original=forecast.read_bytes()
        self.history([self.result_row()])
        self.assertEqual(reconcile(self.ws,timestamp('2026-10-10T20:00:00Z'))['settled'],0)
        self.assertEqual(reconcile(self.ws,timestamp('2026-10-10T21:00:00Z'))['settled'],1)
        self.assertEqual(reconcile(self.ws,timestamp('2026-10-10T22:00:00Z'))['settled'],0)
        summary=tracking_summary(self.ws)
        self.assertEqual(summary['performance']['evaluated'],1);self.assertEqual(summary['performance']['accuracy'],1)
        self.assertAlmostEqual(summary['performance']['brier'],.38)
        self.assertEqual(forecast.read_bytes(),original)

    def test_started_or_future_calculation_is_not_archived(self):
        self.fixture['kickoff']=self.now.isoformat();self.assertEqual(self.save()['added'],0)
        self.fixture['kickoff']='2026-10-10T18:00:00Z';self.row['model']['as_of']='2026-10-10T12:00:00Z'
        self.assertEqual(self.save()['added'],0)

    def test_expanded_history_counts_old_and_recent_without_future_knowledge(self):
        config={**self.ws.config['model'],'min_matches_per_team':1,'max_history_days':3653}
        rows=[self.result_row(kickoff='2019-09-01T19:00:00Z',result_known_at='2020-01-01T12:00:00Z'),
              self.result_row(event_id='recent',kickoff='2026-09-01T19:00:00Z',result_known_at='2026-09-02T12:00:00Z'),
              self.result_row(event_id='later-knowledge',kickoff='2026-09-02T19:00:00Z',result_known_at='2026-10-11T12:00:00Z'),
              self.result_row(event_id='outside-window',kickoff='2015-09-01T19:00:00Z',result_known_at='2015-09-02T12:00:00Z')]
        enlarged=predict(rows,'A','B',self.now,config)
        recent=predict(rows,'A','B',self.now,{**config,'max_history_days':730})
        self.assertEqual(enlarged['sample']['home'],2);self.assertEqual(recent['sample']['home'],1)
        self.assertEqual(enlarged['sample_period']['home_recent'],1)
        self.assertEqual(enlarged['sample_period']['home_oldest'],'2019-09-01T19:00:00Z')
        self.assertEqual(enlarged['model'],'poisson-baseline-v1')

    def test_live_capture_rechecks_kickoff_after_calculation(self):
        started=timestamp(self.fixture['kickoff'])
        with patch('prono.tracking.utcnow',side_effect=[self.now,started,started]),patch('prono.pronos.selections',return_value={'matches':[self.row]}):
            self.assertEqual(capture(self.ws)['added'],0)
        self.assertFalse(list(self.ws.path('analyses').glob('forecast-*.md')))

    def test_duplicate_conflicting_results_do_not_get_chosen(self):
        self.save();self.history([self.result_row(),self.result_row(event_id='other',home_goals=0,away_goals=1)])
        result=reconcile(self.ws,timestamp('2026-10-10T22:00:00Z'))
        self.assertEqual(result['settled'],0);self.assertEqual(len(result['conflicts']),1)

    def test_rescheduled_forecast_is_excluded_from_scoring(self):
        self.save()
        path=self.ws.path('data/match-registry.json');path.write_text(json.dumps({'matches':{'fixture-test':{'kickoff':'2026-10-12T18:00:00Z'}}}))
        self.assertEqual(reconcile(self.ws,self.now)['rescheduled'],1)
        result=tracking_summary(self.ws);self.assertEqual(result['rescheduled'],1);self.assertEqual(result['performance']['evaluated'],0)

    def test_result_refresh_is_scoped_rate_limited_and_does_not_call_odds_api(self):
        self.save();later=timestamp('2026-10-10T22:00:00Z')
        with patch('prono.history_import.sync_history',return_value={'added':1}) as fetch,patch('prono.providers.sync_odds') as paid:
            self.assertEqual(len(refresh_due_results(self.ws,later)['imports']),1)
            self.assertEqual(refresh_due_results(self.ws,later+timedelta(minutes=30))['imports'],[])
            self.assertEqual(len(refresh_due_results(self.ws,later+timedelta(hours=1))['imports']),1)
            self.assertEqual(fetch.call_count,2);paid.assert_not_called()
            self.assertEqual(fetch.call_args.args[1],['2627'])

    def test_existing_workspace_gets_tracking_defaults_and_can_disable_imports(self):
        self.save();self.ws.config.pop('tracking')
        with patch('prono.history_import.sync_history',return_value={'added':0}) as fetch:
            self.assertEqual(len(refresh_due_results(self.ws,timestamp('2026-10-10T22:00:00Z'))['imports']),1)
            self.ws.config['tracking']={'auto_refresh_results':False}
            self.assertFalse(refresh_due_results(self.ws,timestamp('2026-10-11T22:00:00Z'))['enabled'])
            self.assertEqual(fetch.call_count,1)

    def test_registry_keeps_id_for_unique_future_schedule_revision(self):
        first=register_matches(self.ws,{'matches':[copy.deepcopy(self.fixture)],'collected_at':self.now.isoformat()})
        changed=copy.deepcopy(self.fixture);changed.update(event_id='changed-source-id',kickoff='2026-10-12T18:00:00Z')
        second=register_matches(self.ws,{'matches':[changed],'collected_at':(self.now+timedelta(hours=1)).isoformat()})
        self.assertEqual(second['matches'][0]['event_id'],first['matches'][0]['event_id'])
        self.assertEqual(second['matches'][0]['source_event_id'],'changed-source-id')
        self.assertEqual(len(second['matches'][0]['schedule_revisions']),1)

    def test_registry_does_not_merge_two_games_or_past_games(self):
        first=copy.deepcopy(self.fixture);other=copy.deepcopy(self.fixture);other.update(event_id='second',kickoff='2026-10-15T18:00:00Z')
        register_matches(self.ws,{'matches':[first,other],'collected_at':self.now.isoformat()})
        new=copy.deepcopy(self.fixture);new.update(event_id='new',kickoff='2026-10-12T18:00:00Z')
        result=register_matches(self.ws,{'matches':[new],'collected_at':self.now.isoformat()})
        self.assertEqual(result['matches'][0]['event_id'],'new');self.assertIn('identity_warning',result['matches'][0])

    def test_explicit_postponement_link_survives_next_source_import(self):
        first=register_matches(self.ws,{'matches':[copy.deepcopy(self.fixture)],'collected_at':self.now.isoformat()})
        new=copy.deepcopy(self.fixture);new.update(event_id='new',kickoff='2026-10-12T18:00:00Z')
        later=timestamp('2026-10-10T20:00:00Z')
        second=register_matches(self.ws,{'matches':[new],'collected_at':later.isoformat()})
        self.ws.path('data/market-watch.json').write_text(json.dumps(second))
        link_schedule(self.ws,'fixture-test','new',later)
        again=register_matches(self.ws,{'matches':[copy.deepcopy(new)],'collected_at':later.isoformat()})
        self.assertEqual(again['matches'][0]['event_id'],'fixture-test')
        self.assertEqual(again['matches'][0]['schedule_revisions'][0]['confirmation'],'manual')

    def test_aliases_are_explicit_and_clubs_are_namespaced_by_league(self):
        p=self.ws.path('data/team-aliases.json');p.write_text(json.dumps({'F1':{'alias a':'a'}}))
        self.assertEqual(team_id(self.ws,'F1','Alias A'),team_id(self.ws,'F1','A'))
        self.assertNotEqual(team_id(self.ws,'F1','A'),team_id(self.ws,'E0','A'))
        self.assertNotEqual(team_id(self.ws,'F1','Club A'),team_id(self.ws,'F1','A'))

    def test_freshness_never_promotes_collection_to_quote_time(self):
        self.assertIn('Collecte récente',freshness(self.fixture,self.now));self.assertIn('cotation inconnue',freshness(self.fixture,self.now))
        self.assertIn('ancienne',freshness(self.fixture,self.now+timedelta(hours=7)))
        self.assertIsNone(self.fixture['quoted_at'])

    def test_price_variation_is_for_same_bookmaker_and_capture_only(self):
        previous=copy.deepcopy(self.fixture);previous['offers']=[{'bookmaker':'One','odds':{'home':2,'draw':3,'away':4}}]
        current=copy.deepcopy(previous);current['offers'][0]['odds']['home']=2.2
        changes=price_changes([previous],[current]);self.assertEqual(changes[0]['bookmaker'],'One');self.assertIn('capture',changes[0]['notice'])
        current['offers'][0]['bookmaker']='Other';self.assertEqual(price_changes([previous],[current]),[])

    def test_invalid_bookmaker_does_not_hide_valid_triplet(self):
        csv='Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,BWH,BWD,BWA\nF1,10/10/2026,20:00,A,B,nan,3,4,2.1,3.2,4.1\n'
        result=normalize_markets(csv,self.now.isoformat())
        self.assertEqual(len(result['matches']),1);self.assertEqual(result['matches'][0]['offers'][0]['bookmaker'],'Bwin')
        self.assertEqual(len(result['rejected']),1)

    def research_history(self):
        start=timestamp('2026-01-01T18:00:00Z');teams=['A','B','C','D']
        return [self.result_row(event_id=str(i),kickoff=(start+timedelta(days=i*2)).isoformat(),home=teams[i%4],away=teams[(i+1)%4],
                               home_goals=i%3,away_goals=(i*2)%3) for i in range(100)]

    def test_research_has_evaluable_matches_without_backdating_knowledge(self):
        self.history(self.research_history());path=self.child.path('data/history.csv');original=path.read_bytes()
        now=timestamp('2026-10-11T10:00:00Z')
        observed=evaluate_league(self.child,'observed',now);research=evaluate_league(self.child,'snapshot',now)
        self.assertEqual(observed['models']['poisson-baseline-v1']['evaluated'],0)
        self.assertEqual(research['models']['poisson-baseline-v1']['evaluated'],20)
        self.assertIn('hypothèse',research['notice']);self.assertFalse(research['promoted'])
        self.assertEqual(path.read_bytes(),original)
        for variant,rows in research['predictions'].items():
            self.assertEqual(len(rows),20)
            for row in rows:self.assertLessEqual(timestamp(row['training_latest_kickoff']),timestamp(row['kickoff'])-timedelta(hours=24))

    def test_experimental_parameters_use_only_training_rows_and_leave_baseline_intact(self):
        rows=self.research_history()[:50];now=timestamp('2026-10-01T10:00:00Z')
        config=self.ws.config['model'];before=copy.deepcopy(rows)
        for kwargs in [{},{'half_life_days':180},{'half_life_days':180,'correction':True}]:
            result=predict_rows(rows,'A','B',now,config,**kwargs)
            self.assertAlmostEqual(sum(result['probabilities'].values()),1)
            self.assertTrue(all(0<=v<=1 for v in result['probabilities'].values()))
        self.assertEqual(rows,before);self.assertEqual(predict_rows(rows,'A','B',now,config)['model'],'poisson-baseline-v1')

    def test_optimized_poisson_matches_original_grid(self):
        for lh,la in [(.05,.05),(1.7,.9),(8,8)]:
            expected=dict.fromkeys(('home','draw','away'),0.0)
            for i in range(41):
                for j in range(41):expected['home' if i>j else 'away' if j>i else 'draw']+=math.exp(-lh)*lh**i/math.factorial(i)*math.exp(-la)*la**j/math.factorial(j)
            total=sum(expected.values());actual=score_probabilities(lh,la)
            for key in expected:self.assertAlmostEqual(actual[key],expected[key]/total,places=12)

    def test_calibration_and_intervals_are_deterministic_with_empty_support(self):
        self.assertIsNone(performance([])['brier'])
        rows=[{'probabilities':{'home':.5,'draw':.3,'away':.2},'actual':'home','kickoff':(self.now+timedelta(weeks=i)).isoformat()} for i in range(10)]
        self.assertEqual(paired_interval(rows,rows),paired_interval(rows,rows));self.assertEqual(paired_interval(rows,rows)['delta_brier'],0)
        self.assertEqual(sum(b['count'] for b in performance(rows)['calibration']),30)

    def test_exclusive_record_never_overwrites(self):
        path=self.ws.path('analyses/frozen.md')
        self.assertTrue(write_record_once(path,'test',{'value':1}));self.assertFalse(write_record_once(path,'test',{'value':2}))
        self.assertEqual(read_record(path)['value'],1)
