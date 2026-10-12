import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from prono.workspace import Workspace, timestamp, utcnow, write_record, merge
from prono.demo import seed
from prono.model import predict, load_history, compare
from prono.analysis import analyze, save_analysis, backtest
from prono.journal import add_paper, settle, summary, journal
from prono.providers import normalize_odds, ask
from prono.dashboard import page

ROOT = Path(__file__).resolve().parents[1]

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'config').mkdir()
        shutil.copy(ROOT/'config/workspace.toml', self.root/'config/workspace.toml')
        self.ws = Workspace(self.root)
        seed(self.ws)

    def tearDown(self): self.temp.cleanup()

    def edit_fixtures(self, change):
        path = self.ws.path('data/fixtures.json')
        rows = json.loads(path.read_text())
        change(rows)
        path.write_text(json.dumps(rows))

    def test_analysis_is_normalized_and_not_a_real_recommendation(self):
        r = analyze(self.ws, 'demo-1')
        self.assertEqual(r['status'], 'analysis_only')
        self.assertAlmostEqual(sum(r['model']['probabilities'].values()), 1)
        self.assertTrue(r['paper_only'])
        self.assertEqual(len(r['comparison']['outcomes']), 3)

    def test_market_margin_same_bookmaker(self):
        r = compare({'home': .5, 'draw': .25, 'away': .25}, {'home': 2, 'draw': 3, 'away': 3})
        self.assertAlmostEqual(r['overround'], 1/6)
        self.assertAlmostEqual(sum(x['market_probability_no_vig'] for x in r['outcomes']), 1)
        self.assertAlmostEqual(r['outcomes'][0]['expected_return_per_unit'], 0)

    def test_temporal_leakage_future_result_ignored(self):
        history = load_history(self.ws.path('data/history.csv'))
        cutoff = utcnow()
        base = predict(history, 'Lille Démo', 'Lens Démo', cutoff, self.ws.config['model'])
        poison = dict(history[0], event_id='future', home='Lille Démo', home_goals=30,
                      kickoff=(cutoff-timedelta(hours=1)).isoformat(), result_known_at=(cutoff+timedelta(hours=1)).isoformat())
        second = predict(history+[poison], 'Lille Démo', 'Lens Démo', cutoff, self.ws.config['model'])
        self.assertEqual(base, second)

    def test_result_at_exact_cutoff_not_used(self):
        history = load_history(self.ws.path('data/history.csv'))
        cutoff = utcnow()
        base = predict(history, 'Lille Démo', 'Lens Démo', cutoff, self.ws.config['model'])
        poison = dict(history[0], event_id='equal', kickoff=(cutoff-timedelta(hours=2)).isoformat(), result_known_at=cutoff.isoformat())
        self.assertEqual(base, predict(history+[poison], 'Lille Démo', 'Lens Démo', cutoff, self.ws.config['model']))

    def test_unknown_team_abstains(self):
        self.edit_fixtures(lambda r: r[0].update(home='Équipe inconnue'))
        self.assertEqual(analyze(self.ws, 'demo-1')['status'], 'insufficient_data')
        with self.assertRaises(ValueError): add_paper(self.ws, 'demo-1', 'home')

    def test_stale_odds_cannot_enter_journal(self):
        self.edit_fixtures(lambda r: r[0].update(quoted_at=(utcnow()-timedelta(hours=7)).isoformat()))
        self.assertEqual(analyze(self.ws, 'demo-1')['status'], 'stale_odds')
        with self.assertRaises(ValueError): add_paper(self.ws, 'demo-1', 'home')

    def test_future_odds_refused(self):
        self.edit_fixtures(lambda r: r[0].update(quoted_at=(utcnow()+timedelta(minutes=1)).isoformat()))
        with self.assertRaises(ValueError): analyze(self.ws, 'demo-1')

    def test_started_match_refused(self):
        future = utcnow()+timedelta(days=2)
        with self.assertRaises(ValueError): analyze(self.ws, 'demo-1', future)

    def test_duplicate_paper_and_settlement_refused(self):
        bet = add_paper(self.ws, 'demo-1', 'home')
        with self.assertRaises(ValueError): add_paper(self.ws, 'demo-1', 'away')
        settle(self.ws, bet['id'], 'void')
        with self.assertRaises(ValueError): settle(self.ws, bet['id'], 'win')
        self.assertEqual(summary(self.ws)['balance'], 100)
        self.assertIsNone(summary(self.ws)['roi'])

    def test_settlement_before_kickoff_refused(self):
        bet = add_paper(self.ws, 'demo-1', 'home')
        with self.assertRaises(ValueError): settle(self.ws, bet['id'], 'win')

    def test_paper_balance_win_and_loss(self):
        bet = add_paper(self.ws, 'demo-1', 'home')
        bet2 = add_paper(self.ws, 'demo-2', 'away')
        with patch('prono.journal.utcnow', return_value=utcnow()+timedelta(days=4)):
            settle(self.ws, bet['id'], 'win')
            settle(self.ws, bet2['id'], 'loss')
        s = summary(self.ws)
        self.assertAlmostEqual(s['balance'], 100.1)
        self.assertAlmostEqual(s['roi'], .05)
        self.assertAlmostEqual(s['max_drawdown_units'], 1)

    def test_open_exposure_limit(self):
        self.ws.config['paper']['max_open_exposure'] = 1
        add_paper(self.ws, 'demo-1', 'home')
        with self.assertRaises(ValueError): add_paper(self.ws, 'demo-2', 'home')

    def test_backtest_is_out_of_sample_and_not_roi(self):
        result = backtest(self.ws)
        self.assertGreater(result['evaluated'], 0)
        self.assertGreater(result['skipped'], 0)
        self.assertGreaterEqual(result['brier_multiclass'], 0)
        self.assertNotIn('roi', result)

    def test_archive_preserves_original_forecast(self):
        from prono.workspace import read_record
        r = analyze(self.ws, 'demo-1')
        path = save_analysis(self.ws, r)
        self.assertEqual(read_record(path)['model'], r['model'])

    def test_demo_never_overwrites(self):
        before = self.ws.path('data/history.csv').read_bytes()
        with self.assertRaises(ValueError): seed(self.ws)
        self.assertEqual(before, self.ws.path('data/history.csv').read_bytes())

    def test_nan_odds_rejected(self):
        with self.assertRaises(ValueError): compare({'home': .5, 'draw': .25, 'away': .25}, {'home': float('nan'), 'draw': 3, 'away': 3})

    def test_timezone_mandatory(self):
        with self.assertRaises(ValueError): timestamp('2026-10-10T18:00:00')

    def test_history_duplicates_and_unknown_at_invalid(self):
        path = self.ws.path('data/history.csv')
        text = path.read_text()
        path.write_text(text+text.splitlines()[1]+'\n')
        with self.assertRaises(ValueError): load_history(path)

    def test_provider_uses_one_bookmaker_not_best_price_mix(self):
        now = utcnow()
        def bm(key, prices):
            return {'key': key, 'last_update': now.isoformat(), 'markets': [{'key':'h2h', 'outcomes':[{'name':n,'price':p} for n,p in zip(['Home','Away','Draw'], prices)]}]}
        events = [{'id':'e1', 'commence_time':(now+timedelta(days=1)).isoformat(), 'home_team':'Home', 'away_team':'Away', 'bookmakers':[bm('b',[4,2,3]),bm('a',[2,4,3])]}]
        r = normalize_odds(events, now)[0]
        self.assertEqual(r['bookmaker'], 'a')
        self.assertEqual(r['odds'], {'home':2,'away':4,'draw':3})

    def test_dashboard_escapes_loaded_content(self):
        self.edit_fixtures(lambda r: r[0].update(home='<script>alert(1)</script>'))
        content = page(self.ws)
        self.assertNotIn('<script>', content)
        self.assertIn('&lt;script&gt;', content)

    def test_llm_only_receives_aggregates(self):
        self.ws.config['llm'].update(backend='openai-compatible', model='test-model')
        with patch('prono.providers.http_json', return_value={'choices':[{'message':{'content':'Bilan fictif.'}}]}) as mock:
            self.assertEqual(ask(self.ws, 'Explique mon bilan', summary(self.ws)), 'Bilan fictif.')
            body = mock.call_args.args[1]
            self.assertNotIn('Lille', json.dumps(body))
            self.assertNotIn('history.csv', json.dumps(body))

    def test_nested_user_config_does_not_discard_defaults(self):
        user = self.ws.path('config/workspace.user.toml')
        user.write_text('[coaching]\nstyle = "pedagogue"\n')
        merged = Workspace(self.root)
        self.assertEqual(merged.config['coaching']['style'], 'pedagogue')
        self.assertEqual(merged.config['coaching']['verbosity'], 'concise')

    def test_installer_never_overwrites_existing_ide_file(self):
        sys.path.insert(0, str(ROOT/'scripts'))
        from install import install_ide
        target = self.root/'.github/copilot-instructions.md'
        target.parent.mkdir(parents=True)
        target.write_text('MES INSTRUCTIONS')
        install_ide(self.root, 'copilot', Path('/python'))
        self.assertEqual(target.read_text(), 'MES INSTRUCTIONS')

    def test_cli_smoke(self):
        r = subprocess.run([sys.executable,'-m','prono.cli','--workspace',str(self.root),'doctor'], text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['fixtures'], 3)

    def test_actual_dashboard_http_and_host_filter(self):
        import socket
        import urllib.request
        import urllib.error
        with socket.socket() as s:
            s.bind(('127.0.0.1',0))
            port = s.getsockname()[1]
        process = subprocess.Popen([sys.executable,'-m','prono.cli','--workspace',str(self.root),'ui','--port',str(port)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertIn('Dashboard', process.stdout.readline())
            url = f'http://127.0.0.1:{port}'
            with urllib.request.urlopen(url+'/api/summary', timeout=5) as response:
                self.assertEqual(json.load(response)['balance'], 100)
            with urllib.request.urlopen(url, timeout=5) as response:
                self.assertIn('AI Prono Coach', response.read().decode())
                self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                urllib.request.urlopen(urllib.request.Request(url, headers={'Host':'evil.example'}), timeout=5)
            self.assertEqual(blocked.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(url+'/config/workspace.toml', timeout=5)
            self.assertEqual(missing.exception.code, 404)
        finally:
            process.terminate()
            process.communicate(timeout=5)

if __name__ == '__main__': unittest.main()
