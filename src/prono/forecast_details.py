"""Lectures descriptives de la baseline existante, sans ajustement du modèle."""

import math
from .model import poisson
from .workspace import number


def forecast_details(model):
    if not model.get("available"):
        return None
    if model.get("model") != "poisson-baseline-v1":
        return None
    rates = model.get("expected_goals")
    if not isinstance(rates, dict):
        return None
    home, away = (number(rates[k], 0.05, 8) for k in ("home", "away"))
    # Même grille 0–40 que les probabilités 1N2 de la baseline.
    scores = [
        {"home": h, "away": a, "probability": poisson(home, h) * poisson(away, a)}
        for h in range(41) for a in range(41)
    ]
    total = sum(row["probability"] for row in scores)
    for row in scores:
        row["probability"] /= total
    scores.sort(key=lambda row: (-row["probability"], row["home"], row["away"]))
    modes = [row for row in scores if math.isclose(
        row["probability"], scores[0]["probability"], rel_tol=1e-12, abs_tol=0
    )]
    by_outcome = {}
    for outcome in ("home", "draw", "away"):
        candidates = [row for row in scores if (
            "home" if row["home"] > row["away"] else "away" if row["away"] > row["home"] else "draw"
        ) == outcome]
        by_outcome[outcome] = [row for row in candidates if math.isclose(
            row["probability"], candidates[0]["probability"], rel_tol=1e-12, abs_tol=0
        )]
    yes = sum(row["probability"] for row in scores if row["home"] > 0 and row["away"] > 0)
    no = 1 - yes
    return {
        "model": "poisson-baseline-v1",
        "most_likely_scores": modes,
        "scores_by_outcome": by_outcome,
        "both_teams_score": {
            "yes": yes, "no": no,
            "pick": None if math.isclose(yes, no, abs_tol=1e-12, rel_tol=0) else "yes" if yes > no else "no",
        },
        "notice": "Scores et deux équipes marquent : lectures exploratoires non calibrées du même Poisson. scores_by_outcome donne les scores les plus probables parmi ceux compatibles avec chaque issue ; leurs probabilités restent absolues, non conditionnelles. Le score modal global peut différer du choix 1N2 agrégé. Aucune cote de ces marchés ni espérance associée n’est fournie.",
    }
