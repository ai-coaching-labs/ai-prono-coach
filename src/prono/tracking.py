"""Prévisions gelées avant match et résultats sourcés ; aucun journal de mises parallèle."""

import hashlib
import json
import threading
from collections import defaultdict
from datetime import timedelta
from .workspace import utcnow, timestamp, read_record, write_record_once, atomic_write
from .identity import pair
from .model import load_history
from .metrics import performance, market_comparison


def forecasts(ws):
    return [read_record(p) for p in sorted(ws.path("analyses").glob("forecast-*.md"))]


def capture(ws, now=None, league="all"):
    from .pronos import selections
    from .leagues import league_workspace

    live_clock = now is None
    now = now or utcnow()
    added = 0
    seen = 0
    issues = []
    digests = {}
    configs = {}
    for period in ("today", "next3"):
        selection = selections(ws, period, league, now=now)
        issues.extend(selection.get("issues", []))
        for row in selection["matches"]:
            f, m = row["fixture"], row["model"]
            if (
                not m.get("available")
                or row.get("outcome") is None
                or timestamp(f["kickoff"]) <= now
            ):
                continue
            if timestamp(m["as_of"]) > now or timestamp(m["as_of"]) >= timestamp(
                f["kickoff"]
            ):
                continue
            division = row["division"]
            ident = hashlib.sha256(
                (
                    division
                    + "|"
                    + f["event_id"]
                    + "|"
                    + f["kickoff"]
                    + "|"
                    + m["model"]
                ).encode()
            ).hexdigest()[:32]
            if division not in digests:
                child = league_workspace(ws, division)
                p = child.path("data/history.csv")
                digests[division] = (
                    hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
                )
                configs[division] = child.config["model"]
            recorded_at = utcnow() if live_clock else now
            if timestamp(f["kickoff"]) <= recorded_at:
                continue
            record = {
                "id": ident,
                "created_at": recorded_at.isoformat(),
                "event_id": f["event_id"],
                "division": division,
                "pair": list(pair(ws, division, f)),
                "fixture": f,
                "model": m,
                "outcome": row["outcome"],
                "probabilities": m["probabilities"],
                "paper_status": row["status"],
                "reasons": row["reasons"],
                "synthetic": row["synthetic"],
                "history_sha256": digests[division],
                "model_config": configs[division],
                "mode": "forecast_observation",
            }
            if write_record_once(
                ws.path("analyses/forecast-" + ident + ".md"), "forecast", record
            ):
                added += 1
            seen += 1
    return {"added": added, "eligible": seen, "issues": issues}


def reconcile(ws, now=None):
    from .leagues import league_workspace

    now = now or utcnow()
    settled = 0
    rescheduled = 0
    conflicts = []
    histories = {}
    registry_path = ws.path("data/match-registry.json")
    registry = (
        json.loads(registry_path.read_text()).get("matches", {})
        if registry_path.exists()
        else {}
    )
    for f in forecasts(ws):
        path = ws.path("analyses/outcome-" + f["id"] + ".md")
        if path.exists():
            continue
        scheduled = registry.get(f["event_id"])
        if scheduled and timestamp(scheduled["kickoff"]) != timestamp(
            f["fixture"]["kickoff"]
        ):
            record = {
                "forecast_id": f["id"],
                "status": "rescheduled",
                "observed_at": now.isoformat(),
                "original_kickoff": f["fixture"]["kickoff"],
                "kickoff": scheduled["kickoff"],
                "notice": "Prévision précédente conservée ; exclue du bilan, une nouvelle prévision est nécessaire.",
            }
            if write_record_once(path, "forecast_outcome", record):
                rescheduled += 1
            continue
        if timestamp(f["fixture"]["kickoff"]) >= now:
            continue
        if f["division"] not in histories:
            index = defaultdict(list)
            try:
                for row in load_history(
                    league_workspace(ws, f["division"]).path("data/history.csv")
                ):
                    if timestamp(row["result_known_at"]) <= now:
                        index[
                            (pair(ws, f["division"], row), timestamp(row["kickoff"]))
                        ].append(row)
            except (ValueError, OSError) as exc:
                conflicts.append({"division": f["division"], "reason": str(exc)})
            histories[f["division"]] = index
        matches = histories[f["division"]].get(
            (tuple(f["pair"]), timestamp(f["fixture"]["kickoff"])), []
        )
        if len(matches) != 1:
            if len(matches) > 1:
                conflicts.append(
                    {"id": f["id"], "reason": "Résultats contradictoires ou dupliqués."}
                )
            continue
        r = matches[0]
        if timestamp(f["created_at"]) >= timestamp(r["kickoff"]):
            conflicts.append(
                {
                    "id": f["id"],
                    "reason": "Prévision enregistrée après le début du match.",
                }
            )
            continue
        actual = (
            "home"
            if r["home_goals"] > r["away_goals"]
            else "away" if r["away_goals"] > r["home_goals"] else "draw"
        )
        record = {
            "forecast_id": f["id"],
            "status": "settled",
            "observed_at": now.isoformat(),
            "actual": actual,
            "home_goals": r["home_goals"],
            "away_goals": r["away_goals"],
            "source": r["source"],
            "result_known_at": r["result_known_at"],
            "event_id": r["event_id"],
        }
        if write_record_once(path, "forecast_outcome", record):
            settled += 1
    return {"settled": settled, "rescheduled": rescheduled, "conflicts": conflicts}


