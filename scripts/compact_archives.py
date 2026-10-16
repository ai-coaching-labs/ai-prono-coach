"""Compacter les doublons exacts et les constructions anciennes, avec archive restaurable.

Sans --apply : inventaire seulement. Aucune collecte ni suppression d'historique.
"""

import argparse
import hashlib
import json
import os
import plistlib
import re
import stat
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def size(root):
    return sum(
        p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink()
    )


def captures(root):
    groups = defaultdict(list)
    for directory in root.joinpath("data").rglob("sources"):
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in directory.glob("*.csv"):
            if path.is_symlink() or path.name.endswith(".raw.csv"):
                continue
            meta_path = path.with_suffix(".json")
            raw = path.with_suffix(".raw.csv")
            try:
                meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
                if meta_path.is_symlink() or raw.is_symlink():
                    continue
                key = (
                    str(directory),
                    meta.get("url", meta.get("source", "")),
                    digest(path),
                    digest(raw) if raw.exists() else None,
                )
                collected = meta.get("collected_at")
                filename_time = re.search(r"-(\d{8}T\d{12})\.csv$", path.name)
                order = (
                    datetime.fromisoformat(collected.replace("Z", "+00:00")).timestamp()
                    if collected
                    else (
                        datetime.strptime(filename_time.group(1), "%Y%m%dT%H%M%S%f")
                        .replace(tzinfo=timezone.utc)
                        .timestamp()
                        if filename_time
                        else path.stat().st_mtime
                    )
                )
                files = (
                    [path]
                    + ([meta_path] if meta_path.exists() else [])
                    + ([raw] if raw.exists() else [])
                )
                groups[key].append((order, path, files))
            except (ValueError, OSError, TypeError):
                continue  # Une provenance illisible n'autorise pas sa suppression.
        for path in directory.glob("espn-*.json"):
            if path.is_symlink():
                continue
            try:
                meta = json.loads(path.read_text())
                source = meta["source"]
                content = json.dumps(
                    meta["data"],
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
                key = (str(directory), source, hashlib.sha256(content).hexdigest())
                order = datetime.fromisoformat(
                    meta["collected_at"].replace("Z", "+00:00")
                ).timestamp()
                groups[key].append((order, path, [path]))
            except (KeyError, ValueError, OSError, TypeError):
                continue
    removals = []
    for group in groups.values():
        group.sort(key=lambda item: (item[0], str(item[1])))
        kept = group[0][1]
        for _, _, files in group[1:]:
            removals.extend((path, "identical_capture", kept) for path in files)
    return removals


def old_distributions(root):
    dist = root / "dist"
    if not dist.exists():
        return [], []
    # Une construction pour chacune des deux versions les plus récentes.
    builds = defaultdict(list)
    for path in dist.glob("macos-*"):
        info = path / "AI Prono Coach.app/Contents/Info.plist"
        try:
            version = tuple(
                int(v)
                for v in plistlib.loads(info.read_bytes())[
                    "CFBundleShortVersionString"
                ].split(".")
            )
            builds[version].append(path)
        except (OSError, ValueError, KeyError, plistlib.InvalidFileException):
            continue
    keep = {
        max(builds[v], key=lambda p: p.stat().st_mtime_ns)
        for v in sorted(builds, reverse=True)[:2]
    }
    dmgs = list(dist.glob("AI-Prono-Coach-*.dmg"))
    if dmgs:
        keep.add(max(dmgs, key=lambda p: p.stat().st_mtime_ns))
    latest_validation = dist / "validation-macos.json"
    if latest_validation.exists():
        keep.add(latest_validation)
    candidates = []
    for entry in dist.iterdir():
        if entry in keep:
            continue
        recognized = (
            entry.name.startswith("macos-")
            or (entry.name.startswith("AI-Prono-Coach-") and entry.suffix == ".dmg")
            or entry.name.endswith((".dmg.previous", ".previous", ".jpg"))
            or entry.name.startswith("validation-macos-")
            or entry.name == ".DS_Store"
        )
        if not recognized:
            continue
        paths = (
            list(entry.rglob("*"))
            if entry.is_dir() and not entry.is_symlink()
            else [entry]
        )
        candidates.extend(
            (p, "obsolete_distribution", None)
            for p in paths
            if p.is_file() or p.is_symlink()
        )
    return candidates, sorted(str(p.relative_to(root)) for p in keep)


def plan(root):
    root = root.resolve()
    distributions, kept = old_distributions(root)
    candidates = captures(root) + distributions
    records = []
    seen = set()
    for path, reason, reference in candidates:
        if path in seen:
            continue
        seen.add(path)
        relative = str(path.relative_to(root))
        if path.is_symlink():
            content = os.readlink(path).encode()
            kind = "symlink"
        else:
            content = path.read_bytes()
            kind = "file"
        records.append(
            {
                "path": relative,
                "reason": reason,
                "kind": kind,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "kept": str(reference.relative_to(root)) if reference else None,
                "kept_sha256": digest(reference) if reference else None,
            }
        )
    return {
        "workspace": str(root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "before": {name: size(root / name) for name in ("data", "dist")},
        "kept_distributions": kept,
        "files": records,
    }


def compact(root, archive_directory, apply=False):
    root = root.resolve()
    manifest = plan(root)
    summary = {
        "before": manifest["before"],
        "planned_files": len(manifest["files"]),
        "planned_bytes": sum(r["bytes"] for r in manifest["files"]),
        "duplicate_capture_files": sum(
            r["reason"] == "identical_capture" for r in manifest["files"]
        ),
        "kept_distributions": manifest["kept_distributions"],
    }
    if not apply or not manifest["files"]:
        return summary
    archive_directory = archive_directory.resolve()
    if archive_directory == root or root in archive_directory.parents:
        raise ValueError(
            "Placer l’archive hors du workspace pour éviter une archive récursive."
        )
    archive_directory.mkdir(parents=True, exist_ok=True)
    archive = archive_directory / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-compaction.zip"
    )
    # Mode exclusif : ne jamais remplacer une archive antérieure.
    with zipfile.ZipFile(
        archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as output:
        for record in manifest["files"]:
            path = root / record["path"]
            content = (
                os.readlink(path).encode()
                if record["kind"] == "symlink"
                else path.read_bytes()
            )
            if hashlib.sha256(content).hexdigest() != record["sha256"]:
                raise ValueError(
                    "Fichier modifié pendant la préparation : aucun fichier retiré."
                )
            if record["kind"] == "symlink":
                info = zipfile.ZipInfo(record["path"])
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                output.writestr(info, content)
            else:
                output.write(path, record["path"])
        output.writestr(
            "COMPACTION-MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    # Vérification CRC et empreinte de chaque fichier avant le premier retrait.
    with zipfile.ZipFile(archive) as saved:
        if saved.testzip() is not None:
            raise ValueError("Archive invalide : aucun fichier retiré.")
        for record in manifest["files"]:
            if (
                hashlib.sha256(saved.read(record["path"])).hexdigest()
                != record["sha256"]
            ):
                raise ValueError("Empreinte d’archive invalide : aucun fichier retiré.")
    removed, skipped = [], []
    parents = set()
    for record in manifest["files"]:
        path = root / record["path"]
        try:
            content = (
                os.readlink(path).encode()
                if record["kind"] == "symlink"
                else path.read_bytes()
            )
            if hashlib.sha256(content).hexdigest() != record["sha256"]:
                skipped.append(record["path"])
                continue
            if (
                record["kept"]
                and digest(root / record["kept"]) != record["kept_sha256"]
            ):
                skipped.append(record["path"])
                continue
            path.unlink()
            removed.append(record["path"])
            parents.update(p for p in path.parents if p != root and root in p.parents)
        except OSError:
            skipped.append(record["path"])
    # Ne retirer que les dossiers devenus vides, jamais un fichier apparu entre-temps.
    for path in sorted(parents, key=lambda p: len(p.parts), reverse=True):
        if path in (root / "data", root / "dist") or "sources" in path.parts:
            continue
        try:
            path.rmdir()
        except OSError:
            pass
    summary.update(
        archive=str(archive),
        archive_bytes=archive.stat().st_size,
        removed_files=len(removed),
        skipped=skipped,
        after={name: size(root / name) for name in ("data", "dist")},
        dist_entries=len(list(root.joinpath("dist").iterdir())),
    )
    receipt = archive.with_suffix(".json")
    receipt.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    archive_dir = args.archive_dir or args.workspace.resolve().parent / (
        args.workspace.name + "-archives"
    )
    print(
        json.dumps(
            compact(args.workspace, archive_dir, args.apply),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
