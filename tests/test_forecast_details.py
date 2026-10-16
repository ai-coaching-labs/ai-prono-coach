"""Lectures score/BTTS cohérentes avec la distribution de production inchangée."""
import copy
import math
import unittest
from prono.forecast_details import forecast_details
from prono.model import score_probabilities


class ForecastDetailsTests(unittest.TestCase):
    def model(self, h, a):
        return {'available': True, 'model': 'poisson-baseline-v1',
                'expected_goals': {'home': h, 'away': a},
                'probabilities': score_probabilities(h, a)}

    def test_btts_agrees_with_independent_poisson_formula_and_score_probability(self):
        for h, a in [(0.05, 0.05), (1.6, 0.8), (3.1, 2.2), (8, 8)]:
            with self.subTest(h=h, a=a):
                model = self.model(h, a)
                original = copy.deepcopy(model)
                result = forecast_details(model)
                self.assertEqual(model, original)
                btts = result['both_teams_score']
                self.assertAlmostEqual(btts['yes'], (1-math.exp(-h))*(1-math.exp(-a)), places=12)
                self.assertAlmostEqual(btts['yes']+btts['no'], 1, places=14)
                for score in result['most_likely_scores']:
                    expected = math.exp(-h-a)*h**score['home']*a**score['away']/math.factorial(score['home'])/math.factorial(score['away'])
                    self.assertAlmostEqual(score['probability'], expected, places=12)

    def test_all_modal_ties_are_reported_and_not_rounded_expected_goals(self):
        scores = forecast_details(self.model(1, 1))['most_likely_scores']
        self.assertEqual({(s['home'], s['away']) for s in scores}, {(0,0),(0,1),(1,0),(1,1)})
        scores = forecast_details(self.model(1.9, 0.7))['most_likely_scores']
        self.assertEqual([(s['home'], s['away']) for s in scores], [(1,0)])

    def test_balanced_btts_is_indecisive(self):
        rate = -math.log(1-math.sqrt(0.5))
        self.assertIsNone(forecast_details(self.model(rate,rate))['both_teams_score']['pick'])

    def test_draw_is_a_valid_leading_outcome_with_a_draw_scenario(self):
        model = self.model(0.6, 0.6)
        self.assertEqual(max(model['probabilities'], key=model['probabilities'].get), 'draw')
        scores = forecast_details(model)['scores_by_outcome']['draw']
        self.assertEqual([(s['home'], s['away']) for s in scores], [(0, 0)])

    def test_scenario_matches_each_outcome_and_keeps_absolute_probability(self):
        model = self.model(1.9, 1.4)
        result = forecast_details(model)
        self.assertEqual([(s['home'], s['away']) for s in result['most_likely_scores']], [(1, 1)])
        self.assertEqual(max(model['probabilities'], key=model['probabilities'].get), 'home')
        home_score = result['scores_by_outcome']['home'][0]
        self.assertEqual((home_score['home'], home_score['away']), (2, 1))
        self.assertAlmostEqual(home_score['probability'], math.exp(-3.3)*1.9**2/2*1.4)
        for outcome, scores in result['scores_by_outcome'].items():
            self.assertTrue(scores)
            for score in scores:
                self.assertEqual('home' if score['home'] > score['away'] else 'away' if score['away'] > score['home'] else 'draw', outcome)

    def test_no_details_when_model_missing_unavailable_or_experimental(self):
        for model in [{}, {'available':False}, {'available':True},
                      {**self.model(1,1),'model':'dc-correction-research-v1'}]:
            self.assertIsNone(forecast_details(model))
