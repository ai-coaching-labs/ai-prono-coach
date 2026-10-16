"""Réutiliser aussi les captures datées des anciennes versions."""

import json


def existing_text_capture(path, prefix, content, raw_bytes=None):
    if path.exists():
        return path
    expected = content.encode("utf-8")
    for candidate in sorted(path.parent.glob(prefix + "*.csv")):
        if candidate.is_symlink() or candidate.name.endswith(".raw.csv"):
            continue
        if candidate.read_bytes() != expected:
            continue
        raw = candidate.with_suffix(".raw.csv")
        if raw_bytes is None and raw.exists():
            continue
        if raw_bytes is not None and (
            not raw.exists() or raw.read_bytes() != raw_bytes
        ):
            continue
        return candidate
    return path


def existing_json_capture(path, prefix, source, data):
    if path.exists():
        return path
    for candidate in sorted(path.parent.glob(prefix + "*.json")):
        if candidate.is_symlink():
            continue
        try:
            record = json.loads(candidate.read_text())
        except (OSError, ValueError):
            continue
        if record.get("source") == source and record.get("data") == data:
            return candidate
    return path
