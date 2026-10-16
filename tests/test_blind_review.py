"""Every role is blind to Poisson outputs; the final comparison is added after its reply."""
import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from prono.blind_review import blind_context, render_verdict


class BlindReviewTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
        self.context = {'as_of': self.now.isoformat(), 'matches': [{
            'event_id':'fixture', 'match':'A / B', 'kickoff':'2099-01-01T18:00:00Z',
            'division':'F1', 'model_pick':'home', 'probabilities':{'home':.5,'draw':.3,'away':.2},
            'expected_goals':{'home':1.8,'away':.9},
            'forecast_details':{'both_teams_score':{'pick':'no','yes':.4,'no':.6}},
            'comparison':{'expected_value':.2}, 'status':'MODEL_LEAK', 'reasons':['MODEL_REASON'],
            'domestic_form':{'home':{'last5':{'wins':3},'forecast':{'model_pick':'home'}}},
            'understat_xg':{'home':{'last5':{'xg_for_per_match':1.4},'collected_at':'2026-10-14T12:00:00Z'}},
            'offers':[{'bookmaker':'Example','odds':{'home':2.3,'draw':3,'away':4}}]}],
            'selection':{'rows':[{'pick_probability':.5,'gap':.2}]},
            'model_evaluation':{'probabilities':{'home':.5}}, 'unknown_future_field':'MODEL_LEAK'}
        self.verdict = {'event_id':'fixture','outcome':'away','score':[0,1],'confidence':'faible',
                        'reason':'Absences vérifiées [club](https://example.test).','reserve':'Petit échantillon.'}

    def render(self, verdict=None, context=None):
        return render_verdict(json.dumps({'verdicts':[verdict or self.verdict]}), context or self.context, self.now)

    def test_projection_preserves_observed_facts_and_sources_and_is_invariant_to_predictions(self):
        before = copy.deepcopy(self.context)
        blind = blind_context(self.context)
        text = json.dumps(blind)
        for key in ('model_pick','probabilities','expected_goals','forecast_details','comparison','selection','model_evaluation','MODEL_LEAK','MODEL_REASON'):
            self.assertNotIn(key, text)
        row = blind['matches'][0]
        self.assertEqual(row['domestic_form']['home']['last5']['wins'],3)
        self.assertEqual(row['understat_xg'],self.context['matches'][0]['understat_xg'])
        self.assertEqual(row['offers'],self.context['matches'][0]['offers'])
        changed = copy.deepcopy(self.context)
        changed['matches'][0].update(model_pick='away',probabilities={'home':.01,'draw':.02,'away':.97})
        self.assertEqual(blind_context(changed),blind)
        self.assertEqual(self.context,before)

    def test_comparison_is_deterministic_and_does_not_modify_the_llm_choice_or_python(self):
        before = copy.deepcopy(self.context)
        answer, verdicts, errors = self.render()
        self.assertEqual(errors,[])
        self.assertIn('1 (50.0 %)',answer)
        self.assertIn('2 · Extérieur · désaccord avec Python',answer)
        self.assertIn('0-1',answer)
        self.assertIn('Non (60.0 %)',answer)
        self.assertEqual(verdicts[0]['outcome'],'away')
        self.assertEqual(verdicts[0]['comparison'],'disagreement')
        self.assertEqual(self.context,before)
        agreed={**self.verdict,'outcome':'home','score':[1,0]}
        self.assertEqual(self.render(agreed)[1][0]['comparison'],'agreement')

    def test_no_python_still_allows_independent_choice_and_draw_score(self):
        context=copy.deepcopy(self.context)
        context['matches'][0].update(model_pick=None,probabilities=None,forecast_details=None)
        answer,verdicts,errors=self.render({**self.verdict,'outcome':'draw','score':[1,1]},context)
        self.assertEqual(errors,[])
        self.assertIn('N · Nul',answer)
        self.assertIn('1-1',answer)
        self.assertEqual(verdicts[0]['confidence'],'faible')
        self.assertEqual(verdicts[0]['comparison'],'unavailable')

    def test_invalid_score_confidence_or_json_does_not_trigger_repair_calls_or_invent_values(self):
        answer,verdicts,errors=self.render({**self.verdict,'score':[1,1],'confidence':'98 %'})
        self.assertTrue(errors)
        self.assertIsNone(verdicts[0]['score'])
        self.assertIsNone(verdicts[0]['confidence'])
        self.assertNotIn('98 %',answer)
        with patch('prono.team.call_model',side_effect=AssertionError('No repair call')):
            answer,verdicts,errors=render_verdict('invalid JSON',self.context,self.now)
        self.assertTrue(errors)
        self.assertIsNone(verdicts[0]['outcome'])
        self.assertIn('Verdict non exploitable',answer)

    def test_expired_and_abstained_matches_have_no_active_score_or_confidence(self):
        context=copy.deepcopy(self.context)
        context['matches'][0]['kickoff']='2026-10-15T11:00:00Z'
        answer,verdicts,_=self.render(context=context)
        self.assertEqual(verdicts[0]['outcome'],'abstain')
        self.assertIsNone(verdicts[0]['score'])
        self.assertIsNone(verdicts[0]['confidence'])
        self.assertIn('déjà commencé',answer)
        self.assertEqual(self.render({**self.verdict,'outcome':'abstain'})[1][0]['comparison'],'abstention')

    def test_failed_essential_specialist_prevents_high_confidence(self):
        context=copy.deepcopy(self.context)
        context['agent_reviews']=[{'role':'sports-journalist','status':'error'}]
        _,verdicts,errors=self.render({**self.verdict,'confidence':'élevée'},context)
        self.assertIsNone(verdicts[0]['confidence'])
        self.assertTrue(errors)
