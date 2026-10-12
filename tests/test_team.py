import copy
import json
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from prono.chat import coach_facts, claude_reply
from prono.team import ROLES, TeamJobs, explicit_team_request, prepare_context, receipts, run_team
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
        self.assertIn('Avis bookmaker-expert',calls[-1][1])
        record = read_record(self.ws.path('analyses/team-'+result['run_id']+'.md'))
        self.assertEqual(record['facts']['matches'][0]['probabilities'],self.context['matches'][0]['probabilities'])
        self.assertIsNone(record['facts']['matches'][0]['quoted_at'])
        self.assertEqual(len(receipts(self.ws,result['run_id'])[0]['roles']),8)
        restored = TeamJobs(self.ws).get(result['run_id'])
        self.assertEqual(restored['result']['answer'],result['answer'])

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
            fixture={'event_id':str(i),'home':'A','away':'B','kickoff':'2026-10-10T18:00:00Z','source':'test'}
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
        self.assertEqual(set(calls),{'bookmaker-expert','sports-journalist','lineup-analyst','match-analyst','coach'})
        self.assertEqual(result['stats']['model_calls'],5)

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
        self.execute(adapter);self.context['matches'][0]['probabilities']={'home':.4,'draw':.3,'away':.3}
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
