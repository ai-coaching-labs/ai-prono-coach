"""Référence marché sur les mêmes matchs et à l'instant de disponibilité des cotes."""

import json
from collections import Counter, defaultdict
from .workspace import timestamp
from .metrics import market_probabilities, performance
from .model import predict_rows


def historical_quotes(ws, archived_forecasts=()):
    """Le fichier existant de fixtures peut aussi contenir des cotes historiques datées."""
    path = ws.path("data/fixtures.json")
    fixtures = json.loads(path.read_text()) if path.exists() else []
    if not isinstance(fixtures, list):
        raise ValueError("fixtures.json doit contenir une liste.")
    quotes = [{"fixture": f, "created_at": f.get("collected_at")} for f in fixtures]
    # Un forecast est une preuve d'observation à sa date d'archivage.
    quotes.extend(
        {"fixture": f["fixture"], "created_at": f["created_at"]}
        for f in archived_forecasts
        if not f.get("synthetic", False)
    )
    return quotes


def compare_historical_market(
    ws, window, targets, variants, mode, now, quotes, resolve=lambda x: x
):
    limit = float(ws.config["data"]["max_odds_age_hours"])
    indexed = defaultdict(list)
    rejected = Counter()
    for observation in quotes:
        fixture = observation.get("fixture", {})
        try:
            key = (
                resolve(fixture["home"]),
                resolve(fixture["away"]),
                timestamp(fixture["kickoff"]),
            )
            recorded = (
                timestamp(observation["created_at"])
                if observation.get("created_at")
                else None
            )
        except (KeyError, ValueError, TypeError):
            rejected["invalid_observation"] += 1
            continue
        market = market_probabilities(fixture, observation.get("created_at"), limit)
        if not market["available"]:
            indexed[key].append((None, market["reason"], None, observation))
        elif recorded > now:
            indexed[key].append((None, "future_observation", None, observation))
        else:
            indexed[key].append((recorded, None, market["probabilities"], observation))
    model_rows = {name: [] for name in variants}
    market_rows, samples = [], []
    excluded = Counter()
    for row in targets:
        key = (resolve(row["home"]), resolve(row["away"]), timestamp(row["kickoff"]))
        available = indexed.get(key, [])
        valid = [q for q in available if q[0] is not None]
        if not valid:
            excluded["no_valid_quote"] += 1
            for reason in {q[1] for q in available} or {"quote_unavailable"}:
                rejected[reason] += 1
            continue
        # Dernière observation connue avant match. Bookmaker/source départagent
        # les captures simultanées ; aucun choix a posteriori selon les scores.
        valid.sort(
            key=lambda q: (
                q[0],
                timestamp(q[3]["fixture"]["quoted_at"]),
                q[3]["fixture"]["bookmaker"],
                q[3]["fixture"]["source"],
            )
        )
        recorded, _, probabilities, observation = valid[-1]
        simultaneous = [
            q
            for q in valid
            if q[0] == recorded
            and q[3]["fixture"]["bookmaker"] == observation["fixture"]["bookmaker"]
            and timestamp(q[3]["fixture"]["quoted_at"])
            == timestamp(observation["fixture"]["quoted_at"])
        ]
        if any(
            q[3]["fixture"]["odds"] != observation["fixture"]["odds"]
            for q in simultaneous
        ):
            excluded["conflicting_quotes"] += 1
            continue
        eligible = window.eligible(
            recorded, ws.config["model"]["max_history_days"], mode
        )
        predictions = {
            name: predict_rows(
                eligible,
                row["home"],
                row["away"],
                recorded,
                ws.config["model"],
                kickoff_times=window.kickoff_times,
                **parameters,
            )
            for name, parameters in variants.items()
        }
        if not all(p["available"] for p in predictions.values()):
            excluded["insufficient_history_at_quote"] += 1
            continue
        actual = (
            "home"
            if row["home_goals"] > row["away_goals"]
            else "away" if row["away_goals"] > row["home_goals"] else "draw"
        )
        for name, prediction in predictions.items():
            model_rows[name].append(
                {"probabilities": prediction["probabilities"], "actual": actual}
            )
        market_rows.append({"probabilities": probabilities, "actual": actual})
        samples.append(
            {
                "event_id": row["event_id"],
                "kickoff": row["kickoff"],
                "as_of": recorded.isoformat(),
                "quoted_at": observation["fixture"]["quoted_at"],
                "bookmaker": observation["fixture"]["bookmaker"],
                "source": observation["fixture"]["source"],
            }
        )
    market = performance(market_rows)
    models = {}
    for name, rows in model_rows.items():
        metrics = performance(rows)
        models[name] = {
            **metrics,
            "delta_brier": metrics["brier"] - market["brier"] if rows else None,
            "delta_log_loss": (
                metrics["log_loss"] - market["log_loss"] if rows else None
            ),
        }
    return {
        "evaluated": len(market_rows),
        "target_count": len(targets),
        "excluded": dict(excluded),
        "quote_exclusions": dict(rejected),
        "market": market,
        "models": models,
        "samples": samples,
        "method": "Même sous-échantillon pour les variantes et le marché. Modèles recalculés à la disponibilité documentée des cotes ; normalisation proportionnelle hors marge.",
        "notice": "Un écart négatif favorise le modèle. Cotes sans cotation ou disponibilité pré-match vérifiable exclues. La référence est une capture, pas une clôture de marché. Le mode archives garde ses hypothèses rétrospectives ; aucune preuve de rentabilité.",
    }
