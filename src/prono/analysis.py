import hashlib
import json
from .model import load_history, predict, compare, OUTCOMES, HistoryWindow, predict_rows
from .workspace import utcnow, timestamp, number, write_record


def validate_fixture(f):
    for key in ("event_id", "home", "away", "source", "bookmaker"):
        if not isinstance(f.get(key), str) or not f[key].strip():
            raise ValueError(f"Champ du match absent : {key}")
    if f["home"] == f["away"]:
        raise ValueError("Équipes identiques.")
    kickoff, quoted = timestamp(f["kickoff"]), timestamp(f["quoted_at"])
    if quoted >= kickoff:
        raise ValueError("Seules les cotes d'avant-match sont supportées.")
    for k in OUTCOMES:
        number(f["odds"][k], 1.000001)
    return f


def fixtures(ws):
    path = ws.path("data/fixtures.json")
    if not path.exists():
        return []
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError("fixtures.json doit contenir une liste.")
    return [validate_fixture(f) for f in rows]


def analyze(ws, event_id, now=None):
    now = now or utcnow()
    matches = [f for f in fixtures(ws) if f["event_id"] == event_id]
    if len(matches) != 1:
        raise ValueError(
            "Identifiant absent ou ambigu : prono fixtures pour lister les matchs."
        )
    f = matches[0]
    kickoff, quoted = timestamp(f["kickoff"]), timestamp(f["quoted_at"])
    if kickoff <= now:
        raise ValueError(
            "Match déjà commencé : les analyses sont pré-match uniquement."
        )
    if quoted > now:
        raise ValueError("Cote horodatée dans le futur.")
    age = (now - quoted).total_seconds() / 3600
    model = predict(
        load_history(ws.path("data/history.csv")),
        f["home"],
        f["away"],
        quoted,
        ws.config["model"],
    )
    stale = age > float(ws.config["data"]["max_odds_age_hours"])
    result = {
        "event_id": event_id,
        "created_at": now.isoformat(),
        "fixture": f,
        "odds_age_hours": age,
        "model": model,
        "status": (
            "stale_odds"
            if stale
            else "analysis_only" if model["available"] else "insufficient_data"
        ),
        "decision": "Observation uniquement — aucune mise réelle recommandée.",
        "paper_only": True,
    }
    if model["available"]:
        result["comparison"] = compare(model["probabilities"], f["odds"])
    return result


def save_analysis(ws, result):
    digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[
        :16
    ]
    path = ws.path(f"analyses/{digest}.md")
    write_record(
        path,
        "analysis",
        result,
        "Les écarts et espérances sont des estimations du modèle, pas des preuves de value.\nLes cotes des trois issues proviennent du même bookmaker et du même instant.",
    )
    return path


def backtest(ws, now=None):
    now = now or utcnow()
    history = load_history(ws.path("data/history.csv"))
    window = HistoryWindow(history)
    logs, squared, losses, baseline_squared = [], [], [], []
    for row in window.rows:
        cutoff = window.kickoff_times[id(row)]
        eligible = window.eligible(cutoff, ws.config["model"]["max_history_days"])
        forecast = predict_rows(
            eligible,
            row["home"],
            row["away"],
            cutoff,
            ws.config["model"],
            kickoff_times=window.kickoff_times,
        )
        if not forecast["available"]:
            continue
        actual = (
            "home"
            if row["home_goals"] > row["away_goals"]
            else "away" if row["home_goals"] < row["away_goals"] else "draw"
        )
        p = forecast["probabilities"]
        squared.append(sum((p[k] - (1 if k == actual else 0)) ** 2 for k in OUTCOMES))
        baseline_squared.append(
            sum((1 / 3 - (1 if k == actual else 0)) ** 2 for k in OUTCOMES)
        )
        import math

        losses.append(-math.log(max(p[actual], 1e-15)))
        logs.append(
            {
                "event_id": row["event_id"],
                "kickoff": row["kickoff"],
                "actual": actual,
                "probabilities": p,
            }
        )
    n = len(logs)
    from .market_evaluation import historical_quotes, compare_historical_market
    from .leagues import division_for
    from .identity import team_resolver
    from .tracking import forecasts

    division = division_for(ws)
    quotes = historical_quotes(
        ws, [f for f in forecasts(ws) if f["division"] == division]
    )
    market = compare_historical_market(
        ws,
        window,
        [
            r
            for r in window.rows
            if timestamp(r["kickoff"]) < now and timestamp(r["result_known_at"]) <= now
        ],
        {"poisson-baseline-v1": {}},
        "observed",
        now,
        quotes,
        team_resolver(ws, division),
    )
    return {
        "market_comparison": market,
        "evaluated": n,
        "skipped": len(history) - n,
        "brier_multiclass": sum(squared) / n if n else None,
        "log_loss": sum(losses) / n if n else None,
        "uniform_baseline_brier": sum(baseline_squared) / n if n else None,
        "method": "walk-forward strict : seuls les résultats connus avant chaque coup d'envoi",
        "profitability": "Non évaluée : les scores probabilistes ne mesurent pas le rendement d’une stratégie de pari.",
        "predictions": logs,
    }
