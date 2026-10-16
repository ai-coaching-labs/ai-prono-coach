"""Sélections de travail pré-match : calcul local, aucun pari ni appel réseau."""

from .presentation import html_fragment
import json
from datetime import timedelta
from zoneinfo import ZoneInfo
from .analysis import fixtures, analyze
from .leagues import LEAGUES, league_workspace
from .model import load_history, predict
from .journal import journal, summary
from .workspace import utcnow, timestamp


def selections(ws, period="today", league="all", query="", now=None):
    now = timestamp((now or utcnow()).isoformat())
    zone = ZoneInfo(ws.config.get("coaching", {}).get("timezone", "Europe/Paris"))
    today = now.astimezone(zone).date()
    if period not in ("today", "next3"):
        raise ValueError("Période attendue : today ou next3.")
    start, end = (
        (today, today)
        if period == "today"
        else (today + timedelta(days=1), today + timedelta(days=3))
    )
    if league != "all" and league not in LEAGUES:
        raise ValueError("Championnat inconnu.")
    codes = list(LEAGUES) if league == "all" else [league]
    from .market_watch import public_calendar

    watch = public_calendar(ws)["matches"]
    rows, issues = ([], [])
    for code in codes:
        try:
            child = league_workspace(ws, code)
            history = load_history(child.path("data/history.csv"))
            verified = fixtures(child)
            stats, entries = (summary(child), journal(child))
        except (ValueError, OSError) as exc:
            issues.append({"division": code, "reason": str(exc)})
            continue
        identity = lambda f: (f["home"], f["away"], timestamp(f["kickoff"]))
        known = {identity(f) for f in verified}
        inputs = [(f, True) for f in verified] + [
            (f, False)
            for f in watch
            if f["division"] == code and identity(f) not in known
        ]
        from .identity import team_resolver

        normalize = team_resolver(ws, code)
        normalized = [
            {**r, "home": normalize(r["home"]), "away": normalize(r["away"])}
            for r in history
        ]
        for fixture, verified_quote in inputs:
            kickoff = timestamp(fixture["kickoff"])
            day = kickoff.astimezone(zone).date()
            if kickoff <= now or not start <= day <= end:
                continue
            if (
                query.casefold()
                not in (fixture["home"] + " " + fixture["away"]).casefold()
            ):
                continue
            reasons, comparison = ([], None)
            if verified_quote:
                try:
                    result = analyze(child, fixture["event_id"], now)
                    model = result["model"]
                    comparison = result.get("comparison")
                    if result["status"] == "stale_odds":
                        reasons.append("Cotes périmées.")
                except ValueError as exc:
                    model = {"available": False}
                    reasons.append(str(exc))
            else:
                model = predict(
                    normalized,
                    normalize(fixture["home"]),
                    normalize(fixture["away"]),
                    now,
                    child.config["model"],
                )
                reasons.append(
                    "Cotes indicatives : simulation fictive non validée, fraîcheur inconnue."
                )
            outcome = None
            if not model["available"]:
                reasons.append(model.get("reason", "Analyse indisponible."))
            else:
                probabilities = model["probabilities"]
                ranked = sorted(probabilities, key=probabilities.get, reverse=True)
                if abs(probabilities[ranked[0]] - probabilities[ranked[1]]) < 1e-12:
                    reasons.append("Issues les plus probables à égalité.")
                else:
                    outcome = ranked[0]
            chosen = next(
                (
                    r
                    for r in (comparison or {}).get("outcomes", [])
                    if r["outcome"] == outcome
                ),
                None,
            )
            if chosen and chosen["expected_return_per_unit"] <= 0:
                reasons.append(
                    "Espérance théorique non positive pour l’issue la plus probable."
                )
            if any((r["event_id"] == fixture["event_id"] for r in entries)):
                reasons.append("Simulation déjà inscrite pour ce match.")
            unit = float(child.config["paper"]["unit"])
            if stats["available_balance"] < unit or stats[
                "open_exposure"
            ] + unit > float(child.config["paper"]["max_open_exposure"]):
                reasons.append("Limite de simulation atteinte.")
            from .leagues import EUROPE

            if code in EUROPE:
                reasons.append(
                    "Coupe d’Europe : baseline exploratoire, validation spécifique encore absente."
                )
            rows.append(
                {
                    "division": code,
                    "fixture": fixture,
                    "kickoff_local": kickoff.astimezone(zone).isoformat(),
                    "model": model,
                    "outcome": outcome,
                    "comparison": chosen,
                    "status": "abstention" if reasons else "candidate",
                    "reasons": reasons,
                    "context_notice": "Avis des agents et compositions à vérifier ; non intégrés à la baseline.",
                    "synthetic": fixture["source"] == "synthetic-demo"
                    or any((r["source"] == "synthetic-demo" for r in history)),
                }
            )
    from .leagues import EUROPE

    if any((r["division"] in EUROPE for r in rows)):
        from .domestic_form import DomesticForm

        domestic = DomesticForm(ws, now.isoformat())
        for row in rows:
            if row["division"] in EUROPE:
                row["domestic_form"] = domestic.match(row["fixture"])
    rows.sort(
        key=lambda r: (r["status"] != "candidate", timestamp(r["fixture"]["kickoff"]))
    )
    return {
        "created_at": now.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": str(zone),
        "period": period,
        "matches": rows,
        "issues": issues,
        "candidates": sum((r["status"] == "candidate" for r in rows)),
        "notice": "Sélections à étudier séparément en fictif, pas un ticket à jouer ensemble. Modèle non calibré ; une espérance positive ne prouve aucun avantage.",
    }


