"""Contexte xG indépendant : provenance, corrections, dates et absence de réseau implicite."""
import copy
import gzip
import io
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from prono.understat import UnderstatForm, fetch_season, normalize_matches, save_capture, sync_xg
from prono.workspace import Workspace, timestamp

ROOT = Path(__file__).resolve().parents[1]
NOW = timestamp('2026-10-15T15:00:00Z')
KICKOFF = '2026-10-16T19:00:00Z'


class UnderstatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); (root/'config').mkdir()
        shutil.copy(ROOT/'config/workspace.toml', root/'config/workspace.toml')
        self.ws = Workspace(root)

    def match(self, i=0, days=3, home=True, xg=2.0):
        return {'id':str(100+i), 'isResult':True,
                'h':{'id':'1' if home else '2','title':'Paris Saint Germain' if home else 'Opponent'},
                'a':{'id':'2' if home else '1','title':'Opponent' if home else 'Paris Saint Germain'},
                'goals':{'h': '2', 'a':'1'}, 'xG':{'h':xg, 'a':0.5},
                'datetime':(NOW-timedelta(days=days)).replace(tzinfo=None).isoformat(sep=' '),
                'forecast':{'w':0.9,'d':0.09,'l':0.01}}

    def store(self, rows=None, known=None, season=2026):
        return save_capture(self.ws, 'F1', season, {'dates':rows or [self.match()]}, known or NOW-timedelta(minutes=1))

    def form(self, as_of=NOW, kickoff=KICKOFF, name='Paris SG', division='UCL'):
        return UnderstatForm(self.ws, as_of.isoformat()).team(name,kickoff,division)

    def test_window_averages_venues_alias_and_no_provider_forecast(self):
        self.store([self.match(i,days=i+3,home=i%2==0) for i in range(12)])
        form = self.form()
        self.assertTrue(form['available'])
        self.assertEqual(form['last5']['played'],5)
        self.assertEqual(form['last10']['played'],10)
        self.assertEqual(form['home_last5']['played'],5)
        self.assertEqual(form['away_last5']['played'],5)
        self.assertAlmostEqual(form['last5']['xg_for_per_match'],1.4)
        self.assertAlmostEqual(form['last5']['xg_against_per_match'],1.1)
        self.assertNotIn('forecast',json.dumps(form))
        self.assertIn('understat.com/league/Ligue_1',form['matches_newest_first'][0]['source_url'])
        self.assertTrue(self.form(name='Paris Saint-Germain')['available'])

    def test_knowledge_strict_before_as_of_and_fixture_never_inferred_from_filename(self):
        self.store(known=NOW)
        self.assertFalse(self.form()['available'])
        self.assertTrue(self.form(as_of=NOW+timedelta(seconds=1))['available'])
        self.assertFalse(self.form(kickoff=(NOW-timedelta(seconds=1)).isoformat())['available'])
        self.assertFalse(self.form(as_of=NOW-timedelta(days=1))['available'])

    def test_naive_dates_keep_original_and_exclude_today_yesterday_future_and_old(self):
        self.store([self.match(i,days=days) for i,days in enumerate([0,1,2,-1,181])])
        form = self.form()
        self.assertEqual(form['last10']['played'],1)
        row = form['matches_newest_first'][0]
        self.assertEqual(row['date_status'],'timezone_unverified')
        self.assertNotIn('kickoff',row)
        self.assertEqual(row['provider_datetime'],self.match(2,days=2)['datetime'])
        self.assertTrue(any('Fuseau' in w for w in form['warnings']))

    def test_corrections_preserve_original_knowledge_and_previous_values(self):
        first = self.store(known=NOW-timedelta(hours=2))
        again = self.store(known=NOW)
        self.assertTrue(again['reused']); self.assertEqual(first['collected_at'],again['collected_at'])
        corrected = self.store([self.match(xg=1.0)],known=NOW-timedelta(hours=1))
        self.assertNotEqual(first['path'],corrected['path'])
        self.assertAlmostEqual(self.form(as_of=NOW-timedelta(minutes=90))['last5']['xg_for'],2.0)
        self.assertAlmostEqual(self.form()['last5']['xg_for'],1.0)
        self.assertTrue(Path(first['path']).exists())

    def test_simultaneous_contradictory_captures_are_unavailable(self):
        self.store([self.match(xg=1.0)])
        self.store([self.match(xg=2.0)])
        form = self.form()
        self.assertFalse(form['available'])
        self.assertTrue(form['load_issues'])

    def test_missing_zero_nonfinite_duplicate_and_unfinished(self):
        zero = self.match(xg=0.0)
        missing = self.match(1); missing['xG']['h']=None
        unfinished = self.match(2); unfinished['isResult']=False
        rows, excluded = normalize_matches([zero,missing,unfinished])
        self.assertEqual(rows[0]['home']['xg'],0)
        self.assertEqual(excluded,{'xg_missing':1,'not_finished':1})
        for bad in [float('nan'),-1,True]:
            with self.subTest(bad=bad), self.assertRaises(ValueError): normalize_matches([self.match(xg=bad)])
        with self.assertRaises(ValueError):normalize_matches([zero,zero])

    def test_history_seasons_explicit_and_default_only_two(self):
        with patch('prono.understat.utcnow',return_value=NOW), patch('prono.understat.fetch_season',return_value={'dates':[self.match()]}) as fetch:
            result = sync_xg(self.ws,['F1'])
            self.assertEqual([c.args for c in fetch.call_args_list],[('F1',2026),('F1',2025)])
            self.assertTrue(all(r['status']=='ok' for r in result['imports']))
            fetch.reset_mock(); sync_xg(self.ws,['F1'],[2014])
            fetch.assert_called_once_with('F1',2014)
            fetch.reset_mock()
            with self.assertRaises(ValueError):sync_xg(self.ws,['F2'])
            with self.assertRaises(ValueError):sync_xg(self.ws,['F1'],[2027])
            fetch.assert_not_called()

    def test_network_error_keeps_existing_capture_and_reports_error(self):
        original=self.store()
        with patch('prono.understat.fetch_season',side_effect=ValueError('HTTP 403')):
            result=sync_xg(self.ws,['F1'],[2026])
        self.assertEqual(result['imports'][0]['status'],'error')
        self.assertTrue(Path(original['path']).exists())
        self.assertTrue(self.form()['available'])

    def test_gzip_response_public_request_and_size_limit(self):
        raw=gzip.compress(json.dumps({'dates':[self.match()]}).encode())
        with patch('urllib.request.urlopen',return_value=io.BytesIO(raw)) as fetch:
            self.assertEqual(len(fetch_season('F1',2026)['dates']),1)
            self.assertEqual(fetch.call_args.args[0].get_header('X-requested-with'),'XMLHttpRequest')
        with patch('prono.understat.MAX_BYTES',10),patch('urllib.request.urlopen',return_value=io.BytesIO(b'x'*11)):
            with self.assertRaises(ValueError):fetch_season('F1',2026)

    def test_local_read_only_unsupported_unknown_partial_and_stale(self):
        self.store([self.match(days=30)])
        with patch('prono.understat.fetch_season') as fetch:
            form=self.form();fetch.assert_not_called()
        self.assertTrue(form['stale']);self.assertEqual(form['last10']['played'],1)
        self.assertFalse(self.form(name='Unknown')['available'])
        self.assertFalse(self.form(division='N1')['available'])

    def test_tampered_snapshot_not_used(self):
        result=self.store();path=Path(result['path']);data=json.loads(path.read_text())
        data['matches'][0]['home']['xg']=99;path.write_text(json.dumps(data))
        form=self.form();self.assertFalse(form['available']);self.assertTrue(form['load_issues'])
