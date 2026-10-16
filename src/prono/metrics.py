"""Scores probabilistes et calibration descriptive, calculés sans modèle de langage."""

import math
from .model import OUTCOMES
from .workspace import number


def market_probabilities(fixture, recorded_at, max_odds_age_hours=6):
    """Triplet observé avant match ; aucune date de disponibilité inférée."""
    from .workspace import timestamp

    if not fixture.get("quoted_at"):
        return {"available": False, "reason": "quote_time_unavailable"}
    if not recorded_at:
        return {"available": False, "reason": "quote_knowledge_unavailable"}
    try:
        quoted = timestamp(fixture["quoted_at"])
        recorded = timestamp(recorded_at)
        kickoff = timestamp(fixture["kickoff"])
        if not quoted <= recorded < kickoff:
            raise ValueError("Cote ou observation hors pré-match.")
        if (recorded - quoted).total_seconds() > max_odds_age_hours * 3600:
            return {"available": False, "reason": "stale_odds"}
        if not all(
            isinstance(fixture.get(k), str) and fixture[k].strip()
            for k in ("bookmaker", "source")
        ):
            raise ValueError("Provenance manquante.")
        inverse = {k: 1 / number(fixture["odds"][k], 1.000001) for k in OUTCOMES}
        total = sum(inverse.values())
    except (KeyError, TypeError, ValueError):
        return {"available": False, "reason": "invalid_quote"}
    return {
        "available": True,
        "probabilities": {k: v / total for k, v in inverse.items()},
    }


def market_comparison(rows, max_odds_age_hours=6):
    """Compare les mêmes observations aux cotes figées, jamais à des cotes actuelles."""
    from collections import Counter

    model_rows, market_rows = [], []
    excluded = Counter()
    for row in rows:
        market = market_probabilities(
            row.get("fixture", {}), row.get("created_at"), max_odds_age_hours
        )
        if not market["available"]:
            excluded[market["reason"]] += 1
            continue
        try:
            p = {k: number(row["probabilities"][k], 0, 1) for k in OUTCOMES}
            score(p, row["actual"])
        except (KeyError, TypeError, ValueError):
            excluded["invalid_prediction"] += 1
            continue
        model_rows.append({"probabilities": p, "actual": row["actual"]})
        market_rows.append(
            {"probabilities": market["probabilities"], "actual": row["actual"]}
        )
    model, market = performance(model_rows), performance(market_rows)
    return {
        "evaluated": len(model_rows),
        "excluded": dict(excluded),
        "model": model,
        "market": market,
        "delta_brier": model["brier"] - market["brier"] if model_rows else None,
        "delta_log_loss": (
            model["log_loss"] - market["log_loss"] if model_rows else None
        ),
        "method": "Même sous-échantillon ; cotes du même bookmaker figées avant match, normalisation proportionnelle hors marge.",
        "notice": "Un écart négatif favorise le modèle. Ce marché est celui de la capture, pas une cote de clôture ni une preuve de rentabilité. Cotes non horodatées exclues.",
    }


def score(probabilities, actual):
    if actual not in OUTCOMES:
        raise ValueError("Résultat 1N2 invalide.")
    p = {k: number(probabilities[k], 0, 1) for k in OUTCOMES}
    if abs(sum(p.values()) - 1) > 1e-6:
        raise ValueError("Probabilités non normalisées.")
    return {
        "brier": sum((p[k] - (k == actual)) ** 2 for k in OUTCOMES),
        "log_loss": -math.log(max(p[actual], 1e-15)),
    }


def performance(rows):
    if not rows:
        return {
            "evaluated": 0,
            "brier": None,
            "log_loss": None,
            "accuracy": None,
            "calibration": [],
        }
    scores = [score(r["probabilities"], r["actual"]) for r in rows]
    bins = []
    for outcome in OUTCOMES:
        for b in range(5):
            selected = [
                r for r in rows if min(4, int(r["probabilities"][outcome] * 5)) == b
            ]
            if selected:
                bins.append(
                    {
                        "outcome": outcome,
                        "lower": b / 5,
                        "upper": (b + 1) / 5,
                        "count": len(selected),
                        "mean_probability": sum(
                            r["probabilities"][outcome] for r in selected
                        )
                        / len(selected),
                        "observed_frequency": sum(
                            r["actual"] == outcome for r in selected
                        )
                        / len(selected),
                    }
                )
    return {
        "evaluated": len(rows),
        "brier": sum(s["brier"] for s in scores) / len(rows),
        "log_loss": sum(s["log_loss"] for s in scores) / len(rows),
        "accuracy": sum(
            max(r["probabilities"], key=r["probabilities"].get) == r["actual"]
            for r in rows
        )
        / len(rows),
        "calibration": bins,
        "notice": "Calibration descriptive ; petits groupes instables, aucune probabilité corrigée automatiquement.",
    }
