import importlib.util
import json
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "compact_archives", ROOT / "scripts/compact_archives.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ArchiveCompactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.sources = self.root / "data/workspaces/f1/data/sources"
        self.sources.mkdir(parents=True)
        self.archive = Path(self.temp.name) / "archives"
        (self.root / "dist").mkdir()

    def capture(self, name, content, collected):
        p = self.sources / name
        p.write_text(content)
        p.with_suffix(".json").write_text(
            json.dumps({"url": "test-only", "collected_at": collected})
        )
        return p

    def build(self, name, version):
        p = self.root / "dist" / name / "AI Prono Coach.app/Contents"
        p.mkdir(parents=True)
        p.joinpath("Info.plist").write_bytes(
            plistlib.dumps({"CFBundleShortVersionString": version})
        )
        p.joinpath("executable").write_bytes(b"test-only")
        p.joinpath("external-link").symlink_to(self.sources)
        return p.parent.parent

    def test_dry_run_preserves_every_file_and_apply_archives_all_removed_bytes(self):
        first = self.capture("first.csv", "identical", "2026-10-10T10:00:00Z")
        duplicate = self.capture("duplicate.csv", "identical", "2026-10-11T10:00:00Z")
        distinct = self.capture("correction.csv", "corrected", "2026-10-12T10:00:00Z")
        history = self.sources.parent / "history.csv"
        history.write_bytes(b"first knowledge and kickoff must remain unchanged")
        old = self.build("macos-old", "0.3.5")
        previous = self.build("macos-previous", "0.3.6")
        current = self.build("macos-current", "0.3.7")
        original = {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file() and not p.is_symlink()
        }
        report = module.compact(self.root, self.archive)
        self.assertEqual(report["duplicate_capture_files"], 2)
        self.assertFalse(self.archive.exists())
        self.assertTrue(duplicate.exists())
        report = module.compact(self.root, self.archive, True)
        self.assertEqual(report["skipped"], [])
        self.assertTrue(first.exists())
        self.assertTrue(distinct.exists())
        self.assertFalse(duplicate.exists())
        self.assertFalse(old.exists())
        self.assertTrue(previous.exists())
        self.assertTrue(current.exists())
        self.assertEqual(
            history.read_bytes(), original[str(history.relative_to(self.root))]
        )
        with zipfile.ZipFile(report["archive"]) as saved:
            self.assertIsNone(saved.testzip())
            manifest = json.loads(saved.read("COMPACTION-MANIFEST.json"))
            for record in manifest["files"]:
                if record["kind"] == "file":
                    self.assertEqual(
                        saved.read(record["path"]), original[record["path"]]
                    )
            self.assertEqual(
                saved.read(
                    str(
                        (old / "AI Prono Coach.app/Contents/external-link").relative_to(
                            self.root
                        )
                    )
                ).decode(),
                str(self.sources),
            )

    def test_different_source_and_original_encoding_are_not_merged(self):
        a = self.capture("a.csv", "same text", "2026-10-10T10:00:00Z")
        b = self.capture("b.csv", "same text", "2026-10-11T10:00:00Z")
        a.with_suffix(".raw.csv").write_bytes(b"raw-1")
        b.with_suffix(".raw.csv").write_bytes(b"raw-2")
        c = self.capture("c.csv", "same text", "2026-10-12T10:00:00Z")
        c.with_suffix(".json").write_text(
            json.dumps(
                {"url": "different-source", "collected_at": "2026-10-12T10:00:00Z"}
            )
        )
        self.assertEqual(module.captures(self.root), [])

    def test_invalid_metadata_is_preserved(self):
        a = self.capture("a.csv", "same", "2026-10-10T10:00:00Z")
        b = self.capture("b.csv", "same", "2026-10-11T10:00:00Z")
        a.with_suffix(".json").write_text("broken metadata")
        self.assertEqual(module.captures(self.root), [])
        self.assertTrue(b.exists())

    def test_market_refresh_reuses_identical_source_without_inventing_quote_time(self):
        import shutil
        from prono.workspace import Workspace, timestamp
        from prono.market_watch import sync_markets

        (self.root / "config").mkdir()
        shutil.copy(ROOT / "config/workspace.toml", self.root / "config/workspace.toml")
        ws = Workspace(self.root)
        csv = "Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A\nF1,15/10/2026,19:45,A,B,2,3,4\n"
        with (
            patch("prono.market_watch.fetch_csv", return_value=csv),
            patch(
                "prono.market_watch.utcnow",
                return_value=timestamp("2026-10-12T10:00:00Z"),
            ),
        ):
            sync_markets(ws, include_europe=False, include_domestic=False)
        original_capture = next(ws.path("data/sources").glob("fixtures-*.csv"))
        original_capture.rename(
            ws.path("data/sources/fixtures-20261012T100000000000.csv")
        )
        files = {
            p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in ws.path("data/sources").iterdir()
        }
        with (
            patch("prono.market_watch.fetch_csv", return_value=csv),
            patch(
                "prono.market_watch.utcnow",
                return_value=timestamp("2026-10-12T11:00:00Z"),
            ),
        ):
            sync_markets(ws, include_europe=False, include_domestic=False)
        self.assertEqual(
            files,
            {
                p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in ws.path("data/sources").iterdir()
            },
        )
        current = json.loads(ws.path("data/market-watch.json").read_text())
        self.assertEqual(current["collected_at"], "2026-10-12T11:00:00+00:00")
        self.assertIsNone(current["matches"][0]["quoted_at"])

    def test_legacy_espn_capture_is_reused_without_changing_first_collection(self):
        from prono.workspace import Workspace
        from prono.europe import archive
        import shutil

        (self.root / "config").mkdir()
        shutil.copy(ROOT / "config/workspace.toml", self.root / "config/workspace.toml")
        ws = Workspace(self.root)
        path = ws.path("data/sources/espn-UCL-2026-20261010T100000000000.json")
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(
            json.dumps(
                {
                    "source": "test-only",
                    "collected_at": "2026-10-10T10:00:00Z",
                    "data": {"events": []},
                }
            )
        )
        original = path.read_bytes()
        with patch("prono.europe.fetch", return_value=("test-only", {"events": []})):
            archive(ws, "UCL", "2026")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.glob("espn-*.json")), [path])

    def test_previous_version_dmg_is_archived_when_a_new_release_exists(self):
        import os

        first = self.root / "dist/AI-Prono-Coach-0.3.7.dmg"
        newer = self.root / "dist/AI-Prono-Coach-0.3.8.dmg"
        first.write_bytes(b"old-test-only")
        newer.write_bytes(b"new-test-only")
        os.utime(first, (1700000100, 1700000100))
        os.utime(newer, (1700000200, 1700000200))
        report = module.compact(self.root, self.archive, True)
        self.assertFalse(first.exists())
        self.assertTrue(newer.exists())
        with zipfile.ZipFile(report["archive"]) as saved:
            self.assertEqual(saved.read("dist/" + first.name), b"old-test-only")
