"""Pré-tri de toute la période par Python ; pas un optimiseur de tickets ou de mises."""

from .workspace import timestamp, number


def validate_count(value):
    if type(value) is not int or not 1 <= value <= 15:
        raise ValueError("Choisir de 1 à 15 matchs à approfondir.")
    return value


def validate_event_ids(event_ids, event_id=None):
    if event_ids is None:
        return None
    if event_id or not isinstance(event_ids, list) or not 1 <= len(event_ids) <= 15:
        raise ValueError("Choisir de 1 à 15 matchs manuellement, sans sélection unique simultanée.")
    if any(not isinstance(i, str) or not i.strip() or len(i) > 100 for i in event_ids):
        raise ValueError("Identifiants de matchs invalides.")
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("Un match ne peut être sélectionné deux fois.")
    return list(event_ids)


def key(row):
    return (row["division"], row["fixture"]["event_id"])


def rank_matches(rows, config, as_of, count=3, event_id=None, event_ids=None):
    count = validate_count(count)
    event_ids = validate_event_ids(event_ids, event_id)
    manual_ids = event_ids or ([event_id] if event_id else [])
    now = timestamp(as_of)
    threshold = number(config.get("min_pick_probability", 0.50), 0, 1)
    gap_min = number(config.get("min_probability_gap", 0.10), 0, 1)
    recent_min = int(config.get("min_recent_matches_per_team", 8))
    max_age = int(config.get("max_team_history_age_days", 180))
    if recent_min < 1 or max_age < 1:
        raise ValueError("Critères de sélection invalides.")
    audits = []
    eligible = []
    for row in rows:
        f, m = row["fixture"], row["model"]
        pick = row["outcome"]
        reasons = []
        p = None
        gap = None
        recent = None
        ev = None
        sample_period = m.get("sample_period") or {}
        audit = {
            "event_id": f["event_id"],
            "division": row["division"],
            "match": f["home"] + " / " + f["away"],
            "kickoff": f["kickoff"],
            "model_pick": pick,
            "synthetic": row.get("synthetic", False),
            "selected": False,
            "rank": None,
        }
        if not m.get("available") or pick is None:
            reasons.append(m.get("reason") or "Aucun choix du modèle.")
        else:
            probabilities = m.get("probabilities", {})
            try:
                if set(probabilities) != {"home", "draw", "away"}:
                    raise ValueError()
                values = {k: number(v, 0, 1) for k, v in probabilities.items()}
                if abs(sum(values.values()) - 1) > 1e-6 or pick not in values:
                    raise ValueError()
                ranked = sorted(values, key=values.get, reverse=True)
                if (
                    pick != ranked[0]
                    or abs(values[ranked[0]] - values[ranked[1]]) < 1e-12
                ):
                    raise ValueError()
                p = values[pick]
                gap = p - values[ranked[1]]
            except (ValueError, TypeError):
                reasons.append("Probabilités ou choix du modèle invalides.")
            if p is not None:
                if p < threshold:
                    reasons.append(
                        f"Choix à {100*p:.1f} %, sous le seuil de {100*threshold:.0f} %."
                    )
                if gap < gap_min:
                    reasons.append(
                        f"Écart entre les deux premières issues inférieur à {100*gap_min:.0f} points."
                    )
            counts = [sample_period.get(k + "_recent") for k in ("home", "away")]
            if sample_period.get("recent_days") != 730 or any(
                type(n) is not int or n < 0 for n in counts
            ):
                reasons.append("Échantillons récents indisponibles.")
            else:
                recent = min(counts)
                if recent < recent_min:
                    reasons.append(
                        f"Moins de {recent_min} matchs sur deux ans pour au moins une équipe ({counts[0]} / {counts[1]})."
                    )
            for side in ("home", "away"):
                latest = sample_period.get(side + "_latest")
                if not latest:
                    reasons.append(
                        "Date du dernier résultat de chaque équipe indisponible."
                    )
                    break
                age = (now - timestamp(latest)).total_seconds() / 86400
                if not 0 <= age <= max_age:
                    reasons.append(
                        f'Dernier match historique de l’équipe {"à domicile" if side=="home" else "à l’extérieur"} trop ancien ou futur.'
                    )
                    break
        comparison = row.get("comparison")
        if row["status"] == "candidate" and f.get("quoted_at") and comparison:
            ev = number(comparison["expected_return_per_unit"])
            if ev <= 0:
                ev = None
        audit.update(
            pick_probability=p,
            probability_gap=gap,
            recent_min=recent,
            expected_return_per_unit=ev,
            recent_home=sample_period.get("home_recent"),
            recent_away=sample_period.get("away_recent"),
            prices=[
                {"bookmaker": o["bookmaker"], "odds": o["odds"][pick]}
                for o in f.get("offers", [])
                if pick in o.get("odds", {})
            ],
            category="paper_candidate" if ev is not None else "model_observation",
            eligible=not reasons,
            exclusions=reasons,
        )
        audits.append(audit)
        if not reasons:
            eligible.append(audit)
    # Aucun score composite ni pourcentage de confiance : ordre explicite et déterministe.
    eligible.sort(
        key=lambda a: (
            -a["pick_probability"],
            -a["probability_gap"],
            -a["recent_min"],
            timestamp(a["kickoff"]),
            a["division"],
            a["event_id"],
        )
    )
    for rank, a in enumerate(eligible, 1):
        a["rank"] = rank
    selected = (
        [a for a in audits if a["event_id"] in manual_ids]
        if manual_ids
        else eligible[:count]
    )
    if manual_ids and any(sum(a["event_id"] == i for a in selected) != 1 for i in manual_ids):
        raise ValueError("Match manuel absent ou ambigu dans cette période.")
    if any(timestamp(a["kickoff"]) <= now for a in selected) and manual_ids:
        raise ValueError("Un match choisi a déjà commencé ; analyse pré-match indisponible.")
    for a in selected:
        a["selected"] = True
        a["selection_reason"] = (
            "Choix manuel ; critères automatiques affichés pour information."
            if manual_ids
            else (
                "Observation : probabilité la plus élevée parmi les choix admissibles ; départage par écart et échantillon récent."
            )
        )
    ordered = eligible + sorted(
        [a for a in audits if not a["eligible"]],
        key=lambda a: (timestamp(a["kickoff"]), a["division"], a["event_id"]),
    )
    report = {
        "policy": "shortlist-v2",
        "mode": "manual" if manual_ids else "automatic",
        "scanned": len(rows),
        "calculable": sum(
            r["model"].get("available", False) and r["outcome"] is not None
            for r in rows
        ),
        "eligible": len(eligible),
        "requested": len(manual_ids) if manual_ids else count,
        "selected": len(selected),
        "rows": ordered,
        "criteria": {
            "min_pick_probability": threshold,
            "min_probability_gap": gap_min,
            "min_recent_matches_per_team": recent_min,
            "recent_days": 730,
            "max_team_history_age_days": max_age,
        },
        "method": "Toute la période chargée est examinée avant toute limite d’affichage. Filtre sur probabilité, écart, échantillons récents et dernière rencontre connue. Ordre descriptif par probabilité décroissante, écart, échantillon récent ; aucune priorité liée aux cotes ou à l’espérance théorique. Heure du match seulement pour départager.",
        "notice": "Pré-tri statistique à faire vérifier par les spécialistes. Probabilités non calibrées. Les cotes indicatives ne permettent pas de classer la rentabilité. Aucun combiné optimisé ni probabilité jointe calculés.",
    }
    lookup = {key(r): r for r in rows}
    return [lookup[(a["division"], a["event_id"])] for a in ordered], report
