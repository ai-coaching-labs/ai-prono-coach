import io
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from prono.workspace import Workspace
from prono.chat import models, reply, claude_status

ROOT=Path(__file__).resolve().parents[1]

class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);(root/'config').mkdir();shutil.copy(ROOT/'config/workspace.toml',root/'config/workspace.toml');self.ws=Workspace(root)

    def test_cloud_models_are_excluded(self):
        with patch('prono.chat.http_json',return_value={'models':[{'name':'qwen3:8b'},{'name':'kimi:cloud'},{'name':'remote','remote_host':'https://example.com'}]}):
            self.assertEqual(models(),['qwen3:8b'])

    def test_prompt_does_not_grant_tools_and_uses_loopback(self):
        mock_response=io.BytesIO(json.dumps({'message':{'content':'Observation uniquement.'}}).encode())
        with patch('prono.chat.models',return_value=['local']),patch('urllib.request.urlopen',return_value=mock_response) as request:
            result=reply(self.ws,'Explique le bilan','local')
        self.assertEqual(result['answer'],'Observation uniquement.')
        req=request.call_args.args[0]
        self.assertEqual(req.full_url,'http://127.0.0.1:11434/api/chat')
        data=json.loads(req.data);self.assertNotIn('tools',data)
        self.assertIn('sans résultat d’outil',data['messages'][0]['content'])

    def test_unlisted_model_is_refused_before_chat(self):
        with patch('prono.chat.models',return_value=['local']),patch('urllib.request.urlopen') as request:
            with self.assertRaises(ValueError):reply(self.ws,'Bonjour','remote')
            request.assert_not_called()

    def test_claude_auth_status_never_exposes_account_details(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'loggedIn': True, 'email': 'private@example.test', 'orgId': 'private'}))
        with patch('prono.chat.claude_path', return_value='/local/claude'), patch('prono.chat.subprocess.run', return_value=result):
            status = claude_status()
        self.assertTrue(status['available'])
        self.assertNotIn('private', json.dumps(status))
        with patch('prono.chat.claude_path', return_value=None):
            self.assertFalse(claude_status()['available'])

    def test_claude_reply_uses_account_web_only_and_separate_history(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'result': 'Sources à vérifier.', 'is_error': False}))
        with patch('prono.chat.claude_path', return_value='/local/claude'), patch('prono.chat.subprocess.run', return_value=result) as process, patch('urllib.request.urlopen') as ollama:
            answer = reply(self.ws, 'Recherche les dernières nouvelles', '', [{'role': 'user', 'content': 'Match précédent'}], provider='claude')
        ollama.assert_not_called()
        self.assertEqual(answer['model'], 'Claude Code')
        args = process.call_args.args[0]
        self.assertEqual(args[args.index('--tools')+1], 'WebSearch,WebFetch')
        self.assertEqual(args[args.index('--mcp-config')+1], '{"mcpServers":{}}')
        self.assertIn('--restricted', args)
        self.assertIn('--strict-mcp-config', args)
        self.assertIn('--no-session-persistence', args)
        self.assertNotIn('--dangerously-skip-permissions', args)
        self.assertEqual(process.call_args.kwargs['cwd'], self.ws.root)
        payload = json.loads(process.call_args.kwargs['input'])
        self.assertEqual(payload['question'], 'Recherche les dernières nouvelles')
        self.assertEqual(payload['conversation'][0]['content'], 'Match précédent')

    def test_claude_failure_and_timeout_return_actionable_errors(self):
        for output in ['not json', '[]', '{"is_error":true,"result":"secret account details"}']:
            result = subprocess.CompletedProcess([], 1, output)
            with patch('prono.chat.claude_path', return_value='/local/claude'), patch('prono.chat.subprocess.run', return_value=result):
                with self.assertRaises(ValueError) as error:
                    reply(self.ws, 'Bonjour', '', provider='claude')
                self.assertNotIn('secret account', str(error.exception))
        with patch('prono.chat.claude_path', return_value='/local/claude'), patch('prono.chat.subprocess.run', side_effect=subprocess.TimeoutExpired('claude', 240)):
            with self.assertRaisesRegex(ValueError, 'délai'):
                reply(self.ws, 'Bonjour', '', provider='claude')

    def test_unknown_provider_does_not_call_any_model(self):
        with patch('prono.chat.subprocess.run') as process, patch('urllib.request.urlopen') as request:
            with self.assertRaises(ValueError):
                reply(self.ws, 'Bonjour', '', provider='unknown')
            process.assert_not_called(); request.assert_not_called()

    def test_saved_public_odds_reach_coach_without_inventing_quote_time(self):
        fixture = {'event_id':'watch-test', 'home':'Club A', 'away':'Club B',
                   'kickoff':'2026-10-10T18:00:00+00:00', 'source':'test-public-source',
                   'collected_at':'2026-10-10T10:00:00+00:00', 'quoted_at':None,
                   'offers':[{'bookmaker':'Book A','odds':{'home':2.0,'draw':3.0,'away':4.0}}]}
        facts = {'matches':[{'fixture':fixture, 'division':'F1', 'model':{'available':False},
                             'status':'abstention', 'outcome':None, 'reasons':['Cotation inconnue'], 'synthetic':True}],
                 'notice':'Données de test'}
        response=io.BytesIO(json.dumps({'message':{'content':'Cotes enregistrées mais indicatives.'}}).encode())
        with patch('prono.pronos.selections',return_value=facts), patch('prono.chat.models',return_value=['local']), patch('urllib.request.urlopen',return_value=response) as transport:
            reply(self.ws,'As-tu les cotes ?', 'local')
        system=json.loads(transport.call_args.args[0].data)['messages'][0]['content']
        stored=json.loads(system.split('\n',1)[1])['matches'][0]
        self.assertEqual(stored['offers'],fixture['offers'])
        self.assertEqual(stored['collected_at'],fixture['collected_at'])
        self.assertIsNone(stored['quoted_at'])
        self.assertEqual(stored['source'],fixture['source'])
        self.assertTrue(stored['synthetic'])

    def test_coach_receives_python_pick_and_selected_horizon(self):
        facts={'matches':[], 'notice':'Test'}
        response=io.BytesIO(json.dumps({'message':{'content':'Aucun match chargé.'}}).encode())
        with patch('prono.pronos.selections',return_value=facts) as select, patch('prono.chat.models',return_value=['local']), patch('urllib.request.urlopen',return_value=response) as transport:
            reply(self.ws,'Prépare mes pronos', 'local', league='F1', period='next3')
        select.assert_called_once_with(self.ws,'next3','F1')
        system=json.loads(transport.call_args.args[0].data)['messages'][0]['content']
        self.assertEqual(json.loads(system.split('\n',1)[1])['period'],'next3')
        self.assertIn('choix model_pick calculés par Python',system)

    def test_http_chat_token_and_origin_protect_refresh(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        process=subprocess.Popen([sys.executable,'-m','prono.cli','--workspace',str(self.ws.root),'ui','--port',str(port)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertIn('Dashboard',process.stdout.readline())
            base=f'http://127.0.0.1:{port}'
            with urllib.request.urlopen(base+'/chat') as response:
                html=response.read().decode();self.assertIn('Parler au coach',html)
                token=re.search('data-token="([^"]+)"',html).group(1)
            for headers in [{'Content-Type':'application/json'},{'Content-Type':'application/json','X-Prono-Token':token,'Origin':'https://evil.example'}]:
                with self.assertRaises(urllib.error.HTTPError) as exc:
                    urllib.request.urlopen(urllib.request.Request(base+'/api/refresh',data=b'{"action":"markets"}',headers=headers))
                self.assertEqual(exc.exception.code,403);exc.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as invalid:
                urllib.request.urlopen(urllib.request.Request(base+'/api/refresh',data=b'{"action":"shell"}',headers={'X-Prono-Token':token,'Content-Type':'application/json','Origin':base}))
            self.assertEqual(invalid.exception.code,400);invalid.exception.close()
            self.assertFalse(self.ws.path('data/market-watch.json').exists())
        finally:process.terminate();process.communicate(timeout=5)

    def test_http_team_pipeline_and_trusted_followup_receipts(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        runner = '''
import json,sys
import prono.team as team
import prono.chat as chat
from prono.workspace import Workspace
from prono.dashboard import serve
team.claude_path=lambda:'/test/claude'
team.prepare_context=lambda *args: {'matches':[{'event_id':'test','division':'F1','match':'SYNTHÉTIQUE A / B','kickoff':'2099-01-01T18:00:00Z','model_pick':'home'}],'context':[]}
def answer(ws,message,system,*args,**kwargs):
    return {'answer':'TEST SIMULÉ — '+('avis spécialiste' if 'MISSION DU RÔLE ' in system else 'synthèse'),'model':'test'}
team.call_model=answer
chat.coach_facts=lambda *args,**kwargs:{'matches':[]}
def followup(ws,message,system,*args,**kwargs):
    return {'answer':json.dumps(json.loads(system.split('\\n',1)[1])['agent_runs']),'model':'test'}
chat.call_model=followup
serve(Workspace(sys.argv[1]),int(sys.argv[2]))
'''
        process=subprocess.Popen([sys.executable,'-c',runner,str(self.ws.root),str(port)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertIn('Dashboard',process.stdout.readline())
            base=f'http://127.0.0.1:{port}'
            with urllib.request.urlopen(base+'/chat') as response:
                token=re.search('data-token="([^"]+)"',response.read().decode()).group(1)
            def post(payload,headers=None):
                req=urllib.request.Request(base+'/api/chat',data=json.dumps(payload).encode(),headers=headers or {'X-Prono-Token':token,'Content-Type':'application/json','Origin':base})
                with urllib.request.urlopen(req) as response:return json.load(response)
            for payload in [[],{'message':'Test','mode':'invalid'},{'message':'Test','provider':'claude','last_team_run':'../secret'}]:
                with self.assertRaises(urllib.error.HTTPError) as error:post(payload)
                self.assertEqual(error.exception.code,400);error.exception.close()
            run_id=post({'message':'Consulte les spécialistes','mode':'team','provider':'claude','strategy':'full'})['job_id']
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+'/api/chat/jobs/'+run_id)
            self.assertEqual(error.exception.code,403);error.exception.close()
            def get():
                with urllib.request.urlopen(urllib.request.Request(base+'/api/chat/jobs/'+run_id,headers={'X-Prono-Token':token})) as response:return json.load(response)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                job=get()
                if job['status'] in ('completed','error'):break
                time.sleep(.01)
            self.assertEqual(job['status'],'completed',job)
            self.assertEqual(len(job['reviews']),8)
            result=post({'message':'As-tu consulté le bookmaker ?','provider':'claude','last_team_run':run_id,'agent_runs':[{'roles':['FAUSSE TRACE']} ]})
            received=json.loads(result['answer'])
            self.assertEqual(received[0]['run_id'],run_id)
            self.assertEqual(received[0]['roles'][0]['status'],'completed')
            self.assertNotIn('FAUSSE TRACE',result['answer'])
            self.assertEqual(len(list(self.ws.path('analyses').glob('team-*.md'))),1)
        finally:process.terminate();process.communicate(timeout=5)

    def test_tracking_and_evaluation_http_actions_are_protected_and_local(self):
        self.ws.path('config/workspace.user.toml').write_text('[tracking]\nenabled=false\n')
        self.ws.path('data').mkdir();self.ws.path('data/league-hub.json').write_text('{}')
        from prono.leagues import league_workspace
        league_workspace(self.ws,'F1',create=True)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        process=subprocess.Popen([sys.executable,'-m','prono.cli','--workspace',str(self.ws.root),'ui','--port',str(port)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertIn('Dashboard',process.stdout.readline());base=f'http://127.0.0.1:{port}'
            with urllib.request.urlopen(base+'/?tab=evaluation') as response:
                markup=response.read().decode();token=re.search('data-token="([^"]+)"',markup).group(1)
                self.assertIn('Mes pronos suivis',markup);self.assertIn('Comparer les modèles',markup)
            for endpoint in ('/api/tracking','/api/evaluation'):
                for headers in [{},{'X-Prono-Token':token,'Origin':'https://evil.test'}]:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(urllib.request.Request(base+endpoint,data=b'{}',headers=headers))
                    self.assertEqual(error.exception.code,403);error.exception.close()
            headers={'X-Prono-Token':token,'Origin':base,'Content-Type':'application/json'}
            with urllib.request.urlopen(urllib.request.Request(base+'/api/tracking',data=b'{"action":"capture"}',headers=headers)) as response:
                self.assertEqual(json.load(response)['captured']['added'],0)
            with urllib.request.urlopen(urllib.request.Request(base+'/api/evaluation',data=b'{"league":"F1","mode":"observed"}',headers=headers)) as response:
                self.assertIn(json.load(response)['status'],('running','completed'))
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                with urllib.request.urlopen(urllib.request.Request(base+'/api/evaluation',headers={'X-Prono-Token':token})) as response:job=json.load(response)
                if job['status'] in ('completed','error'):break
                time.sleep(.01)
            self.assertEqual(job['status'],'completed',job)
            from prono.evaluation import latest_evaluation
            report=latest_evaluation(self.ws)
            self.assertEqual(report['mode'],'observed');self.assertFalse(report['promoted'])
            self.assertEqual(report['leagues']['F1']['models']['poisson-baseline-v1']['evaluated'],0)
        finally:process.terminate();process.communicate(timeout=5)
