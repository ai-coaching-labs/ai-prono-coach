import copy
import csv
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from prono.workspace import Workspace, timestamp
from prono.model import HistoryWindow
from prono.evaluation import VARIANTS, evaluate_league
from prono.market_evaluation import compare_historical_market
from prono.tracking import tracking_summary
from prono.history_import import FIELDS

ROOT = Path(__file__).resolve().parents[1]


class MarketEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        shutil.copy(ROOT / "config/workspace.toml", self.root / "config/workspace.toml")
        self.ws = Workspace(self.root)
        self.ws.config["model"]["min_matches_per_team"] = 1
        self.now = timestamp("2026-10-12T20:00:00Z")
        self.target = {
            "event_id": "target",
            "kickoff": "2026-10-12T18:00:00Z",
            "result_known_at": "2026-10-12T20:00:00Z",
            "home": "A",
            "away": "B",
            "home_goals": 1,
            "away_goals": 0,
            "source": "test-only",
        }
        self.training = [
            {
                **self.target,
                "event_id": str(i),
                "kickoff": (self.now - timedelta(days=i + 2)).isoformat(),
                "result_known_at": (
                    self.now - timedelta(days=i + 2) + timedelta(hours=2)
                ).isoformat(),
            }
            for i in range(12)
        ]
        self.quote = {
            "created_at": "2026-10-12T12:00:00Z",
            "fixture": {
                "event_id": "different-provider-id",
                "home": "A",
                "away": "B",
                "kickoff": self.target["kickoff"],
                "bookmaker": "test-only",
                "source": "test-only",
                "quoted_at": "2026-10-12T11:00:00Z",
                "odds": {"home": 2, "draw": 3, "away": 4},
            },
        }

    def compare(self, quotes, targets=None, training=None, mode="observed"):
        return compare_historical_market(
            self.ws,
            HistoryWindow(self.training if training is None else training),
            [self.target] if targets is None else targets,
            VARIANTS,
            mode,
            self.now,
            quotes,
        )

    def test_all_variants_and_market_use_identical_sample_at_quote_knowledge(self):
        unquoted = {**self.target, "event_id": "unquoted", "home": "C"}
        result = self.compare([self.quote], [self.target, unquoted])
        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(result["excluded"], {"no_valid_quote": 1})
        expected = sum((p - y) ** 2 for p, y in [(6 / 13, 1), (4 / 13, 0), (3 / 13, 0)])
        self.assertAlmostEqual(result["market"]["brier"], expected)
        for model in result["models"].values():
            self.assertEqual(model["evaluated"], 1)
            self.assertAlmostEqual(model["delta_brier"], model["brier"] - expected)
        self.assertEqual(result["samples"][0]["as_of"], "2026-10-12T12:00:00+00:00")

    def test_future_knowledge_between_quote_and_kickoff_is_not_training_data(self):
        training = copy.deepcopy(self.training)
        for row in training:
            row["result_known_at"] = "2026-10-12T13:00:00Z"
        self.assertEqual(
            self.compare([self.quote], training=training)["excluded"],
            {"insufficient_history_at_quote": 1},
        )
        self.assertEqual(
            self.compare([self.quote], training=training, mode="snapshot")["evaluated"],
            1,
        )

    def test_quotes_without_documented_pre_match_knowledge_are_excluded(self):
        for field, value in [
            ("created_at", None),
            ("created_at", self.target["kickoff"]),
            ("quoted_at", None),
            ("quoted_at", "2026-10-12T12:00:01Z"),
            ("quoted_at", "2026-10-12T05:59:00Z"),
        ]:
            q = copy.deepcopy(self.quote)
            if field == "created_at":
                q[field] = value
            else:
                q["fixture"][field] = value
            self.assertEqual(self.compare([q])["evaluated"], 0)

    def test_last_valid_quote_is_chosen_without_selecting_best_market_score(self):
        later = copy.deepcopy(self.quote)
        later["created_at"] = "2026-10-12T14:00:00Z"
        later["fixture"]["odds"] = {"home": 5, "draw": 4, "away": 2}
        a = self.compare([self.quote, later])
        b = self.compare([later, self.quote])
        self.assertEqual(a, b)
        self.assertEqual(a["samples"][0]["as_of"], "2026-10-12T14:00:00+00:00")
        conflicting = copy.deepcopy(later)
        conflicting["fixture"]["odds"]["home"] = 8
        self.assertEqual(
            self.compare([later, conflicting])["excluded"], {"conflicting_quotes": 1}
        )

    def test_full_evaluation_reads_historical_triplets_but_does_not_backdate_knowledge(
        self,
    ):
        history = sorted(
            self.training + [self.target], key=lambda r: timestamp(r["kickoff"])
        )
        path = self.ws.path("data/history.csv")
        path.parent.mkdir()
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(history)
        original = path.read_bytes()
        fixture = dict(self.quote["fixture"], collected_at=self.quote["created_at"])
        self.ws.path("data/fixtures.json").write_text(json.dumps([fixture]))
        result = evaluate_league(self.ws, "observed", self.now)
        self.assertEqual(result["market_comparison"]["evaluated"], 1)
        from prono.analysis import backtest

        self.assertEqual(
            backtest(self.ws, self.now)["market_comparison"]["evaluated"], 1
        )
        self.assertEqual(path.read_bytes(), original)
        fixture.pop("collected_at")
        self.ws.path("data/fixtures.json").write_text(json.dumps([fixture]))
        result = evaluate_league(self.ws, "observed", self.now)
        self.assertEqual(result["market_comparison"]["evaluated"], 0)
        self.assertIn(
            "quote_knowledge_unavailable",
            result["market_comparison"]["quote_exclusions"],
        )

    def test_model_review_jalon_never_promotes_the_model(self):
        self.ws.config["tracking"]["min_settled_before_model_review"] = 2
        row = {
            **self.quote,
            "id": "x",
            "division": "F1",
            "synthetic": False,
            "outcome": "home",
            "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        }
        from prono.workspace import write_record

        write_record(
            self.ws.path("analyses/outcome-x.md"),
            "forecast_outcome",
            {"status": "settled", "actual": "home"},
        )
        with patch("prono.tracking.forecasts", return_value=[row]):
            review = tracking_summary(self.ws)["model_review"]
        self.assertFalse(review["ready_for_review"])
        with patch("prono.tracking.forecasts", return_value=[row, dict(row, id="y")]):
            write_record(
                self.ws.path("analyses/outcome-y.md"),
                "forecast_outcome",
                {"status": "settled", "actual": "home"},
            )
            review = tracking_summary(self.ws)["model_review"]
        self.assertTrue(review["ready_for_review"])
        self.assertFalse(review["automatic_promotion"])
        self.assertEqual(review["production_model"], "poisson-baseline-v1")

    def test_conflicting_triplets_are_not_hidden_by_identical_normalized_probabilities(
        self,
    ):
        second = copy.deepcopy(self.quote)
        second["fixture"]["source"] = "another-test-source"
        second["fixture"]["odds"] = {"home": 4, "draw": 6, "away": 8}
        self.assertEqual(
            self.compare([self.quote, second])["excluded"], {"conflicting_quotes": 1}
        )
