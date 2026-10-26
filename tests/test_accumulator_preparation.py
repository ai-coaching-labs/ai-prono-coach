from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch

import unittest
import test_accumulators as cases
from prono.accumulator_preparation import preparation, save_quote, start_preparation
from prono.accumulators import propose
from prono.leagues import league_workspace
from prono.workspace import read_record


class PreparationTests(unittest.TestCase):
    row = cases.AccumulatorsTests.row
    archive = cases.AccumulatorsTests.archive
    def setUp(self):
        cases.AccumulatorsTests.setUp(self)
        self.rows = self.rows[:3]
        self.child = league_workspace(self.ws, 'F1', create=True)

    def plan(self, mode='indicative'):
        with patch('prono.accumulator_preparation.selections', return_value={'matches':self.rows, 'issues':[]}), patch('prono.accumulators.selections', return_value={'matches':self.rows, 'issues':[]}):
            return preparation(self.ws, now=self.now, quote_mode=mode)

    def indicative_rows(self):
        for r in self.rows:
            f = r['fixture']
            f['offers'] = [{'bookmaker':f.pop('bookmaker'), 'odds':f.pop('odds')}]
            f['quoted_at'] = None
            f['collected_at'] = (self.now - timedelta(hours=2)).isoformat()
            r['reasons'] = ['Cotes indicatives : simulation fictive non validée, fraîcheur inconnue.']

    def test_indicative_prices_are_usable_without_inventing_quote_time(self):
        self.indicative_rows()
        original = deepcopy(self.rows)
        p = self.plan()
        self.assertEqual(p['quote_ready_count'], 3)
        self.assertTrue(p['simulation_ready'])
        self.assertEqual(self.plan('verified')['quote_ready_count'], 0)
        with patch('prono.accumulators.selections', return_value={'matches':self.rows, 'issues':[]}):
            r = propose(self.ws, 1, now=self.now, allow_indicative=True)
        self.assertIsNone(r['tickets'][0]['legs'][0]['quoted_at'])
        self.assertTrue(r['tickets'][0]['legs'][0]['indicative'])
        self.assertIn('retours estimés', r['notice'])
        self.assertEqual(self.rows, original)

    def test_no_offers_or_synthetic_never_become_candidates(self):
        self.indicative_rows()
        for r in self.rows:
            r['fixture']['offers'] = []
        self.assertEqual(self.plan()['quote_ready_count'], 0)
        for r in self.rows:
            r['synthetic'] = True
        self.assertEqual(self.plan()['matches'], [])

    def test_no_budget_until_coach_review_and_valid_ticket(self):
        self.ws.path('analyses/team-' + 'a'*32 + '.md').unlink()
        self.assertFalse(self.plan()['simulation_ready'])
        self.assertEqual(self.plan()['coach_current_count'], 0)
        self.archive(outcome='abstain')
        self.assertFalse(self.plan()['simulation_ready'])
        self.assertEqual(self.plan()['coach_current_count'], 3)

    def test_user_quotes_keep_old_capture_and_knowledge_dates(self):
        f=self.rows[0]['fixture']
        body={'division':'F1', 'event_id':f['event_id'], 'kickoff':f['kickoff'],
              'bookmaker':'Book', 'source_url':'https://example.org/match',
              'quoted_at':f['quoted_at'], 'odds':f['odds']}
        with patch('prono.accumulator_preparation.selections', return_value={'matches':self.rows, 'issues':[]}):
            save_quote(self.ws, body, self.now)
            save_quote(self.ws, {**body, 'odds':{**f['odds'], 'home':2.2}}, self.now)
        captures=[read_record(p) for p in self.child.path('analyses').glob('odds-*.md')]
        self.assertEqual(len(captures), 2)
        changed=next(r for r in captures if r['previous_fixtures'])
        self.assertEqual(changed['previous_fixtures'][0]['odds']['home'], 2)
        self.assertEqual(changed['fixture']['quoted_at'], f['quoted_at'])
        self.assertEqual(changed['fixture']['collected_at'], self.now.isoformat())

    def test_future_stale_or_rescheduled_quotes_rejected(self):
        f=self.rows[0]['fixture']
        body={'division':'F1', 'event_id':f['event_id'], 'kickoff':f['kickoff'],
              'bookmaker':'Book', 'source_url':'https://example.org/match',
              'quoted_at':f['quoted_at'], 'odds':f['odds']}
        for changes in ({'quoted_at':(self.now+timedelta(minutes=1)).isoformat()},
                        {'quoted_at':(self.now-timedelta(days=1)).isoformat()},
                        {'kickoff':(self.now+timedelta(days=1)).isoformat()}):
            with self.subTest(changes=changes), patch('prono.accumulator_preparation.selections', return_value={'matches':self.rows, 'issues':[]}):
                with self.assertRaises(ValueError):
                    save_quote(self.ws, {**body, **changes}, self.now)
        self.assertFalse(list(self.child.path('analyses').glob('odds-*.md')))

    def test_explicit_preparation_starts_existing_blind_team_and_keeps_scope(self):
        self.indicative_rows()
        plan=self.plan()
        jobs=Mock()
        jobs.start.return_value='b'*32
        with patch('prono.accumulator_preparation.preparation', return_value=plan), patch('prono.chat.claude_status', return_value={'available':True}):
            r=start_preparation(self.ws, {'event_ids':['0','1','2'], 'period':'next3', 'quote_mode':'indicative'}, jobs)
        self.assertEqual(r['job_id'], 'b'*32)
        sent=jobs.start.call_args.args[0]
        self.assertEqual(sent['provider'], 'claude')
        self.assertEqual(sent['event_ids'], ['0','1','2'])
        self.assertEqual(sent['period'], 'next3')
        self.assertTrue(sent['force_refresh'])
        self.assertNotIn('probabilities', sent)
        from prono.team import selected_roles
        self.assertEqual(set(selected_roles(self.ws, sent['message'], 'adaptive')), {'sports-journalist', 'match-analyst'})

    def test_unavailable_claude_and_missing_prices_dont_start_job(self):
        plan=self.plan('verified')
        jobs=Mock()
        with patch('prono.accumulator_preparation.preparation', return_value=plan), patch('prono.chat.claude_status', return_value={'available':False, 'message':'Connexion Claude requise'}):
            with self.assertRaisesRegex(ValueError, 'Connexion Claude'):
                start_preparation(self.ws, {'event_ids':['0','1']}, jobs)
        plan['matches'][0]['quote_ready']=False
        with patch('prono.accumulator_preparation.preparation', return_value=plan):
            with self.assertRaises(ValueError):
                start_preparation(self.ws, {'event_ids':['0','1']}, jobs)
        jobs.start.assert_not_called()

    def test_generation_uses_only_selected_matches(self):
        self.indicative_rows()
        with patch('prono.accumulators.selections', return_value={'matches':self.rows, 'issues':[]}):
            r=propose(self.ws, 5, now=self.now, allow_indicative=True, event_ids=['0','2'])
        self.assertEqual({l['event_id'] for t in r['tickets'] for l in t['legs']}, {'0','2'})
        self.assertEqual(r['tickets'][0]['type'], 'double')

    def test_preparation_excludes_started_matches_and_never_starts_external_work(self):
        self.rows[0]['fixture']['kickoff']=self.now.isoformat()
        with patch('prono.chat.claude_status') as claude, patch('prono.team.TeamJobs.start') as start:
            p=self.plan()
        self.assertEqual(len(p['matches']), 2)
        claude.assert_not_called()
        start.assert_not_called()

    def test_automatic_selection_ranks_odds_and_never_reuses_teams(self):
        self.rows[0]['fixture']['odds']['home']=1.7
        self.rows[2]['fixture']['odds']['home']=3
        p=self.plan()
        self.assertEqual(p['automatic_event_ids'][0], '2')
        self.rows[0]['fixture']['home']=self.rows[1]['fixture']['home']
        p=self.plan()
        self.assertEqual(len(p['automatic_event_ids']), 2)
        self.assertFalse({'0','1'}.issubset(p['automatic_event_ids']))

    def test_automatic_selection_requires_same_bookmaker_and_prices(self):
        self.rows[2]['fixture']['bookmaker']='Other'
        self.assertEqual(set(self.plan()['automatic_event_ids']), {'0','1'})
        self.rows[1]['fixture']['bookmaker']='Third'
        self.assertEqual(self.plan()['automatic_event_ids'], [])

    def test_automatic_start_uses_server_selection_without_manual_ids(self):
        p=self.plan()
        jobs=Mock()
        jobs.start.return_value='b'*32
        with patch('prono.accumulator_preparation.preparation', return_value=p), patch('prono.chat.claude_status', return_value={'available':True}):
            r=start_preparation(self.ws, {'selection_mode':'auto', 'event_ids':['not-selected']}, jobs)
        self.assertEqual(r['event_ids'], p['automatic_event_ids'])
        self.assertEqual(jobs.start.call_args.args[0]['event_ids'], p['automatic_event_ids'])

    def test_exploration_shows_weak_negative_scenarios_without_changing_coach(self):
        for row in self.rows:
            row['fixture']['odds']['home']=1.2
        verdicts=[{'event_id':str(i), 'outcome':'home', 'confidence':'faible',
                   'reason':'Hypothèse fragile', 'reserve':'Absences incertaines'} for i in range(3)]
        self.archive(llm_verdicts=verdicts)
        with patch('prono.accumulators.selections', return_value={'matches':self.rows,'issues':[]}):
            exploratory=propose(self.ws,5,now=self.now,allow_indicative=True)
            strict=propose(self.ws,5,now=self.now)
        self.assertTrue(exploratory['tickets'])
        self.assertFalse(strict['tickets'])
        t=exploratory['tickets'][0]
        self.assertLess(t['expected_net_under_independence'],0)
        self.assertTrue(any('projection défavorable' in s for s in t['warnings']))
        self.assertTrue(all(l['confidence']=='faible' and l['outcome']=='home' for l in t['legs']))
        import html
        from prono.accumulators import render
        rendered=render(exploratory,html.escape)
        self.assertIn('Scénario comparatif exploratoire',rendered)
        self.assertIn('projection défavorable',rendered)
        self.assertFalse(self.ws.path('journal').exists())

    def test_exploration_never_turns_abstention_or_missing_confidence_into_pick(self):
        for confidence,outcome in ((None,'home'),('faible','abstain')):
            with self.subTest(confidence=confidence,outcome=outcome):
                self.archive(llm_verdicts=[{'event_id':str(i),'outcome':outcome,'confidence':confidence} for i in range(3)])
                with patch('prono.accumulators.selections',return_value={'matches':self.rows,'issues':[]}):
                    r=propose(self.ws,5,now=self.now,allow_indicative=True)
                self.assertEqual(r['tickets'],[])

    def test_european_cups_remain_in_preparation_with_visible_notice(self):
        import html
        from zoneinfo import ZoneInfo
        from prono.accumulator_preparation import render_preparation
        for row, code in zip(self.rows, ('UCL', 'UEL', 'UECL')):
            row['division'] = code
        p = self.plan()
        self.assertEqual(len(p['matches']), 3)
        self.assertEqual(p['excluded'], [])
        body = render_preparation(p, lambda value: html.escape(str(value)), ZoneInfo('Europe/Paris'), '')
        self.assertIn('modèle exploratoire', body)
        self.assertNotIn('validation spécifique du modèle absente', body)

    def test_fifteen_matches_can_be_selected_and_sent_to_team(self):
        self.rows = [self.row(i) for i in range(18)]
        p = self.plan()
        self.assertEqual(len(p['automatic_event_ids']), 15)
        jobs = Mock()
        with patch('prono.accumulator_preparation.preparation', return_value=p), patch('prono.chat.claude_status', return_value={'available':True}):
            start_preparation(self.ws, {'selection_mode':'auto'}, jobs)
        sent = jobs.start.call_args.args[0]
        self.assertEqual(len(sent['event_ids']), 15)
        self.assertEqual(sent['selection_count'], 15)
        self.assertEqual(self.ws.config['paper']['max_open_exposure'], 5)