def tracking_summary(ws, league="all", query="", include_synthetic=False):
    rows = []
    for f in forecasts(ws):
        if league != "all" and f["division"] != league:
            continue
        if (
            query.casefold()
            not in (f["fixture"]["home"] + " " + f["fixture"]["away"]).casefold()
        ):
            continue
        if f["synthetic"] and not include_synthetic:
            continue
        p = ws.path("analyses/outcome-" + f["id"] + ".md")
        result = read_record(p) if p.exists() else None
        rows.append(
            {**f, "result": result, "status": result["status"] if result else "pending"}
        )
    rows.sort(key=lambda f: timestamp(f["fixture"]["kickoff"]), reverse=True)
    settled = [
        {**r, "actual": r["result"]["actual"]} for r in rows if r["status"] == "settled"
    ]
    by_league = {
        code: performance(
            [
                {"probabilities": r["probabilities"], "actual": r["result"]["actual"]}
                for r in rows
                if r["division"] == code and r["status"] == "settled"
            ]
        )
        for code in sorted({r["division"] for r in rows})
    }
    minimum = ws.config.get("tracking", {}).get("min_settled_before_model_review", 300)
    if type(minimum) is not int or minimum < 1:
        raise ValueError("Jalon de revue du modèle invalide.")
    review_count = sum(not r.get("synthetic", False) for r in settled)
    review = {
        "minimum_settled": minimum,
        "settled": review_count,
        "ready_for_review": review_count >= minimum,
        "production_model": "poisson-baseline-v1",
        "automatic_promotion": False,
        "notice": "Conserver la baseline jusqu’au jalon de prévisions réglées, puis demander une revue explicite. Ce jalon ne prouve ni calibration ni rentabilité.",
    }
    return {
        "model_review": review,
        "captured": len(rows),
        "pending": sum(r["status"] == "pending" for r in rows),
        "rescheduled": sum(r["status"] == "rescheduled" for r in rows),
        "performance": performance(settled),
        "market_comparison": market_comparison(
            settled, float(ws.config["data"]["max_odds_age_hours"])
        ),
        "by_league": by_league,
        "matches": rows,
        "notice": "Suivi de prévisions réellement archivées avant match. Aucun ROI ni mise calculés pour ces observations.",
    }


def refresh_due_results(ws, now=None):
    """Résultats publics des seuls matchs suivis : au plus un essai par championnat/heure."""
    from .leagues import league_workspace
    from .history_import import sync_history

    now = now or utcnow()
    settings = ws.config.get("tracking", {})
    if not settings.get("auto_refresh_results", True):
        return {"enabled": False, "imports": []}
    path = ws.path("data/result-refresh-status.json")
    state = json.loads(path.read_text()) if path.exists() else {}
    due = defaultdict(set)
    for f in forecasts(ws):
        kickoff = timestamp(f["fixture"]["kickoff"])
        if (
            f["synthetic"]
            or ws.path("analyses/outcome-" + f["id"] + ".md").exists()
            or kickoff > now - timedelta(hours=3)
        ):
            continue
        # Revoir les reports non résolus une fois par jour après une semaine.
        delay = max(60, int(settings.get("result_refresh_minutes", 60)))
        if now - kickoff > timedelta(days=7):
            delay = max(delay, 1440)
        previous = state.get(f["division"], {}).get("attempted_at")
        if previous and now - timestamp(previous) < timedelta(minutes=delay):
            continue
        year = kickoff.year if kickoff.month >= 7 else kickoff.year - 1
        due[f["division"]].add(f"{year%100:02d}{(year+1)%100:02d}")
    updates = []
    for division, seasons in due.items():
        state[division] = {"attempted_at": now.isoformat(), "status": "running"}
        atomic_write(path, json.dumps(state, indent=2))
        try:
            result = sync_history(league_workspace(ws, division), sorted(seasons))
            state[division].update(status="ok", added=result["added"])
        except (ValueError, OSError) as exc:
            state[division].update(status="error", error=str(exc))
        updates.append({"division": division, **state[division]})
        atomic_write(path, json.dumps(state, ensure_ascii=False, indent=2))
    return {"enabled": True, "imports": updates}


def tick(ws, refresh=False):
    before = reconcile(ws)
    imported = refresh_due_results(ws) if refresh else {"enabled": False, "imports": []}
    after = (
        reconcile(ws)
        if imported["imports"]
        else {"settled": 0, "rescheduled": 0, "conflicts": []}
    )
    captured = capture(ws)
    result = {
        "at": utcnow().isoformat(),
        "captured": captured,
        "results": {
            "settled": before["settled"] + after["settled"],
            "rescheduled": before["rescheduled"] + after["rescheduled"],
            "conflicts": before["conflicts"] + after["conflicts"],
        },
        "refresh": imported,
    }
    atomic_write(
        ws.path("data/tracking-status.json"),
        json.dumps(result, ensure_ascii=False, indent=2),
    )
    return result


def start_worker(ws, operation_lock):
    stop = threading.Event()

    def work():
        interval = max(
            60, int(ws.config.get("tracking", {}).get("interval_seconds", 300))
        )
        while not stop.is_set():
            if operation_lock.acquire(blocking=False):
                try:
                    tick(ws, refresh=True)
                except Exception as exc:
                    atomic_write(
                        ws.path("data/tracking-status.json"),
                        json.dumps(
                            {
                                "at": utcnow().isoformat(),
                                "error": (
                                    str(exc)
                                    if isinstance(exc, (ValueError, OSError))
                                    else "Erreur du suivi automatique."
                                ),
                            }
                        ),
                    )
                finally:
                    operation_lock.release()
            stop.wait(interval)

    if ws.config.get("tracking", {}).get("enabled", True):
        threading.Thread(
            target=work, name="prono-forecast-tracking", daemon=True
        ).start()
    return stop
