"""Calendrier public national jusqu’à J+3, distinct des historiques de résultats."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from zoneinfo import ZoneInfo

from .europe import archive
from .workspace import atomic_write, timestamp, utcnow

LEAGUES = {
    "F1": "fra.1", "F2": "fra.2", "E0": "eng.1", "E1": "eng.2",
    "E2": "eng.3", "E3": "eng.4", "EC": "eng.5", "D1": "ger.1",
    "D2": "ger.2", "I1": "ita.1", "I2": "ita.2", "SP1": "esp.1",
    "SP2": "esp.2", "N1": "ned.1", "B1": "bel.1", "P1": "por.1",
    "T1": "tur.1", "G1": "gre.1", "SC0": "sco.1", "SC1": "sco.2",
    "SC2": "sco.3", "SC3": "sco.4",
}


def sync_domestic_calendar(ws, codes=None):
    from .domestic_form import ALIASES, normalized
    from .identity import register_matches, team_resolver

    codes = list(LEAGUES) if codes is None else list(codes)
    if not codes or any(code not in LEAGUES for code in codes):
        raise ValueError("Championnat national inconnu.")
    now = utcnow()
    zone = ZoneInfo(ws.config.get("coaching", {}).get("timezone", "Europe/Paris"))
    today = now.astimezone(zone).date()
    end = today + timedelta(days=3)
    months = list(dict.fromkeys((today.strftime("%Y%m"), end.strftime("%Y%m"))))
    path = ws.path("data/domestic-calendar.json")
    previous = json.loads(path.read_text()) if path.exists() else {"matches": [], "sources": {}}

    def collect(code):
        try:
            rows, rejected = [], []
            for month in months:
                part = archive(ws, code, month, slug=LEAGUES[code])
                rows.extend(part["matches"])
                rejected.extend(part["rejected"])
            aliases = {name.upper(): target for name, target in ALIASES.get(code, {}).items()}
            resolve = team_resolver(ws, code)
            selected, seen = [], set()
            for row in rows:
                kickoff = timestamp(row["kickoff"])
                if kickoff <= now or kickoff.astimezone(zone).date() > end:
                    continue
                if row["event_id"] in seen:
                    continue
                seen.add(row["event_id"])
                for field in ("home", "away"):
                    name = row[field]
                    target = aliases.get(name.upper(), name)
                    if resolve(name) == normalized(name) and resolve(name) != resolve(target):
                        row["provider_" + field] = name
                        row[field] = target
                selected.append(row)
            return code, selected, {"status": "ok", "matches": len(selected),
                                    "rejected": len(rejected), "collected_at": now.isoformat()}
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return code, None, {"status": "error", "message": str(exc), "previous_preserved": True,
                                "attempted_at": now.isoformat()}

    # Lectures publiques bornées ; les écritures d’identité restent séquentielles.
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(collect, codes))
    matches = previous["matches"]
    statuses = dict(previous.get("sources", {}))
    incoming = []
    for code, rows, status in outcomes:
        statuses[code] = status
        if rows is not None:
            matches = [row for row in matches if row["division"] != code]
            incoming.extend(rows)
    if incoming:
        enriched = register_matches(ws, {"collected_at": now.isoformat(), "matches": incoming})
        matches.extend(enriched["matches"])
    result = {"collected_at": now.isoformat(), "start": today.isoformat(), "end": end.isoformat(),
              "timezone": str(zone), "matches": matches, "sources": statuses,
              "notice": "Calendrier national ESPN jusqu’à J+3. Heures confirmées uniquement ; cotes indicatives, aucune simulation autorisée."}
    atomic_write(path, json.dumps(result, ensure_ascii=False, indent=2))
    return {"matches": sum(status.get("matches", 0) for _, _, status in outcomes),
            "sources": statuses, "start": result["start"], "end": result["end"], "notice": result["notice"]}
