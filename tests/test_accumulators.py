import html
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from prono.accumulators import propose, render
from prono.workspace import Workspace, timestamp, write_record

ROOT = Path(__file__).resolve().parents[1]


class AccumulatorsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / 'config').mkdir()
        shutil.copy(ROOT / 'config/workspace.toml', root / 'config/workspace.toml')
        self.ws = Workspace(root)
        self.now = timestamp('2026-10-20T10:00:00Z')
        self.rows = [self.row(i) for i in range(12)]
        self.archive()

    def row(self, i):
        return {'division': 'F1', 'fixture': {
            'event_id': str(i), 'home': f'Home {i}', 'away': f'Away {i}',
            'kickoff': (self.now + timedelta(hours=2)).isoformat(),
            'quoted_at': (self.now - timedelta(minutes=10)).isoformat(),
            'odds': {'home': 2.0, 'draw': 3.5, 'away': 4.0},
            'bookmaker': 'Book', 'source': 'verified'},
            'model': {'available': True, 'probabilities': {'home': .6, 'draw': .2, 'away': .2}},
            'synthetic': False, 'reasons': []}

    def archive(self, run='a' * 32, offset=5, outcome='home', **changes):
        record = {'run_id': run, 'created_at': (self.now - timedelta(minutes=offset + 1)).isoformat(),
                  'status': 'completed', 'blind_protocol': 'all-roles-blind-v8',
                  'facts': {'matches': [dict(division='F1', event_id=r['fixture']['event_id'],
                             match=r['fixture']['home'] + ' / ' + r['fixture']['away'],
                             kickoff=r['fixture']['kickoff']) for r in self.rows]},
                  'reviews': [{'role': 'coach', 'status': 'completed',
                               'completed_at': (self.now - timedelta(minutes=offset)).isoformat()}],
                  'llm_verdicts': [{'event_id': r['fixture']['event_id'], 'outcome': outcome,
                                    'confidence': 'modérée', 'reason': '<source>', 'reserve': 'limite'} for r in self.rows]}
        record.update(changes)
        write_record(self.ws.path(f'analyses/team-{run}.md'), 'team_review', record)

    def propose(self, budget=5, ticket_mode='doubles'):
        with patch('prono.accumulators.selections', return_value={'matches': self.rows, 'issues': []}):
            return propose(self.ws, budget, now=self.now, ticket_mode=ticket_mode)

    def test_fixed_unit_budget_and_no_shared_matches(self):
        r = self.propose(2.5)
        self.assertEqual(len(r['tickets']), 2)
        self.assertEqual(r['unused_budget'], .5)
        legs = [l['event_id'] for t in r['tickets'] for l in t['legs']]
        self.assertEqual(len(set(legs)), 4)
        t = r['tickets'][0]
        self.assertAlmostEqual(t['probability_under_independence'], .36)
        self.assertAlmostEqual(t['expected_net_under_independence'], .44)
        self.assertEqual(t['gross_return_if_win'], 4)
        self.assertEqual(len(self.propose(999)['tickets']), 5)
        self.assertEqual(self.propose(.99)['tickets'], [])
        self.assertFalse(self.ws.path('journal').exists())

    def test_global_exposure_reduces_budget(self):
        with patch('prono.accumulators.summary', return_value={'open_exposure': 4, 'net_pnl': 0}):
            r = self.propose(10)
        self.assertEqual(len(r['tickets']), 1)

    def test_latest_abstention_overrides_earlier_favourable_verdict(self):
        self.archive(run='b' * 32, offset=1, outcome='abstain')
        self.assertEqual(self.propose()['tickets'], [])

    def test_stale_future_and_nonblind_reviews_are_excluded(self):
        for changes in ({'offset': 400}, {'offset': -10}, {'blind_protocol': 'legacy'}):
            with self.subTest(changes=changes):
                self.archive(**changes)
                self.assertEqual(self.propose()['tickets'], [])

    def test_changed_kickoff_and_identity_block_old_review(self):
        for row in self.rows:
            row['fixture']['kickoff'] = (self.now + timedelta(days=1)).isoformat()
        self.assertEqual(self.propose()['tickets'], [])

    def test_stale_odds_synthetic_missing_data_and_no_coach(self):
        for row in self.rows:
            row['reasons'] = ['Cotes périmées.']
        self.assertEqual(self.propose()['tickets'], [])
        for row in self.rows:
            row['reasons'] = []
            row['synthetic'] = True
        self.assertEqual(self.propose()['tickets'], [])
        self.ws.path('analyses/team-' + 'a' * 32 + '.md').unlink()
        self.assertEqual(self.propose()['tickets'], [])

    def test_same_bookmaker_and_disjoint_teams(self):
        self.rows = self.rows[:2]
        self.rows[1]['fixture']['bookmaker'] = 'Other'
        self.assertEqual(self.propose()['tickets'], [])
        self.rows[1]['fixture']['bookmaker'] = 'Book'
        self.rows[1]['fixture']['home'] = self.rows[0]['fixture']['home']
        self.archive()
        self.assertEqual(self.propose()['tickets'], [])

    def test_draw_valid_and_coach_disagreement_not_replaced(self):
        self.archive(outcome='draw')
        self.assertEqual(self.propose()['tickets'], [])  # .2 * 3.5 <= 1
        for r in self.rows:
            r['fixture']['odds']['draw'] = 6
        t = self.propose()['tickets'][0]
        self.assertEqual(t['legs'][0]['outcome'], 'draw')
        self.assertAlmostEqual(t['probability_under_independence'], .04)

    def test_budget_validation_and_escaped_render(self):
        for value in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.propose(value)
        body = render(self.propose(), html.escape)
        self.assertIn('&lt;source&gt;', body)
        self.assertNotIn('<source>', body)
        self.assertIn('non réservé', body)

    def test_hub_integration(self):
        from prono.hub_dashboard import page
        with patch('prono.accumulators.selections', return_value={'matches': [], 'issues': []}):
            body = page(self.ws, {'tab': 'accumulators', 'budget': '2'})
        self.assertIn('Budget fictif maximum', body)
        self.assertIn('Aucun combiné admissible', body)

    def test_auto_prefers_triple_when_odds_and_probability_support_it(self):
        r = self.propose(1, 'auto')
        t = r['tickets'][0]
        self.assertEqual(t['type'], 'triple')
        self.assertEqual(len(t['legs']), 3)
        self.assertAlmostEqual(t['probability_under_independence'], .216)
        self.assertEqual(t['odds'], 8)
        double = self.propose(1, 'doubles')['tickets'][0]
        self.assertGreater(t['expected_log_growth_under_independence'],
                           double['expected_log_growth_under_independence'])
        self.assertIn('Triple fictif', render(r, html.escape))

    def test_auto_can_mix_formats_without_reusing_matches(self):
        self.rows = self.rows[:5]
        r = self.propose(5, 'auto')
        self.assertEqual([t['type'] for t in r['tickets']], ['triple', 'double'])
        ids = [l['event_id'] for t in r['tickets'] for l in t['legs']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(r['proposed_total'], 2)

    def test_auto_prefers_double_over_high_odds_triple_with_more_downside(self):
        self.rows = self.rows[:3]
        self.archive(outcome='draw')
        for row in self.rows:
            row['fixture']['odds']['draw'] = 6
        r = self.propose(1, 'auto')
        self.assertEqual(r['tickets'][0]['type'], 'double')
        self.assertGreater(r['risk_excluded_count'], 0)
        # The triple has positive arithmetic expectation but fails the risk criterion.
        self.assertEqual(self.propose(1, 'triples')['tickets'], [])

    def test_triples_respect_bookmaker_team_and_budget_constraints(self):
        self.rows = self.rows[:3]
        self.assertEqual(len(self.propose(1, 'triples')['tickets']), 1)
        self.assertEqual(self.propose(.99, 'triples')['tickets'], [])
        self.rows[2]['fixture']['bookmaker'] = 'Other'
        self.assertEqual(self.propose(5, 'triples')['tickets'], [])
        self.rows[2]['fixture']['bookmaker'] = 'Book'
        self.rows[2]['fixture']['home'] = self.rows[0]['fixture']['home']
        self.archive()
        self.assertEqual(self.propose(5, 'triples')['tickets'], [])

    def test_triples_never_include_expired_or_abstained_coach_verdict(self):
        self.rows = self.rows[:3]
        self.archive(offset=400)
        self.assertEqual(self.propose(5, 'triples')['tickets'], [])
        self.archive(outcome='abstain')
        self.assertEqual(self.propose(5, 'triples')['tickets'], [])

    def test_odds_affect_auto_ranking_with_same_probabilities(self):
        self.rows = self.rows[:3]
        self.rows[2]['fixture']['odds']['home'] = 1.7
        t = self.propose(1, 'doubles')['tickets'][0]
        self.assertEqual({l['event_id'] for l in t['legs']}, {'0', '1'})
        self.rows[2]['fixture']['odds']['home'] = 3
        t = self.propose(1, 'doubles')['tickets'][0]
        self.assertIn('2', {l['event_id'] for l in t['legs']})

    def test_formats_and_entire_bankroll_are_checked(self):
        with self.assertRaises(ValueError):
            self.propose(5, 'invalid')
        self.ws.config['paper']['starting_balance'] = 1
        self.assertEqual(self.propose(5, 'auto')['tickets'], [])

    def test_hub_preserves_selected_triples_format(self):
        from prono.hub_dashboard import page
        with patch('prono.accumulators.selections', return_value={'matches': self.rows, 'issues': []}), patch('prono.hub_dashboard.utcnow', return_value=self.now):
            body = page(self.ws, {'tab': 'accumulators', 'budget': '1', 'format': 'triples'})
        self.assertIn('value="triples" selected', body)
        self.assertIn('Triple fictif 1', body)

    def test_empty_result_explains_blockers_without_expanding_details(self):
        for row in self.rows:
            row['reasons'] = ['Cotes indicatives : fraîcheur inconnue.']
        self.ws.path('analyses/team-' + 'a' * 32 + '.md').unlink()
        body = render(self.propose(), html.escape, coach_url='/chat?league=F1&period=next3')
        before_details = body.split('<details>')[0]
        self.assertIn('Calcul terminé : aucun combiné admissible.', before_details)
        self.assertIn('Cotes indicatives', before_details)
        self.assertIn('Avis coach archivé indisponible.', before_details)
        self.assertIn('/chat?league=F1&amp;period=next3', before_details)

    def test_initial_page_shows_instructions_instead_of_finished_calculation(self):
        body = render(self.propose(), html.escape, submitted=False)
        self.assertIn('Saisis ton budget fictif', body)
        self.assertNotIn('Calcul terminé', body)

    def test_budget_and_success_have_visible_feedback(self):
        body = render(self.propose(.5), html.escape)
        self.assertIn('Budget utilisable inférieur', body.split('<details>')[0])
        body = render(self.propose(1), html.escape)
        self.assertIn('Calcul terminé : 1 combiné(s) proposé(s).', body)

    def test_european_cups_generate_tickets_with_validation_warning(self):
        for code in ('UCL', 'UEL', 'UECL'):
            with self.subTest(division=code):
                for row in self.rows:
                    row['division'] = code
                facts = [dict(division=code, event_id=r['fixture']['event_id'],
                              match=r['fixture']['home'] + ' / ' + r['fixture']['away'],
                              kickoff=r['fixture']['kickoff']) for r in self.rows]
                self.archive(facts={'matches': facts})
                result = self.propose()
                self.assertTrue(result['tickets'])
                self.assertIn('validation spécifique absente', render(result, html.escape))
