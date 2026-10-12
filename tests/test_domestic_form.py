import csv
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from prono.workspace import Workspace, timestamp, read_record
from prono.leagues import league_workspace
from prono.domestic_form import DomesticForm
from prono.model import predict, load_history
from prono.chat import coach_facts
from prono.team import prepare_context, run_team, selected_roles

ROOT=Path(__file__).resolve().parents[1]
NOW=timestamp('2026-10-12T12:00:00Z')
KICKOFF='2026-10-13T19:00:00Z'


class DomesticFormTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);(root/'config').mkdir()
        shutil.copy(ROOT/'config/workspace.toml',root/'config/workspace.toml')
        self.ws=Workspace(root)

    def row(self,i=0,team='Arsenal',home=True,days=2,goals=(2,1),known=None):
        at=NOW-timedelta(days=days)
        return {'event_id':str(i),'kickoff':at.isoformat(),
                'home':team if home else 'Opponent','away':'Opponent' if home else team,
                'home_goals':goals[0] if home else goals[1],'away_goals':goals[1] if home else goals[0],
                'result_known_at':known or (at+timedelta(hours=3)).isoformat(),'source':'https://example.org/result'}

    def write(self,code,rows):
        child=league_workspace(self.ws,code,create=True);p=child.path('data/history.csv');p.parent.mkdir(exist_ok=True)
        with p.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(self.row()));writer.writeheader();writer.writerows(rows)
        return child

    def form(self,name='Arsenal',kickoff=KICKOFF):
        return DomesticForm(self.ws,NOW.isoformat()).team(name,kickoff)

    def test_form_five_ten_venues_and_provenance(self):
        rows=[self.row(i,home=i%2==0,days=i+2,goals=((2,1) if i<4 else (1,1) if i==4 else (0,1))) for i in range(12)]
        self.write('E0',rows)
        f=self.form();self.assertTrue(f['available'])
        self.assertEqual((f['last5']['wins'],f['last5']['draws'],f['last5']['losses']),(4,1,0))
        self.assertEqual((f['last5']['goals_for'],f['last5']['goals_against'],f['last5']['points']),(9,5,13))
        self.assertEqual(f['last10']['played'],10)
        self.assertEqual(f['last10']['losses'],5)
        self.assertEqual(f['home_last5']['played'],5);self.assertEqual(f['away_last5']['played'],5)
        self.assertEqual(f['matches_newest_first'][0]['event_id'],'0')
        self.assertEqual(f['matches_newest_first'][0]['result_known_at'],rows[0]['result_known_at'])
        self.assertEqual(f['sources'],['https://example.org/result'])

    def test_strict_knowledge_kickoff_and_window_filters(self):
        good=self.row(1)
        self.write('E0',[good,self.row(2,known=NOW.isoformat()),self.row(3,known=(NOW+timedelta(seconds=1)).isoformat()),
                         self.row(4,days=0),self.row(5,days=-1),self.row(6,days=181)])
        self.assertEqual([r['event_id'] for r in self.form()['matches_newest_first']],['1'])
        self.write('E0',[good])
        self.assertFalse(self.form(kickoff=(NOW-timedelta(days=3)).isoformat())['available'])

    def test_alias_inter_and_no_fuzzy_invention(self):
        self.write('I1',[self.row(1,team='Inter')]);f=self.form('Internazionale')
        self.assertTrue(f['available']);self.assertEqual(f['canonical_team'],'inter')
        self.assertFalse(self.form('Inter Miami')['available'])
        self.write('SP1',[self.row(1,team='Ath Madrid')])
        self.assertTrue(self.form('Atlético Madrid')['available'])

    def test_promoted_club_combines_disclosed_divisions(self):
        self.write('E0',[self.row(1,team='Sunderland')]);self.write('E1',[self.row(2,team='Sunderland',days=90)])
        f=self.form('Sunderland');self.assertEqual(f['divisions'],['E0','E1'])
        self.assertEqual(f['last10']['played'],2)

    def test_ambiguous_country_and_missing_club_abstain(self):
        self.write('E0',[self.row(1,team='Example')]);self.write('F1',[self.row(2,team='Example')])
        self.assertIn('ambiguë',self.form('Example')['reason'])
        self.assertFalse(self.form('Unknown')['available'])

    def test_partial_stale_and_synthetic_are_visible(self):
        row=self.row(1,days=30);row['source']='synthetic-demo';self.write('E0',[row])
        f=self.form();self.assertTrue(f['stale']);self.assertTrue(f['synthetic'])
        self.assertEqual(len(f['warnings']),3);self.assertEqual(f['last5']['played'],1)

    def test_duplicate_results_deduplicate_and_conflicts_block(self):
        r=self.row(1);self.write('E0',[r]);self.write('E1',[dict(r,event_id='other')])
        self.assertEqual(self.form()['last10']['played'],1)
        self.write('E1',[dict(r,event_id='other',home_goals=5)])
        self.assertIn('contradictoires',self.form()['reason'])

    def test_unreadable_league_reported_without_losing_other_sources(self):
        self.write('E0',[self.row(1)]);child=self.write('F1',[]);child.path('data/history.csv').write_text('broken\n')
        index=DomesticForm(self.ws,NOW.isoformat());self.assertTrue(index.team('Arsenal',KICKOFF)['available'])
        self.assertTrue(any(e['division']=='F1' for e in index.errors))

    def test_real_context_model_unchanged_and_mocked_agents_receive_form(self):
        self.write('E0',[self.row(i,days=i+2) for i in range(10)])
        self.write('F1',[self.row(i,team='Lille',days=i+2) for i in range(10)])
        euro=self.write('UCL',[dict(self.row(i,days=i+3),away='Lille') for i in range(12)])
        self.ws.path('data/europe-watch.json').write_text(json.dumps({'matches':[{'division':'UCL','event_id':'test-europe',
            'home':'Arsenal','away':'Lille','kickoff':KICKOFF,'source':'https://example.org/fixture','quoted_at':None,'offers':[]}]}))
        with patch('prono.pronos.utcnow',return_value=NOW),patch('prono.chat.utcnow',return_value=NOW):
            context=prepare_context(self.ws,'UCL','next3','test-europe')
            # Production uses normalized club names, with the same European-only sample.
            history=[{**r,'home':r['home'].casefold(),'away':r['away'].casefold()} for r in load_history(euro.path('data/history.csv'))]
            model=predict(history,'arsenal','lille',NOW,euro.config['model'])
            self.assertEqual(context['matches'][0]['probabilities'],model['probabilities'])
            self.assertEqual(context['matches'][0]['domestic_form']['home']['last10']['played'],10)
            seen=[]
            def adapter(ws,message,system,*args,**kw):
                seen.append(system);self.assertIn('domestic_form',system)
                if 'MISSION DU RÔLE sports-journalist' in system:self.assertIn('trois dernières prestations',system)
                return {'answer':'SIMULÉ : contexte transmis, aucune source lue.','model':'test'}
            with patch('prono.team.claude_path',return_value='/test/claude'),patch('prono.team.call_model',side_effect=adapter):
                result=run_team(self.ws,'Analyse la forme et le contenu des prestations','claude','',league='UCL',period='next3',event_id='test-europe',strategy='adaptive')
            record=read_record(self.ws.path('analyses/team-'+result['run_id']+'.md'))
            self.assertEqual(record['facts']['matches'][0]['domestic_form'],context['matches'][0]['domestic_form'])
            self.assertTrue(seen)
        self.assertIn('sports-journalist',selected_roles(self.ws,'Analyse la forme','adaptive'))
