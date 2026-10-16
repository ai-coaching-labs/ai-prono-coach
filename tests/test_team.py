import copy
import json
import re
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from prono.chat import coach_facts, claude_reply
from prono.team import ROLES, TeamJobs, explicit_team_request, prepare_context, prompt_context, receipts, run_team
from prono.workspace import Workspace, read_record

ROOT = Path(__file__).resolve().parents[1]


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root/'config').mkdir()
        shutil.copy(ROOT/'config/workspace.toml',root/'config/workspace.toml')
        self.ws = Workspace(root)
        self.context = {'matches':[{'event_id':'fixture-test','division':'F1','match':'A / B',
                         'kickoff':'2026-10-10T18:00:00Z','model_pick':'home',
                         'probabilities':{'home':0.5,'draw':0.3,'away':0.2},'quoted_at':None}],
                        'matches_total':1,'context':[],'notice':'SYNTHÉTIQUE',
                        'paper_limits':self.ws.config['paper']}

    def execute(self, adapter, **kwargs):
        kwargs.setdefault('strategy', 'full')
        with patch('prono.team.prepare_context',return_value=copy.deepcopy(self.context)), \
             patch('prono.team.claude_path',return_value='/test/claude'), \
             patch('prono.team.models',return_value=['test-local']):
            with patch('prono.team.call_model',side_effect=adapter):
                return run_team(self.ws,'Consulte les spécialistes','claude','',**kwargs)

    def test_actual_calls_dependencies_archive_and_python_facts(self):
        calls = []
        lock = threading.Lock()
        def adapter(ws,message,system,previous,provider,model,web):
            role = system.split('MISSION DU RÔLE ')[1].split('\n')[0] if 'MISSION DU RÔLE ' in system else 'coach'
            with lock: calls.append((role,system,web))
            return {'answer':'Avis '+role+' : chiffre inventé 999 à ignorer.', 'model':'test','network':'test'}
        result = self.execute(adapter)
        self.assertEqual({r[0] for r in calls},set(ROLES))
        self.assertEqual(len(calls),8)
        ordered = [r[0] for r in calls]
        self.assertLess(ordered.index('sports-journalist'),ordered.index('lineup-analyst'))
        self.assertLess(ordered.index('lineup-analyst'),ordered.index('match-analyst'))
        self.assertEqual(ordered[-1],'coach')
        for role,system,web in calls:
            self.assertEqual(web,ROLES[role][1])
        self.assertIn('Avis sports-journalist',next(s for r,s,w in calls if r=='lineup-analyst'))
        self.assertNotIn('Avis market-analyst',next(s for r,s,w in calls if r=='lineup-analyst'))
        self.assertIn('Avis lineup-analyst',next(s for r,s,w in calls if r=='match-analyst'))
        self.assertIn('Avis bookmaker-expert',calls[-1][1])
        record = read_record(self.ws.path('analyses/team-'+result['run_id']+'.md'))
        self.assertEqual(record['facts']['matches'][0]['probabilities'],self.context['matches'][0]['probabilities'])
        self.assertIsNone(record['facts']['matches'][0]['quoted_at'])
        self.assertEqual(len(receipts(self.ws,result['run_id'])[0]['roles']),8)
        restored = TeamJobs(self.ws).get(result['run_id'])
        self.assertEqual(restored['result']['answer'],result['answer'])

    def test_prompt_omits_unconsulted_rows_but_preserves_complete_trace_and_dates(self):
        context = copy.deepcopy(self.context)
        row = {'event_id':'fixture-test', 'division':'F1', 'kickoff':'2026-10-10T18:00:00Z',
               'exclusions':['Sample limited'], 'selected': True}
        context['selection'] = {'considered': 2, 'rows': [row, {**row, 'event_id':'other'}]}
        original = copy.deepcopy(context)
        compact = prompt_context(context)
        self.assertEqual(compact['selection']['rows'], [row])
        self.assertEqual(compact['selection']['considered'], 2)
        self.assertEqual(compact['selection']['unselected_rows_omitted'], 1)
        self.assertEqual(compact['matches'], context['matches'])
        self.assertEqual(context, original)

    def test_missing_python_history_allows_qualitative_verdict_and_preserves_facts(self):
        match = self.context['matches'][0]
        match['model_pick'] = None
        match['probabilities'] = None
        match['forecast_details'] = None
        match['kickoff'] = '2099-01-01T18:00:00Z'
        self.context['context'] = [{'source': 'https://example.org/synthetic',
                                    'notice': 'SYNTHÉTIQUE : forme domicile documentée'}]
        expected = copy.deepcopy(self.context)
        prompts = []
        def adapter(ws, message, system, *args, **kwargs):
            prompts.append(system)
            answer = json.dumps({'verdicts':[{'event_id':'fixture-test','outcome':'home','score':[2,1],
                                              'confidence':'faible','reason':'Forme domicile sourcée.',
                                              'reserve':'Échantillon limité.'}]}) if 'MISSION DU RÔLE' not in system else 'Avis terrain.'
            return {'answer': answer,
                    'model': 'test'}
        result = self.execute(adapter, strategy='adaptive')
        self.assertEqual(len(prompts), 3)
        self.assertTrue(all('CONSULTATION AVEUGLE' in p for p in prompts))
        self.assertIn('une orientation qualitative 1/N/2', prompts[0])
        self.assertIn('Tu ne connais pas le résultat du moteur statistique', prompts[-1])
        self.assertIn('Ce scénario peut être proposé sans calcul Python', prompts[-1])
        self.assertIn('La confiance porte sur le pronostic 1N2, pas sur ce score exact', prompts[-1])
        self.assertNotIn('"model_pick":', prompts[-1])
        record = read_record(self.ws.path('analyses/team-'+result['run_id']+'.md'))
        self.assertEqual(record['facts'], expected)
        self.assertEqual(record['answer'], result['answer'])
        self.assertIn('faible', result['answer'])
        self.assertEqual(record['llm_verdicts'][0]['outcome'], 'home')

    def test_user_enabled_roles_only_and_no_web_for_local(self):
        self.ws.path('config/workspace.user.toml').write_text('[agents]\nenabled = ["coach", "match-analyst"]\n')
        self.ws = Workspace(self.ws.root)
        calls = []
        def adapter(*args,**kwargs):
            calls.append((args[2],kwargs['web']))
            return {'answer':'Test','model':'test'}
        with patch('prono.team.prepare_context',return_value=self.context),patch('prono.team.models',return_value=['test-local']),patch('prono.team.call_model',side_effect=adapter):
            run_team(self.ws,'Analyse ce match','local','test-local')
        self.assertEqual(len(calls),2)
        self.assertTrue(all(not web for system,web in calls))
        self.assertNotIn('MISSION DU RÔLE sports-journalist',calls[0][0])
        self.assertEqual(self.ws.config['paper']['unit'],1)

    def test_failed_specialist_is_reported_without_fabricated_advice(self):
        def adapter(ws,message,system,*args,**kwargs):
            if 'MISSION DU RÔLE sports-journalist\n' in system: raise ValueError('Source indisponible')
            if 'MISSION DU RÔLE ' not in system:
                self.assertIn('Source indisponible',system)
            return {'answer':'Test','model':'test'}
        result = self.execute(adapter)
        failed = next(r for r in result['reviews'] if r['role']=='sports-journalist')
        self.assertEqual(failed['status'],'error')
        self.assertNotIn('answer',failed)
        self.assertEqual(receipts(self.ws,result['run_id'])[0]['roles'][1]['status'],'error')

    def test_final_coach_failure_preserves_received_reports(self):
        def adapter(ws,message,system,*args,**kwargs):
            if 'MISSION DU RÔLE ' not in system: raise ValueError('Quota de test')
            return {'answer':'Avis reçu','model':'test'}
        with self.assertRaisesRegex(ValueError,'Quota de test'): self.execute(adapter)
        record = self.ws.records('analyses')[0]
        self.assertEqual(record['status'],'error')
        self.assertEqual(record['reviews'][-1]['status'],'error')
        self.assertEqual(sum(r['status']=='completed' for r in record['reviews']),7)

    def test_kickoff_passed_during_consultation_is_marked_for_abstention(self):
        systems = []
        def adapter(ws,message,system,*args,**kwargs):
            systems.append(system)
            return {'answer':'Test','model':'test'}
        with patch('prono.team.utcnow',return_value=datetime(2026,10,10,18,1,tzinfo=timezone.utc)):
            self.execute(adapter)
        coach = json.loads(systems[-1].split('\n',1)[1].split('\n')[0])
        self.assertEqual(coach['expired_match_ids'],['fixture-test'])

    def test_missing_coach_prevents_all_model_calls(self):
        self.ws.config['agents']['enabled']=['sports-journalist']
        with patch('prono.team.claude_path',return_value='/test/claude'),patch('prono.team.call_model') as call:
            with self.assertRaisesRegex(ValueError,'désactivé'):run_team(self.ws,'Test','claude','')
            call.assert_not_called()

    def test_all_eight_roles_are_blind_and_comparison_is_added_only_after_final_call(self):
        self.context['matches'][0].update(kickoff='2099-01-01T18:00:00Z',
            probabilities={'home':.51234567891,'draw':.3,'away':.18765432109},
            expected_goals={'home':'SECRET_RATE'}, comparison={'value':'SECRET_EDGE'},
            forecast_details={'most_likely_scores':['SECRET_SCORE']},
            reasons=['SECRET_REASON'],status='SECRET_STATUS',
            domestic_form={'home':{'last5':{'wins':3}}})
        self.context['selection']={'rows':[{'rank':'SECRET_RANK'}]}
        calls=[]
        def adapter(ws,message,system,previous,*args,**kwargs):
            calls.append(system)
            for secret in ('0.51234567891','SECRET_RATE','SECRET_EDGE','SECRET_SCORE','SECRET_REASON','SECRET_STATUS','SECRET_RANK'):
                self.assertNotIn(secret,system)
            data=json.loads(system.split('\n',1)[1].split('\n')[0])
            self.assertNotIn('model_pick',json.dumps(data))
            self.assertEqual(data['matches'][0]['domestic_form']['home']['last5']['wins'],3)
            answer='Avis terrain sourcé.'
            if 'MISSION DU RÔLE ' not in system:
                answer=json.dumps({'verdicts':[{'event_id':'fixture-test','outcome':'away','score':[0,1],
                                                'confidence':'faible','reason':'Forme observée.','reserve':'Absences incertaines.'}]})
            return {'answer':answer,'model':'test'}
        result=self.execute(adapter)
        self.assertEqual(len(calls),8)
        self.assertIn('désaccord avec Python',result['answer'])
        record=read_record(self.ws.path('analyses/team-'+result['run_id']+'.md'))
        self.assertEqual(record['blind_protocol'],'all-roles-blind-v8')
        self.assertEqual(record['llm_verdicts'][0]['outcome'],'away')
        self.assertEqual(record['facts']['matches'][0]['model_pick'],'home')

    def test_changing_only_python_predictions_keeps_blind_reports_reusable(self):
        def adapter(*args,**kwargs):return {'answer':'Avis https://example.test/source','model':'test'}
        self.execute(adapter)
        self.context['matches'][0].update(model_pick='away',probabilities={'home':.1,'draw':.2,'away':.7})
        result=self.execute(adapter)
        self.assertEqual(result['stats']['reused_reports'],3)

    def test_scope_is_bounded_and_no_matches_prevents_call(self):
        facts = copy.deepcopy(self.context)
        facts['matches'] = [dict(facts['matches'][0],event_id=str(i)) for i in range(6)]
        facts['selection']={'rows':[{'division':'F1','event_id':str(i),'selected':i<3} for i in range(6)]}
        with patch('prono.team.coach_facts',return_value=facts):
            self.assertEqual(len(prepare_context(self.ws,'all','today')['matches']),3)
        facts['matches']=[]
        facts['selection']['rows']=[]
        with patch('prono.team.coach_facts',return_value=facts),patch('prono.team.call_model') as call:
            with self.assertRaisesRegex(ValueError,'Aucun match'):prepare_context(self.ws,'all','today')
            call.assert_not_called()

    def test_selected_match_is_filtered_before_thirty_match_limit(self):
        rows=[]
        for i in range(40):
            fixture={'event_id':str(i),'home':'A','away':'B','kickoff':'2099-01-01T18:00:00Z','source':'test'}
            rows.append({'fixture':fixture,'division':'F1','model':{},'status':'abstention','outcome':None,'reasons':[],'synthetic':True})
        with patch('prono.pronos.selections',return_value={'matches':rows,'notice':'Test'}):
            result=coach_facts(self.ws,event_id='39')
        self.assertEqual(result['matches'][0]['event_id'],'39')
        self.assertEqual(len(result['matches']),1)

    def test_polling_never_repeats_calls_and_second_job_is_refused(self):
        started,release,finished=threading.Event(),threading.Event(),threading.Event()
        jobs=TeamJobs(self.ws)
        def task(*args):
            started.set()
            release.wait(5)
            finished.set()
            return {'answer':'Test','model':'test'}
        with patch('prono.team.run_team',side_effect=task) as run:
            run_id=jobs.start({'message':'Test'})
            self.assertTrue(started.wait(5))
            try:
                for i in range(5): self.assertEqual(jobs.get(run_id)['status'],'running')
                with self.assertRaisesRegex(ValueError,'déjà en cours'):jobs.start({'message':'Test'})
                run.assert_called_once()
            finally: release.set()
            self.assertTrue(finished.wait(5))

    def test_invalid_receipts_and_past_or_negated_questions(self):
        for bad in ['../config/workspace.toml','xyz',[],None]:
            with self.assertRaises(ValueError):receipts(self.ws,bad)
        self.assertFalse(explicit_team_request("t’as consulté l’agent bookmaker ?"))
        self.assertFalse(explicit_team_request('Ne consulte pas le bookmaker'))
        self.assertTrue(explicit_team_request('Peux-tu consulter le journaliste ?'))

    def test_coach_claude_has_no_web_tools(self):
        import subprocess
        result=subprocess.CompletedProcess([],0,json.dumps({'result':'Test'}))
        with patch('prono.chat.claude_path',return_value='/test/claude'),patch('prono.chat.subprocess.run',return_value=result) as process:
            claude_reply(self.ws,'Test','Test',[],web=False)
        args=process.call_args.args[0]
        self.assertEqual(args[args.index('--tools')+1],'')
        self.assertEqual(args[args.index('--allowedTools')+1],'')

    def test_adaptive_team_only_calls_useful_enabled_roles(self):
        calls=[]
        def adapter(ws,message,system,*args,**kwargs):
            role=system.split('MISSION DU RÔLE ')[1].split('\n')[0] if 'MISSION DU RÔLE ' in system else 'coach'
            calls.append(role);return {'answer':'Test','model':'test'}
        with patch('prono.team.prepare_context',return_value=self.context),patch('prono.team.claude_path',return_value='/test/claude'),patch('prono.team.call_model',side_effect=adapter):
            result=run_team(self.ws,'Prépare mes pronos avec actualités, absents et cotes','claude','',strategy='adaptive')
        self.assertEqual(set(calls),{'sports-journalist','match-analyst','coach'})
        self.assertEqual(result['stats']['model_calls'],3)

    def test_default_team_is_three_calls_and_specialist_can_be_requested(self):
        from prono.team import selected_roles
        self.assertEqual(set(selected_roles(self.ws, 'Prépare mes pronos, absents et cotes', 'adaptive')),
                         {'sports-journalist', 'match-analyst'})
        self.assertEqual(set(selected_roles(self.ws, 'Demande à l’expert bookmaker de vérifier les cotes', 'adaptive')),
                         {'sports-journalist', 'match-analyst', 'bookmaker-expert'})
        calls = []
        def adapter(*args, **kwargs):
            calls.append(args[2])
            return {'answer':'Test','model':'test'}
        with patch('prono.team.prepare_context', return_value=copy.deepcopy(self.context)), patch('prono.team.models', return_value=['test-local']), patch('prono.team.call_model', side_effect=adapter):
            result = run_team(self.ws, 'Analyse les matchs choisis', 'local', 'test-local')
        self.assertEqual(result['stats']['model_calls'], 3)
        self.assertEqual(len(calls), 3)

    def test_actual_prepare_button_does_not_request_performance_analyst(self):
        from prono.team import selected_roles
        script=(ROOT/'src/prono/assets/chat.js').read_text()
        handler=script[script.index('document.getElementById("prepare").onclick'):]
        message=json.loads(re.search(r'document\.getElementById\("question"\)\.value\s*=\s*("[^\n]+")\s*;',handler).group(1))
        self.assertIn('journaliste',message)
        self.assertEqual(set(selected_roles(self.ws,message,'adaptive')),{'sports-journalist','match-analyst'})
        self.assertIn('performance-analyst',selected_roles(self.ws,'Analyse mon journal fictif et mon bilan','adaptive'))

    def test_usage_keeps_cache_separate_and_records_each_role(self):
        usage={'input_tokens':10,'output_tokens':5,'cache_read_input_tokens':30,'cache_creation_input_tokens':20}
        def adapter(*args,**kwargs):return {'answer':'Test','model':'test','usage':dict(usage)}
        result=self.execute(adapter,strategy='adaptive')
        stats=result['stats']
        self.assertEqual(stats['model_calls'],3)
        self.assertEqual(stats['input_tokens'],30)
        self.assertEqual(stats['output_tokens'],15)
        self.assertEqual(stats['cache_read_input_tokens'],90)
        self.assertEqual(stats['cache_creation_input_tokens'],60)
        self.assertEqual(stats['usage_calls'],3)
        self.assertTrue(stats['cache_usage_complete'])
        record=read_record(self.ws.path('analyses/team-'+result['run_id']+'.md'))
        self.assertTrue(all(r['usage']==usage for r in record['reviews']))

    def test_recent_sourced_cache_is_explicit_and_force_refresh_ignores_it(self):
        def adapter(*args,**kwargs):return {'answer':'Test https://example.test/source','model':'test','usage':{'input_tokens':10,'output_tokens':5}}
        first=self.execute(adapter);second=self.execute(adapter);third=self.execute(adapter,force_refresh=True)
        self.assertEqual(first['stats']['model_calls'],8)
        self.assertEqual(second['stats']['model_calls'],5);self.assertEqual(second['stats']['reused_reports'],3)
        self.assertEqual(third['stats']['model_calls'],8)
        for row in second['reviews']:
            if row['status']=='cached':self.assertEqual(row['reused_from'],first['run_id']);self.assertTrue(row['completed_at'])
        self.assertEqual(first['stats']['input_tokens'],80)

    def test_cache_expires_and_changed_facts_invalidate_it(self):
        def adapter(*args,**kwargs):return {'answer':'Test https://example.test/source','model':'test'}
        self.execute(adapter);self.context['matches'][0]['domestic_form']={'home':{'last5':{'wins':4}}}
        changed=self.execute(adapter);self.assertEqual(changed['stats']['reused_reports'],0)
        from datetime import timedelta
        from prono.workspace import utcnow
        with patch('prono.team.utcnow',return_value=utcnow()+timedelta(hours=2)):
            expired=self.execute(adapter)
        self.assertEqual(expired['stats']['reused_reports'],0)

    def test_form_clock_does_not_disable_cache_but_results_do(self):
        self.context['matches'][0]['domestic_form']={'home':{'as_of':'2026-10-12T12:00:00Z',
            'last_match_age_days':2.0,'stale':False,'last5':{'wins':3}},'away':{'available':False}}
        def adapter(*args,**kwargs):return {'answer':'Test https://example.test/source','model':'test'}
        self.execute(adapter)
        form=self.context['matches'][0]['domestic_form']['home']
        form.update(as_of='2026-10-12T12:01:00Z',last_match_age_days=2.0007)
        cached=self.execute(adapter);self.assertEqual(cached['stats']['reused_reports'],3)
        form['last5']['wins']=4
        changed=self.execute(adapter);self.assertEqual(changed['stats']['reused_reports'],0)

    def test_xg_clock_preserves_cache_but_changed_xg_invalidates_it(self):
        self.context['matches'][0]['understat_xg']={'home':{'as_of':'2026-10-15T12:00:00Z',
            'available':True,'last5':{'played':5,'xg_for':7.0},'knowledge_dates':['2026-10-15T10:00:00Z']}}
        def adapter(*args,**kwargs):return {'answer':'Test https://example.test/source','model':'test'}
        self.execute(adapter)
        xg=self.context['matches'][0]['understat_xg']['home']
        xg['as_of']='2026-10-15T12:01:00Z'
        cached=self.execute(adapter);self.assertEqual(cached['stats']['reused_reports'],3)
        xg['last5']['xg_for']=6.0
        changed=self.execute(adapter);self.assertEqual(changed['stats']['reused_reports'],0)
