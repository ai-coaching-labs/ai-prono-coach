"""Point quotidien local : aucun appel réseau et aucune simulation automatique."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .analysis import fixtures, analyze
from .journal import summary
from .workspace import utcnow, timestamp, write_record


def daily_briefing(ws, now=None, timezone_name=None):
    now = timestamp((now or utcnow()).isoformat())
    name = timezone_name or ws.config.get("coaching", {}).get("timezone", "Europe/Paris")
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Fuseau horaire inconnu : {name}") from exc
    today = now.astimezone(zone).date()
    loaded = fixtures(ws)
    items = []
    for fixture in sorted(loaded, key=lambda f: timestamp(f["kickoff"])):
        kickoff = timestamp(fixture["kickoff"])
        if kickoff.astimezone(zone).date() != today:
            continue
        item = {"fixture": fixture, "kickoff_local": kickoff.astimezone(zone).isoformat(),
                "synthetic": fixture["source"] == "synthetic-demo"}
        if kickoff <= now:
            item.update(status="started", reason="Match déjà commencé : abstention pré-match.")
        elif timestamp(fixture["quoted_at"]) > now:
            item.update(status="future_odds", reason="Cote horodatée dans le futur : abstention.")
        else:
            result = analyze(ws, fixture["event_id"], now=now)
            item.update(status=result["status"], analysis=result)
            reasons = []
            if result["status"] == "stale_odds":
                reasons.append("Cotes périmées : abstention.")
            if not result["model"]["available"]:
                reasons.append(result["model"]["reason"])
            item["reason"] = " ".join(reasons) or "Observation uniquement ; modèle non calibré."
        items.append(item)
    stats = summary(ws)
    unit = float(ws.config["paper"]["unit"])
    capacity = max(0.0, min(stats["available_balance"],
                           float(ws.config["paper"]["max_open_exposure"]) - stats["open_exposure"]))
    actions = []
    if not loaded:
        actions.append("Importer des résultats historiques et des matchs ; aucune synchronisation automatique.")
    elif not items:
        actions.append("Aucun match chargé pour cette journée locale.")
    if any(i["status"] == "stale_odds" for i in items):
        actions.append("Actualiser les cotes par import ou demander explicitement une synchronisation.")
    if any(i["status"] == "insufficient_data" for i in items):
        actions.append("Compléter l'historique et vérifier les noms des équipes.")
    if capacity < unit:
        actions.append("Limite de simulation atteinte : aucune nouvelle entrée fictive possible.")
    return {"created_at": now.isoformat(), "date": today.isoformat(), "timezone": name,
            "paper_only": True, "loaded_count": len(loaded), "today_count": len(items),
            "matches": items, "summary": stats, "remaining_exposure_units": capacity,
            "next_steps": actions, "absences": "indisponibles", "compositions": "indisponibles",
            "notice": "Poisson-baseline-v1 : probabilités non calibrées, aucune rentabilité démontrée. Simulations fictives uniquement."}


def render_briefing(result):
    lines = [f"## Point du {result['date']} — {result['timezone']}", "", result["notice"], "",
             f"Matchs du jour : {result['today_count']}. Matchs chargés : {result['loaded_count']}.",
             f"Solde fictif : {result['summary']['balance']:.2f} unités. Exposition ouverte : {result['summary']['open_exposure']:.2f} unités.", ""]
    for item in result["matches"]:
        f = item["fixture"]
        lines.extend([f"### {f['home']} / {f['away']}", "",
                      f"Coup d'envoi : {item['kickoff_local']}. {item['reason']}",
                      f"Cotes 1N2 : {f['odds']['home']} / {f['odds']['draw']} / {f['odds']['away']}.",
                      f"Source : {f['source']} ; bookmaker : {f['bookmaker']} ; cotation : {f['quoted_at']}."])
        if item["synthetic"]:
            lines.append("Données SYNTHÉTIQUES : démonstration technique uniquement.")
        lines.append("")
    lines.extend(["Absences et compositions : indisponibles.", ""])
    lines.extend(f"- {action}" for action in result["next_steps"])
    return "\n".join(lines)


def save_briefing(ws, result):
    when = timestamp(result["created_at"])
    path = ws.path(f"rapports/{when.strftime('%Y-%m-%d_%H%M%S_%f')}_point.md")
    write_record(path, "daily_briefing", result, render_briefing(result))
    return path
