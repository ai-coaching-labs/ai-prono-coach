"""The explicit calendar refresh loads confirmed fixtures through local J+3."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from prono.domestic_calendar import sync_domestic_calendar
from prono.market_watch import public_calendar, sync_markets
from prono.workspace import Workspace, timestamp

ROOT = Path(__file__).resolve().parents[1]


class DomesticCalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root/'config').mkdir()
        shutil.copy(ROOT/'config/workspace.toml', root/'config/workspace.toml')
        self.ws = Workspace(root)
        self.now = timestamp('2026-10-30T10:00:00Z')
        self.row = {'event_id': 'espn-E0-123', 'division': 'E0', 'home': 'Arsenal', 'away': 'Chelsea',
                    'kickoff': '2026-10-31T15:00:00+00:00', 'offers': [], 'quoted_at': None,
                    'collected_at': self.now.isoformat(), 'source': 'https://example.test/calendar',
                    'status': 'unverified_quote_time', 'analysis_eligible': False}

    def sync(self, rows, codes=None):
        with patch('prono.domestic_calendar.utcnow', return_value=self.now), \
             patch('prono.domestic_calendar.archive', return_value={'matches': rows, 'rejected': []}) as archive:
            result = sync_domestic_calendar(self.ws, codes or ['E0'])
        return result, archive

    def test_local_j3_month_boundary_without_past_or_j4_matches(self):
        rows = [self.row,
                {**self.row, 'event_id': 'past', 'kickoff': self.now.isoformat()},
                {**self.row, 'event_id': 'last', 'kickoff': '2026-11-02T22:59:00+00:00'},
                {**self.row, 'event_id': 'j4', 'kickoff': '2026-11-02T23:00:00+00:00'}]
        result, archive = self.sync(rows)
        self.assertEqual(result['end'], '2026-11-02')
        self.assertEqual(result['matches'], 2)
        self.assertEqual({c.args[2] for c in archive.call_args_list}, {'202610', '202611'})
        self.assertTrue(all(c.kwargs['slug'] == 'eng.1' for c in archive.call_args_list))
        stored = public_calendar(self.ws)['matches']
        self.assertEqual({r['source_event_id'] for r in stored}, {'espn-E0-123', 'last'})
        self.assertTrue(all(r['quoted_at'] is None and r['analysis_eligible'] is False for r in stored))
        self.assertFalse(self.ws.path('data/history.csv').exists())
        self.assertFalse(self.ws.path('data/fixtures.json').exists())

    def test_explicit_aliases_and_user_alias_override(self):
        self.sync([{**self.row, 'home': 'Manchester City'}])
        row = public_calendar(self.ws)['matches'][0]
        self.assertEqual(row['home'], 'Man City')
        self.assertEqual(row['provider_home'], 'Manchester City')
        self.ws.path('data/team-aliases.json').write_text(json.dumps({'E0': {'manchester city': 'my explicit label'}}))
        self.sync([{**self.row, 'home': 'Manchester City'}])
        self.assertEqual(public_calendar(self.ws)['matches'][0]['home'], 'Manchester City')

    def test_failed_refresh_preserves_previous_fixtures_and_their_dates(self):
        self.sync([self.row])
        original = copy.deepcopy(public_calendar(self.ws)['matches'])
        with patch('prono.domestic_calendar.utcnow', return_value=self.now), \
             patch('prono.domestic_calendar.archive', side_effect=ValueError('source unavailable')):
            result = sync_domestic_calendar(self.ws, ['E0'])
        self.assertEqual(result['sources']['E0']['status'], 'error')
        self.assertTrue(result['sources']['E0']['previous_preserved'])
        self.assertEqual(public_calendar(self.ws)['matches'], original)

    def test_failed_second_month_does_not_commit_a_partial_competition(self):
        self.sync([self.row])
        original = copy.deepcopy(public_calendar(self.ws)['matches'])
        with patch('prono.domestic_calendar.utcnow', return_value=self.now), \
             patch('prono.domestic_calendar.archive', side_effect=[{'matches': [], 'rejected': []}, ValueError('November unavailable')]):
            result = sync_domestic_calendar(self.ws, ['E0'])
        self.assertEqual(result['sources']['E0']['status'], 'error')
        self.assertEqual(public_calendar(self.ws)['matches'], original)

    def test_empty_success_clears_old_calendar_without_fabricating_fixtures(self):
        self.sync([self.row])
        result, _ = self.sync([])
        self.assertEqual(result['sources']['E0']['status'], 'ok')
        self.assertEqual(result['matches'], 0)
        self.assertEqual(public_calendar(self.ws)['matches'], [])

    def test_duplicate_calendar_sources_keep_one_fixture_and_primary_odds(self):
        self.sync([self.row])
        primary = {**self.row, 'event_id': 'watch-primary', 'home': 'ARSENAL',
                   'offers': [{'bookmaker': 'Example', 'odds': {'home': 2, 'draw': 3, 'away': 4}}]}
        self.ws.path('data/market-watch.json').write_text(json.dumps({'matches': [primary]}))
        with patch('prono.domestic_calendar.archive', side_effect=AssertionError('No network during reads')):
            rows = public_calendar(self.ws)['matches']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['event_id'], 'watch-primary')
        self.assertEqual(rows[0]['offers'], primary['offers'])

    def test_explicit_market_refresh_calls_domestic_calendar(self):
        csv = 'Div,Date,Time,HomeTeam,AwayTeam\nE0,31/10/2026,15:00,Arsenal,Chelsea\n'
        with patch('prono.market_watch.fetch_csv', return_value=csv), \
             patch('prono.domestic_calendar.sync_domestic_calendar', return_value={'matches': 7, 'sources': {}, 'end': '2026-11-02'}) as sync:
            result = sync_markets(self.ws, include_europe=False)
        sync.assert_called_once_with(self.ws)
        self.assertEqual(result['domestic']['matches'], 7)

    def test_failed_football_data_does_not_block_domestic_calendar_and_is_reported(self):
        with patch('prono.market_watch.fetch_csv', side_effect=ValueError('CSV unavailable')), \
             patch('prono.domestic_calendar.sync_domestic_calendar', return_value={'matches': 7, 'sources': {}, 'end': '2026-11-02'}):
            result = sync_markets(self.ws, include_europe=False)
        self.assertEqual(result['domestic']['matches'], 7)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['issues'][0]['provider'], 'Football-Data')

    def test_domestic_source_errors_are_exposed_in_refresh_summary(self):
        csv = 'Div,Date,Time,HomeTeam,AwayTeam\nE0,31/10/2026,15:00,Arsenal,Chelsea\n'
        with patch('prono.market_watch.fetch_csv', return_value=csv), \
             patch('prono.domestic_calendar.sync_domestic_calendar', return_value={'matches': 0, 'sources': {'E0': {'status': 'error', 'message': 'unavailable'}}}):
            result = sync_markets(self.ws, include_europe=False)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['issues'][0]['division'], 'E0')