def render(result, link, esc, page_number=1):
    from urllib.parse import urlencode

    labels = {"home": "1 · Domicile", "draw": "N · Nul", "away": "2 · Extérieur"}
    rows = result["matches"]
    pages = max(1, (len(rows) + 17) // 18)
    page_number = min(max(1, page_number), pages)
    content = (
        html_fragment("pronos-fragments.html", "render_div_les_pronos_du_modele")
        + esc(result["start"])
        + " → "
        + esc(result["end"])
        + " · "
        + esc(result["timezone"])
        + html_fragment("pronos-fragments.html", "render_span_markup")
    )
    content += (
        html_fragment("pronos-fragments.html", "render_nav_tabs")
        + "".join(
            (
                html_fragment(
                    "pronos-fragments.html",
                    "render_a_tab_value",
                    value=f"{('chosen' if result['period'] == key else '')}",
                    link=f"{esc(link(horizon=key))}",
                    label=f"{label}",
                )
                for key, label in [
                    ("today", "Aujourd’hui"),
                    ("next3", "Les 3 prochains jours · demain à J+3"),
                ]
            )
        )
        + html_fragment("pronos-fragments.html", "nav_close")
    )
    picks = sum((r["model"]["available"] and r["outcome"] is not None for r in rows))
    content += html_fragment(
        "pronos-fragments.html",
        "render_p_prono_s_calcule_s_rencontre_s_avant_cou",
        picks=f"{picks}",
        len=f"{len(rows)}",
        candidates=f"{result['candidates']}",
    )
    content += (
        html_fragment("pronos-fragments.html", "render_div_notice")
        + esc(result["notice"])
        + html_fragment(
            "pronos-fragments.html", "render_div_lissue_affichee_est_la_plus_probable_"
        )
    )
    content += html_fragment("pronos-fragments.html", "render_div_match_grid")
    for row in rows[(page_number - 1) * 18 : page_number * 18]:
        f, model = (row["fixture"], row["model"])
        content += html_fragment(
            "pronos-fragments.html",
            "render_article_vs",
            value_0=f"{esc(LEAGUES[row['division']][0])}",
            value=f"{esc(row['kickoff_local'][:16].replace('T', ' · '))}",
            home=f"{esc(f['home'])}",
            away=f"{esc(f['away'])}",
        )
        content += (
            html_fragment("pronos-fragments.html", "render_div_eyebrow")
            + (
                "PRONO CALCULÉ"
                if model["available"] and row["outcome"] is not None
                else "PAS DE CHOIX DU MODÈLE"
            )
            + html_fragment("pronos-fragments.html", "div_close")
        )
        if row["synthetic"]:
            content += html_fragment(
                "pronos-fragments.html", "render_p_donnees_synthetiques_demonstration"
            )
        if model["available"]:
            pick = labels.get(row["outcome"], "Égalité · aucun choix")
            team = (
                f["home"]
                if row["outcome"] == "home"
                else (
                    f["away"]
                    if row["outcome"] == "away"
                    else "Match nul" if row["outcome"] == "draw" else ""
                )
            )
            content += (
                html_fragment("pronos-fragments.html", "render_p_prono_du_modele")
                + esc(pick)
                + " — "
                + esc(team)
                + html_fragment("pronos-fragments.html", "render_b_markup")
            )
            for key in ("home", "draw", "away"):
                content += html_fragment(
                    "pronos-fragments.html",
                    "render_div",
                    value_0=f"{labels[key].split(' · ')[0]}",
                    value=f"{100 * model['probabilities'][key]:.1f}",
                )
            content += html_fragment(
                "pronos-fragments.html",
                "render_div_details_du_calcul_et_de_lhistorique_e",
                home=f"{model['sample']['home']}",
                away=f"{model['sample']['away']}",
                as_of=f"{esc(model['as_of'])}",
            )
            sample_period = model.get("sample_period", {})
            if sample_period:
                years = sample_period["max_history_days"] / 365.25
                content += html_fragment(
                    "pronos-fragments.html",
                    "render_p_historique_ans_maximum_dont_matchs_sur_",
                    years=f"{years:.0f}",
                    home_recent=f"{sample_period['home_recent']}",
                    away_recent=f"{sample_period['away_recent']}",
                )
                if sample_period["max_history_days"] > 730:
                    content += html_fragment(
                        "pronos-fragments.html",
                        "render_p_des_effectifs_anciens_participent_au_ca",
                    )
            content += html_fragment("pronos-fragments.html", "details_close")
        if row.get("domestic_form"):
            content += html_fragment(
                "pronos-fragments.html",
                "render_details_forme_en_championnat_contexte_des",
            )
            for side in ("home", "away"):
                form = row["domestic_form"][side]
                content += (
                    html_fragment("pronos-fragments.html", "render_p_markup")
                    + esc(form["team"])
                    + html_fragment("pronos-fragments.html", "render_b")
                )
                if not form["available"]:
                    content += esc(form["reason"])
                else:
                    recent = form["last5"]
                    full = form["last10"]
                    content += f"{recent['played']} derniers matchs chargés : {recent['wins']} V / {recent['draws']} N / {recent['losses']} D, {recent['goals_for']} buts pour / {recent['goals_against']} contre. Sur {full['played']} matchs : {full['points']} points."
                    content += (
                        " Dernier match : " + esc(form["latest_kickoff"][:10]) + ". "
                    )
                    content += esc(" ".join(form["warnings"]))
                content += html_fragment("pronos-fragments.html", "p_close")
            content += (
                html_fragment("pronos-fragments.html", "small_open")
                + esc(row["domestic_form"]["notice"])
                + html_fragment("pronos-fragments.html", "render_small_markup_2")
            )
        if f.get("offers"):
            content += html_fragment(
                "pronos-fragments.html", "render_details_cotes_enregistrees_1_n_2"
            )
            for offer in f["offers"]:
                content += (
                    html_fragment("pronos-fragments.html", "p_open")
                    + esc(offer["bookmaker"])
                    + " : "
                    + " / ".join(
                        (
                            f"{offer['odds'][key]:.2f}"
                            for key in ("home", "draw", "away")
                        )
                    )
                    + html_fragment("pronos-fragments.html", "p_close")
                )
            content += html_fragment(
                "pronos-fragments.html",
                "render_small_cotes_indicatives_date_de_cotation_",
            )
        if row["comparison"]:
            c = row["comparison"]
            content += html_fragment(
                "pronos-fragments.html",
                "render_p_cote_cotee_le",
                odds=f"{c['odds']:.2f}",
                bookmaker=f"{esc(f['bookmaker'])}",
                quoted_at=f"{esc(f['quoted_at'])}",
            )
            content += html_fragment(
                "pronos-fragments.html",
                "render_p_esperance_theorique_unite_par_unite_fic",
                expected_return_per_unit=f"{c['expected_return_per_unit']:+.3f}",
            )
        content += (
            html_fragment("pronos-fragments.html", "render_p_simulation_fictive")
            + ("à étudier" if row["status"] == "candidate" else "abstention")
            + html_fragment("pronos-fragments.html", "render_small_markup_3")
        )
        content += (
            html_fragment("pronos-fragments.html", "ul_open")
            + "".join(
                (
                    html_fragment("pronos-fragments.html", "li_open")
                    + esc(reason)
                    + html_fragment("pronos-fragments.html", "li_close")
                    for reason in row["reasons"]
                )
            )
            + html_fragment("pronos-fragments.html", "ul_close")
        )
        coach_query = urlencode(
            {
                "league": row["division"],
                "period": result["period"],
                "event": f["event_id"],
            }
        )
        content += html_fragment(
            "pronos-fragments.html",
            "render_p_comprendre_ce_match",
            coach_query=f"{esc(coach_query)}",
        )
        content += (
            html_fragment("pronos-fragments.html", "render_p_markup_4")
            + esc(row["context_notice"])
            + html_fragment(
                "pronos-fragments.html",
                "render_small_poisson_baseline_v1_probabilites_no",
            )
        )
    content += html_fragment("pronos-fragments.html", "div_close")
    if not rows:
        other = "next3" if result["period"] == "today" else "today"
        label = (
            "Voir les trois prochains jours" if other == "next3" else "Voir aujourd’hui"
        )
        content += html_fragment(
            "pronos-fragments.html", "render_div_aucun_match_charge_pour_cette_periode"
        ) + html_fragment(
            "pronos-fragments.html",
            "render_a",
            link=f"{esc(link(horizon=other))}",
            label=f"{label}",
        )
    if result["issues"]:
        content += (
            html_fragment(
                "pronos-fragments.html", "render_details_championnats_non_evalues"
            )
            + "".join(
                (
                    html_fragment("pronos-fragments.html", "li_open")
                    + esc(LEAGUES[i["division"]][0] + ": " + i["reason"])
                    + html_fragment("pronos-fragments.html", "li_close")
                    for i in result["issues"]
                )
            )
            + html_fragment("pronos-fragments.html", "render_ul_markup_3")
        )
    if pages > 1:
        content += html_fragment("pronos-fragments.html", "render_div_pagination")
        if page_number > 1:
            content += html_fragment(
                "pronos-fragments.html",
                "render_a_precedent",
                link=f"{esc(link(page=page_number - 1))}",
            )
        content += html_fragment(
            "pronos-fragments.html",
            "render_span_page",
            page_number=f"{page_number}",
            pages=f"{pages}",
        )
        if page_number < pages:
            content += html_fragment(
                "pronos-fragments.html",
                "render_a_suivant",
                link=f"{esc(link(page=page_number + 1))}",
            )
        content += html_fragment("pronos-fragments.html", "div_close")
    return content
