import copy
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from prono.shortlist import rank_matches,validate_count
from prono.chat import coach_facts,reply
from prono.team import prepare_context,run_team,receipts,TeamJobs
from prono.workspace import Workspace,read_record

ROOT=Path(__file__).resolve().parents[1]
NOW='2026-10-12T10:00:00Z'

def row(ident,p=.60,recent=15,kickoff='2026-10-13T19:00:00Z'):
    return {'division':'UCL','fixture':{'event_id':str(ident),'home':'A'+str(ident),'away':'B'+str(ident),'kickoff':kickoff,
            'source':'test-only','quoted_at':None,'offers':[{'bookmaker':'Example','odds':{'home':2,'draw':3,'away':4}}]},
            'model':{'available':True,'probabilities':{'home':p,'draw':(1-p)*.6,'away':(1-p)*.4},'sample':{'home':30,'away':30},
                     'sample_period':{'recent_days':730,'home_recent':recent,'away_recent':recent,
                                      'home_latest':'2026-09-20T19:00:00Z','away_latest':'2026-09-20T19:00:00Z'}},
            'outcome':'home','status':'abstention','comparison':None,'reasons':['Cotes indicatives'],'synthetic':True}

class ShortlistTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);(root/'config').mkdir();shutil.copy(ROOT/'config/workspace.toml',root/'config/workspace.toml')
        self.ws=Workspace(root)

    def test_manual_batch_keeps_exact_scope_before_display_limit(self):
        rows = [row(i, .55) for i in range(40)] + [row('weak', .49)]
        original = copy.deepcopy(rows)
        with patch('prono.pronos.selections', return_value={'created_at': NOW, 'matches': rows, 'notice': 'Test'}):
            facts = coach_facts(self.ws, 'UCL', 'next3', event_ids=['39', 'weak'])
            context = prepare_context(self.ws, 'UCL', 'next3', event_ids=['39', 'weak'])
        self.assertEqual({r['event_id'] for r in context['matches']}, {'39', 'weak'})
        self.assertEqual({r['event_id'] for r in facts['matches']}, {'39', 'weak'})
        self.assertEqual(facts['selection']['mode'], 'manual')
        self.assertEqual(facts['selection']['requested'], 2)
        audit = next(r for r in facts['selection']['rows'] if r['event_id'] == 'weak')
        self.assertTrue(audit['selected'])
        self.assertTrue(audit['exclusions'])
        self.assertEqual(rows, original)

    def test_manual_batch_invalid_scope_is_refused(self):
        for ids in ([], ['x'] * 2, list('abcdef'), 'x', [42], ['missing']):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                rank_matches([row('x')], {}, NOW, event_ids=ids)
        with self.assertRaises(ValueError):
            rank_matches([row('x')], {}, NOW, event_id='x', event_ids=['x'])
        with self.assertRaisesRegex(ValueError, 'ambigu'):
            duplicate = row('x'); duplicate['division'] = 'F1'
            rank_matches([row('x'), duplicate], {}, NOW, event_ids=['x'])

    def test_manual_batch_rejects_kickoff_at_or_before_analysis(self):
        for kickoff in (NOW, '2026-10-12T09:59:59Z'):
            with self.subTest(kickoff=kickoff), self.assertRaisesRegex(ValueError, 'commencé'):
                rank_matches([row('x', kickoff=kickoff)], {}, NOW, event_ids=['x'])
        _, report = rank_matches([row('x', kickoff='2026-10-12T10:00:01Z')], {}, NOW, event_ids=['x'])
        self.assertEqual(report['selected'], 1)

    def test_later_stronger_match_is_selected_beyond_the_old_thirty_match_cutoff(self):
        rows=[row(i,.55,kickoff='2026-10-13T16:45:00Z') for i in range(39)]+[row('best',.80)]
        facts={'created_at':NOW,'matches':rows,'notice':'Test'}
        with patch('prono.pronos.selections',return_value=facts):
            context=prepare_context(self.ws,'UCL','next3')
        self.assertEqual(context['matches'][0]['event_id'],'best')
        self.assertEqual(context['selection']['scanned'],40)
        self.assertEqual(len(context['matches']),3)
        self.assertTrue(any(r['selected'] and r['event_id']=='best' for r in context['selection']['rows']))

    def test_chat_display_limit_is_applied_after_ranking_all_matches(self):
        rows=[row(i,.55) for i in range(40)]+[row('last',.85)]
        with patch('prono.pronos.selections',return_value={'created_at':NOW,'matches':rows,'notice':'Test'}):facts=coach_facts(self.ws,'UCL','next3')
        self.assertEqual(len(facts['matches']),30);self.assertEqual(facts['matches'][0]['event_id'],'last')
        self.assertEqual(facts['selection']['scanned'],41)

    def test_old_sample_without_recent_evidence_and_weak_choice_are_excluded(self):
        rows=[row('good',.7),row('old',.9,1),row('weak',.49)]
        ordered,report=rank_matches(rows,{},NOW,3)
        selected=[a['event_id'] for a in report['rows'] if a['selected']]
        self.assertEqual(selected,['good']);self.assertEqual(report['selected'],1)
        self.assertTrue(next(a for a in report['rows'] if a['event_id']=='old')['exclusions'])
        self.assertTrue(next(a for a in report['rows'] if a['event_id']=='weak')['exclusions'])

    def test_current_triplet_does_not_establish_value_without_verified_quote(self):
        a=row('highest',.8);b=row('lower',.6);b['comparison']={'expected_return_per_unit':99}
        ordered,report=rank_matches([b,a],{},NOW)
        self.assertEqual(ordered[0]['fixture']['event_id'],'highest')
        self.assertTrue(all(a['expected_return_per_unit'] is None for a in report['rows']))

    def test_verified_positive_expectation_does_not_change_priority(self):
        a=row('observation',.8);b=row('verified',.6)
        b['status']='candidate';b['fixture']['quoted_at']=NOW;b['comparison']={'expected_return_per_unit':.2}
        ordered,report=rank_matches([a,b],{},NOW,1)
        self.assertEqual(ordered[0]['fixture']['event_id'],'observation')
        self.assertEqual(next(r for r in report['rows'] if r['event_id']=='verified')['category'],'paper_candidate')
        b['status']='abstention'
        self.assertEqual(rank_matches([a,b],{},NOW,1)[0][0]['fixture']['event_id'],'observation')

    def test_selection_is_deterministic_under_shuffle_and_does_not_mutate_inputs(self):
        rows=[row(i,.6) for i in range(6)];original=copy.deepcopy(rows)
        before=rank_matches(rows,{},NOW)[1]
        self.assertEqual(rows,original);random.Random(42).shuffle(rows)
        self.assertEqual(rank_matches(rows,{},NOW)[1],before)

    def test_stale_future_or_missing_team_history_is_not_eligible(self):
        for value in ['2025-01-01T12:00:00Z','2026-10-13T12:00:00Z',None]:
            a=row('stale',.9);a['model']['sample_period']['home_latest']=value
            self.assertEqual(rank_matches([a],{},NOW)[1]['selected'],0)

    def test_manual_match_is_exact_and_does_not_get_padded_with_other_matches(self):
        rows=[row('good',.8),row('manual',.45,1)]
        with patch('prono.pronos.selections',return_value={'created_at':NOW,'matches':rows,'notice':'Test'}):
            context=prepare_context(self.ws,'UCL','next3','manual')
        self.assertEqual([r['event_id'] for r in context['matches']],['manual'])
        self.assertEqual(context['selection']['mode'],'manual')
        self.assertTrue(next(a for a in context['selection']['rows'] if a['event_id']=='manual')['exclusions'])

    def test_empty_automatic_selection_never_calls_a_model_or_fills_with_first_matches(self):
        with patch('prono.pronos.selections',return_value={'created_at':NOW,'matches':[row('weak',.49)],'notice':'Test'}),patch('prono.team.call_model') as model:
            with self.assertRaisesRegex(ValueError,'Aucun match'):prepare_context(self.ws,'UCL','next3')
        model.assert_not_called()

    def test_count_limits_and_tied_probabilities_are_not_arbitrary_choices(self):
        for invalid in [True,0,6,'3',3.0]:
            with self.assertRaises(ValueError):validate_count(invalid)
        a=row('tie');a['model']['probabilities']={'home':.45,'draw':.45,'away':.1}
        self.assertEqual(rank_matches([a],{},NOW)[1]['selected'],0)
        self.assertEqual(rank_matches([row(i,.6) for i in range(7)],{},NOW,5)[1]['selected'],5)

    def test_real_team_preparation_archives_selection_and_restores_it_in_receipts(self):
        rows=[row(i,.55) for i in range(39)]+[row('last',.85)]
        def adapter(*args,**kwargs):return {'answer':'Avis SIMULÉ, aucun web appelé.','model':'test'}
        with patch('prono.pronos.selections',return_value={'created_at':NOW,'matches':rows,'notice':'SYNTHÉTIQUE'}),patch('prono.team.claude_path',return_value='/test/claude'),patch('prono.team.call_model',side_effect=adapter) as calls:
            result=run_team(self.ws,'Prépare mes pronos','claude','',league='UCL',period='next3',strategy='adaptive',selection_count=2)
        self.assertEqual(result['selection']['scanned'],40);self.assertEqual(len(result['scope']),2)
        self.assertEqual(result['scope'][0]['event_id'],'last');self.assertEqual(calls.call_count,3)
        record=read_record(self.ws.path('analyses/team-'+result['run_id']+'.md'))
        self.assertEqual(record['facts']['selection'],receipts(self.ws,result['run_id'])[0]['selection'])
        self.assertEqual(TeamJobs(self.ws).get(result['run_id'])['result']['selection'],result['selection'])

    def test_normal_coach_discussion_also_receives_the_manually_selected_match(self):
        import json
        rows=[row(i,.6) for i in range(40)]+[row('manual',.45,1)]
        with patch('prono.pronos.selections',return_value={'created_at':NOW,'matches':rows,'notice':'Test'}),patch('prono.chat.models',return_value=['test']),patch('prono.chat.call_model',return_value={'answer':'SIMULÉ','model':'test'}) as model:
            reply(self.ws,'Explique ce match','test',league='UCL',period='next3',event_id='manual',selection_count=5)
        facts=json.loads(model.call_args.args[2].split('\n',1)[1])
        self.assertEqual([r['event_id'] for r in facts['matches']],['manual'])
        self.assertEqual(facts['selection']['mode'],'manual')
