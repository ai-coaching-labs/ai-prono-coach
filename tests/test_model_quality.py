"""Comparaisons appariées, dates strictes et captures sans doublons."""

import copy
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from prono.analysis import backtest
from prono.evaluation import latest_evaluation, evaluate_league
from prono.history_import import sync_history
from prono.leagues import league_workspace
from prono.metrics import market_comparison
from prono.model import HistoryWindow, predict, predict_rows, load_history
from prono.workspace import Workspace, timestamp, write_record

ROOT = Path(__file__).resolve().parents[1]
CSV = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\nF1,15/08/2025,19:45,A,B,1,0\n"


class ModelQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "config").mkdir()
        shutil.copy(ROOT / "config/workspace.toml", root / "config/workspace.toml")
        self.ws = Workspace(root)

    def observation(self):
        return {
            "created_at": "2026-10-12T12:00:00Z",
            "probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15},
            "actual": "home",
            "fixture": {
                "quoted_at": "2026-10-12T11:00:00Z",
                "kickoff": "2026-10-12T18:00:00Z",
                "bookmaker": "test-only",
                "source": "test-only",
                "odds": {"home": 2, "draw": 3, "away": 4},
            },
        }

    def test_market_uses_same_sample_and_normalizes_one_triplet(self):
        valid = self.observation()
        missing = self.observation()
        missing["fixture"]["quoted_at"] = None
        missing["probabilities"] = {"home": 0.05, "draw": 0.05, "away": 0.9}
        result = market_comparison([valid, missing])
        expected = market_comparison([valid])
        self.assertEqual(result["model"], expected["model"])
        self.assertEqual(result["market"], expected["market"])
        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(result["excluded"], {"quote_time_unavailable": 1})
        self.assertLess(result["delta_brier"], 0)
        self.assertAlmostEqual(
            result["market"]["brier"],
            sum(
                (p - actual) ** 2
                for p, actual in [(6 / 13, 1), (4 / 13, 0), (3 / 13, 0)]
            ),
        )

    def test_market_refuses_future_post_match_stale_or_invalid_quotes(self):
        for changes in [
            {"quoted_at": "2026-10-12T12:00:01Z"},
            {"quoted_at": "2026-10-12T18:00:00Z"},
            {"quoted_at": "2026-10-12T05:59:59Z"},
            {"odds": {"home": float("nan"), "draw": 3, "away": 4}},
            {"bookmaker": ""},
        ]:
            row = self.observation()
            row["fixture"].update(changes)
            self.assertEqual(market_comparison([row])["evaluated"], 0)
        row = self.observation()
        row["created_at"] = row["fixture"]["kickoff"]
        self.assertEqual(market_comparison([row])["evaluated"], 0)

    def test_identical_csv_retains_source_files_and_first_knowledge(self):
        first = timestamp("2026-10-10T09:00:00Z")
        with (
            patch("prono.history_import.fetch_csv", return_value=CSV),
            patch("prono.history_import.utcnow", return_value=first),
        ):
            sync_history(self.ws, ["2526"])
        sources = {
            p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in self.ws.path("data/sources").iterdir()
        }
        history = self.ws.path("data/history.csv").read_bytes()
        with (
            patch("prono.history_import.fetch_csv", return_value=CSV),
            patch(
                "prono.history_import.utcnow", return_value=first + timedelta(days=1)
            ),
        ):
            sync_history(self.ws, ["2526"])
        self.assertEqual(
            sources,
            {
                p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.ws.path("data/sources").iterdir()
            },
        )
        self.assertEqual(history, self.ws.path("data/history.csv").read_bytes())
        with patch(
            "prono.history_import.fetch_csv", return_value=CSV.replace(",1,0", ",2,0")
        ):
            with self.assertRaisesRegex(ValueError, "corrigée"):
                sync_history(self.ws, ["2526"])
        self.assertEqual(len(list(self.ws.path("data/sources").glob("*.csv"))), 2)
        self.assertEqual(history, self.ws.path("data/history.csv").read_bytes())

    def test_identical_espn_payload_has_one_capture_despite_key_order(self):
        from prono.europe import archive

        with patch(
            "prono.europe.fetch", return_value=("test-only", {"events": [], "a": 1})
        ):
            archive(self.ws, "UCL", "2026")
        files = {p.name: p.read_bytes() for p in self.ws.path("data/sources").iterdir()}
        with patch(
            "prono.europe.fetch", return_value=("test-only", {"a": 1, "events": []})
        ):
            archive(self.ws, "UCL", "2026")
        self.assertEqual(
            files,
            {p.name: p.read_bytes() for p in self.ws.path("data/sources").iterdir()},
        )

    def test_window_matches_strict_predict_and_embargo_boundaries(self):
        cutoff = timestamp("2026-10-12T12:00:00Z")
        rows = []
        for i, (kickoff, known) in enumerate(
            [
                (cutoff - timedelta(days=2), cutoff - timedelta(seconds=1)),
                (cutoff - timedelta(days=1), cutoff),
                (cutoff - timedelta(hours=23), cutoff - timedelta(hours=1)),
                (cutoff, cutoff + timedelta(hours=2)),
                (cutoff - timedelta(days=6), cutoff - timedelta(days=5)),
            ]
        ):
            rows.append(
                dict(
                    event_id=str(i),
                    kickoff=kickoff.isoformat(),
                    result_known_at=known.isoformat(),
                    home="A",
                    away="B",
                    home_goals=1,
                    away_goals=0,
                    source="test-only",
                )
            )
        window = HistoryWindow(rows)
        self.assertEqual(
            [r["event_id"] for r in window.eligible(cutoff, 5)], ["0", "2"]
        )
        self.assertEqual(
            [r["event_id"] for r in window.eligible(cutoff, 5, "snapshot")], ["0", "1"]
        )
        config = dict(
            self.ws.config["model"], min_matches_per_team=1, max_history_days=5
        )
        old = predict(rows, "A", "B", cutoff, config)
        new = predict_rows(
            window.eligible(cutoff, 5),
            "A",
            "B",
            cutoff,
            config,
            kickoff_times=window.kickoff_times,
        )
        self.assertEqual(old, new)

    def test_old_evaluation_is_marked_outdated_and_missing_leagues_visible(self):
        child = league_workspace(self.ws, "F1", create=True)
        child.path("data").mkdir(exist_ok=True)
        child.path("data/history.csv").write_text("test-only")
        other = league_workspace(self.ws, "E0", create=True)
        other.path("data").mkdir(exist_ok=True)
        other.path("data/history.csv").write_text("test-only")
        write_record(
            self.ws.path("rapports/20261010_evaluation.md"),
            "model_comparison",
            {"leagues": {"F1": {"history_sha256": None}}},
        )
        result = latest_evaluation(self.ws)
        self.assertFalse(result["currency"]["F1"]["current"])
        self.assertEqual(len(result["currency"]["F1"]["reasons"]), 2)
        self.assertEqual(result["not_evaluated"], ["E0"])

    def test_tracking_market_reference_uses_frozen_quote_only(self):
        from prono.tracking import tracking_summary

        row = self.observation()
        row.update(
            id="frozen",
            division="F1",
            event_id="event",
            synthetic=False,
            outcome="home",
        )
        row["fixture"].update(home="A", away="B")
        write_record(
            self.ws.path("analyses/outcome-frozen.md"),
            "forecast_outcome",
            {"status": "settled", "actual": "home"},
        )
        before = copy.deepcopy(row)
        with patch("prono.tracking.forecasts", return_value=[row]):
            result = tracking_summary(self.ws)
        self.assertEqual(result["performance"]["evaluated"], 1)
        self.assertEqual(result["market_comparison"]["evaluated"], 1)
        self.assertEqual(result["market_comparison"], market_comparison([before]))
        self.assertEqual(before, row)

    def test_chat_template_keeps_untrusted_token_as_escaped_data(self):
        from prono.chat import page

        output = page('"><script>{css}</script>')
        self.assertIn("&quot;&gt;&lt;script&gt;{css}&lt;/script&gt;", output)
        self.assertNotIn("<script>{css}</script>", output)
        self.assertIn("Sur quel match veux-tu faire le point ? Je peux aussi", output)
