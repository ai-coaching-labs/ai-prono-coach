import json
import os
import re
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Horodatage avec fuseau requis (ex. 2026-10-10T18:00:00Z).")
    return dt.astimezone(timezone.utc)


def number(value, minimum=None, maximum=None):
    import math

    n = float(value)
    if (
        not math.isfinite(n)
        or (minimum is not None and n < minimum)
        or (maximum is not None and n > maximum)
    ):
        raise ValueError(f"Valeur numérique invalide : {value}")
    return n


def merge(a, b):
    out = dict(a)
    for key, value in b.items():
        out[key] = merge(out.get(key, {}), value) if isinstance(value, dict) else value
    return out


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".prono-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_record(path, kind, payload, prose=""):
    record = {"schema_version": 1, "kind": kind, **payload}
    atomic_write(
        path,
        f"# {kind}\n\n```prono\n{json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False)}\n```\n\n{prose}\n",
    )


def write_record_once(path, kind, payload):
    """Création atomique exclusive : un pronostic existant ne peut être remplacé."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": 1, "kind": kind, **payload}
    text = f"# {kind}\n\n```prono\n{json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)}\n```\n"
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".prono-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        try:
            os.link(temp, path)
        except FileExistsError:
            return False
        return True
    finally:
        os.unlink(temp)


def read_record(path):
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(r"```prono\n(.*?)\n```", text, re.S)
    if not match:
        raise ValueError(f"Bloc prono absent : {Path(path).name}")
    record = json.loads(match.group(1))
    if record.get("schema_version") != 1:
        raise ValueError("Version du contrat inconnue.")
    return record


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        config_path = self.root / "config/workspace.toml"
        if not config_path.exists():
            raise ValueError(
                "Workspace absent : exécuter ./install.sh ou prono init depuis le projet."
            )
        self.config = tomllib.loads(config_path.read_text())
        user = self.root / "config/workspace.user.toml"
        if user.exists():
            self.config = merge(self.config, tomllib.loads(user.read_text()))
        paper = self.config["paper"]
        number(paper["starting_balance"], 0.01)
        number(paper["unit"], 0.01)
        number(paper["max_open_exposure"], 0.01)
        model = self.config["model"]
        if (
            int(model["min_matches_per_team"]) < 1
            or int(model["prior_matches"]) < 1
            or int(model["max_history_days"]) < 1
        ):
            raise ValueError("Paramètres du modèle invalides.")
        number(self.config["data"]["max_odds_age_hours"], 0.01)

    def path(self, value):
        return self.root / value

    def records(self, folder):
        return [read_record(p) for p in sorted(self.path(folder).glob("*.md"))]
