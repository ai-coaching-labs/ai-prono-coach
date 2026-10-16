"""Cotes publiques indicatives, séparées des cotes horodatées analysables."""

import csv
import hashlib
import io
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from .history_import import fetch_csv
from .leagues import LEAGUES
from .workspace import utcnow, timestamp, number, atomic_write

SOURCE = "https://www.football-data.co.uk/fixtures.csv"
BOOKMAKERS = [
    ("B365", "Bet365"),
    ("BW", "Bwin"),
    ("PS", "Pinnacle"),
    ("WH", "William Hill"),
    ("BV", "BetVictor"),
]


def public_calendar(ws):
    """Deux captures indépendantes ; un refresh national ne supprime pas les coupes UEFA."""
    combined = {"matches": [], "datasets": []}
    for filename, label in [
        ("market-watch.json", "Championnats · Football-Data"),
        ("domestic-calendar.json", "Championnats J+3 · ESPN"),
        ("europe-watch.json", "Coupes d’Europe · ESPN"),
    ]:
        path = ws.path("data/" + filename)
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        combined["matches"].extend(data.get("matches", []))
        combined["datasets"].append(
            {"label": label, "collected_at": data.get("collected_at")}
        )
        if filename == "europe-watch.json":
            combined["europe_sources"] = data.get("sources", {})
        if filename == "domestic-calendar.json":
            combined["domestic_sources"] = data.get("sources", {})
        if filename == "market-watch.json":
            combined.update(
                {k: v for k, v in data.items() if k not in ("matches", "datasets")}
            )
    # Une rencontre présente dans les deux calendriers reste une seule fiche.
    from .identity import team_resolver
    resolvers, unique = {}, {}
    for row in combined["matches"]:
        code = row["division"]
        if code not in resolvers:
            resolvers[code] = team_resolver(ws, code)
        resolve = resolvers[code]
        key = (code, resolve(row["home"]), resolve(row["away"]), timestamp(row["kickoff"]))
        if key not in unique:
            unique[key] = row
    combined["matches"] = list(unique.values())
    return combined


def normalize_markets(content, collected_at):
    collected_at = timestamp(collected_at).isoformat()
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    if not {"Div", "Date", "Time", "HomeTeam", "AwayTeam"}.issubset(
        reader.fieldnames or []
    ):
        raise ValueError("Format du calendrier public invalide.")
    rows, rejected, seen = [], [], set()
    for line, raw in enumerate(reader, 2):
        if not any(raw.values()):
            continue
        if raw["Div"] not in LEAGUES:
            rejected.append({"line": line, "reason": "Compétition hors catalogue"})
            continue
        try:
            kickoff = datetime.strptime(
                raw["Date"] + " " + raw["Time"], "%d/%m/%Y %H:%M"
            ).replace(tzinfo=ZoneInfo("Europe/London"))
            home, away = raw["HomeTeam"].strip(), raw["AwayTeam"].strip()
            if not home or not away or home == away:
                raise ValueError("Équipes invalides")
            offers = []
            for prefix, name in BOOKMAKERS:
                values = [raw.get(prefix + suffix, "") for suffix in ("H", "D", "A")]
                if all(values):
                    try:
                        offers.append(
                            {
                                "bookmaker": name,
                                "odds": dict(
                                    zip(
                                        ("home", "draw", "away"),
                                        [number(v, 1.000001) for v in values],
                                    )
                                ),
                            }
                        )
                    except ValueError:
                        rejected.append(
                            {"line": line, "reason": "Triplet invalide : " + name}
                        )
            ident = hashlib.sha256(
                f"{raw['Div']}|{kickoff.isoformat()}|{home}|{away}".encode()
            ).hexdigest()[:20]
            if ident in seen:
                raise ValueError("Rencontre dupliquée")
            seen.add(ident)
            rows.append(
                {
                    "event_id": "watch-" + ident,
                    "division": raw["Div"],
                    "home": home,
                    "away": away,
                    "kickoff": timestamp(kickoff.isoformat()).isoformat(),
                    "offers": offers,
                    "source": SOURCE,
                    "collected_at": collected_at,
                    "quoted_at": None,
                    "status": "unverified_quote_time",
                    "analysis_eligible": False,
                }
            )
        except (ValueError, TypeError) as exc:
            rejected.append({"line": line, "reason": str(exc)})
    return {
        "collected_at": collected_at,
        "source": SOURCE,
        "matches": rows,
        "rejected": rejected,
        "notice": "Cotes indicatives : heure exacte de cotation indisponible. Collecte ≠ cotation. Analyse et simulation bloquées pour ces cotes.",
    }


def _sync_football_data(ws):
    content = fetch_csv(SOURCE)  # Un seul téléchargement pour toutes les divisions.
    when = utcnow()
    result = normalize_markets(content, when.isoformat())
    if not result["matches"]:
        raise ValueError("Aucun match public valide : précédent calendrier conservé.")
    digest = hashlib.sha256(content.encode()).hexdigest()
    archive = ws.path(f"data/sources/fixtures-{digest}.csv")
    from .source_archives import existing_text_capture

    archive = existing_text_capture(archive, "fixtures-", content)
    if not archive.exists():
        atomic_write(archive, content)
    from .identity import register_matches, price_changes

    previous_path = ws.path("data/market-watch.json")
    previous = (
        json.loads(previous_path.read_text()).get("matches", [])
        if previous_path.exists()
        else []
    )
    result = register_matches(ws, result)
    result["price_changes"] = price_changes(previous, result["matches"])
    atomic_write(
        ws.path("data/market-watch.json"),
        json.dumps(result, ensure_ascii=False, indent=2),
    )
    summary = {
        "status": "ok",
        "matches": len(result["matches"]),
        "rejected": len(result["rejected"]),
        "offers": sum(len(r["offers"]) for r in result["matches"]),
        "notice": result["notice"],
    }
    return summary


def sync_markets(ws, include_europe=True, include_domestic=True):
    issues = []
    try:
        summary = _sync_football_data(ws)
    except (ValueError, OSError) as exc:
        if not include_europe and not include_domestic:
            raise
        issues.append({"provider": "Football-Data", "message": str(exc), "previous_preserved": True})
        summary = {"matches": 0, "offers": 0, "notice": "Calendriers publics indicatifs."}
    for enabled, provider, name in ((include_domestic, "ESPN national", "domestic"),
                                    (include_europe, "ESPN européen", "europe")):
        if not enabled:
            continue
        try:
            if name == "domestic":
                from .domestic_calendar import sync_domestic_calendar
                part = sync_domestic_calendar(ws)
            else:
                from .europe import sync_europe
                part = sync_europe(ws)
            summary[name] = part
            summary["matches"] += part["matches"]
            summary["offers"] += part.get("offers", 0)
            issues.extend({"provider": provider, "division": code, "message": state.get("message", "Source indisponible.")}
                          for code, state in part.get("sources", {}).items() if state.get("status") == "error")
        except (ValueError, OSError) as exc:
            issues.append({"provider": provider, "message": str(exc), "previous_preserved": True})
    summary["issues"] = issues
    summary["status"] = "partial" if issues else "ok"
    return summary
