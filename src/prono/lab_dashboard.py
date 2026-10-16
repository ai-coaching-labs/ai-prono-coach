"""Vues de suivi réel et d'études rétrospectives ; actions explicites protégées."""

from .presentation import html_fragment
from .presentation import asset_text
from .workspace import timestamp, utcnow
from .leagues import LEAGUES

LABELS = {"home": "1", "draw": "N", "away": "2"}
NAMES = {
    "poisson-baseline-v1": "Baseline de l’étude",
    "poisson-recency-research-v1": "Récence · expérimental",
    "dc-correction-research-v1": "Correction des petits scores · expérimental",
    "league-frequency": "Fréquences du championnat",
}


def metric(value, percent=False):
    return (
        "—" if value is None else f"{100 * value:.1f} %" if percent else f"{value:.4f}"
    )


def exclusion_summary(counts):
    labels = {
        "no_valid_quote": "cotes admissibles indisponibles",
        "quote_unavailable": "aucune capture de cotes",
        "quote_time_unavailable": "heure de cotation inconnue",
        "quote_knowledge_unavailable": "disponibilité avant match non documentée",
        "stale_odds": "cotes périmées",
        "invalid_quote": "cotes ou dates invalides",
        "invalid_observation": "capture invalide",
        "future_observation": "capture datée dans le futur",
        "conflicting_quotes": "captures de cotes contradictoires",
        "insufficient_history_at_quote": "historique insuffisant à la date des cotes",
    }
    return (
        ", ".join(
            f"{labels.get(key, 'autre exclusion')} : {count}"
            for key, count in sorted(counts.items())
        )
        or "aucun"
    )


def tracking_view(ws, league, query, esc, zone, link, page=1, token=None):
    from .tracking import tracking_summary

    result = tracking_summary(ws, league, query)
    p = result["performance"]
    disabled = "" if token else " disabled"
    content = html_fragment(
        "lab_dashboard-fragments.html",
        "tracking_view_div_mes_pronos_suivis_previsions_c",
    )
    content += (
        html_fragment("lab_dashboard-fragments.html", "tracking_view_div_stats")
        + "".join(
            (
                html_fragment(
                    "lab_dashboard-fragments.html",
                    "tracking_view_article_stat",
                    label=f"{esc(label)}",
                    value=f"{esc(value)}",
                )
                for label, value in [
                    ("Pronos enregistrés", result["captured"]),
                    ("En attente", result["pending"]),
                    ("Résultats comparés", p["evaluated"]),
                    ("Choix corrects", metric(p["accuracy"], True)),
                ]
            )
        )
        + html_fragment("lab_dashboard-fragments.html", "div_close")
    )
    content += html_fragment(
        "lab_dashboard-fragments.html",
        "tracking_view_p_score_probabiliste_erreur_logari",
        metric=f"{metric(p['brier'])}",
        metric_2=f"{metric(p['log_loss'])}",
    )
    review = result["model_review"]
    content += html_fragment(
        "lab_dashboard-fragments.html",
        "tracking_view_p_jalon_de_revue_previsions_reglee",
        settled=f"{review['settled']}",
        minimum_settled=f"{review['minimum_settled']}",
    )
    market = result["market_comparison"]
    content += html_fragment(
        "lab_dashboard-fragments.html",
        "tracking_view_p_comparaison_au_marche_sur_memes_",
        evaluated=f"{market['evaluated']}",
        metric=f"{metric(market['model']['brier'])}",
        metric_2=f"{metric(market['market']['brier'])}",
        metric_3=f"{metric(market['delta_brier'])}",
    )
    content += (
        html_fragment("lab_dashboard-fragments.html", "tracking_view_p_markup")
        + esc(market["method"] + " " + market["notice"])
        + html_fragment("lab_dashboard-fragments.html", "tracking_view_small_markup")
    )
    if market["excluded"]:
        content += (
            html_fragment("lab_dashboard-fragments.html", "p_open")
            + str(sum(market["excluded"].values()))
            + html_fragment(
                "lab_dashboard-fragments.html",
                "tracking_view_p_resultat_s_exclu_s_de_cette_comp",
            )
        )
    content += html_fragment(
        "lab_dashboard-fragments.html",
        "tracking_view_div_enregistrer_les_pronos_charges",
        disabled=f"{disabled}",
        disabled_2=f"{disabled}",
    )
    content += (
        html_fragment("lab_dashboard-fragments.html", "tracking_view_div_notice")
        + esc(result["notice"])
        + html_fragment(
            "lab_dashboard-fragments.html",
            "tracking_view_div_le_suivi_fonctionne_pendant_qu",
        )
    )
    import json

    for filename in ("data/result-refresh-status.json", "data/tracking-status.json"):
        path = ws.path(filename)
        if path.exists():
            state = json.loads(path.read_text())
            if state.get("error"):
                content += (
                    html_fragment(
                        "lab_dashboard-fragments.html",
                        "tracking_view_p_suivi_automatique",
                    )
                    + esc(state["error"])
                    + html_fragment("lab_dashboard-fragments.html", "p_close")
                )
            if filename.endswith("result-refresh-status.json"):
                for code, status in state.items():
                    if status.get("status") == "error" and (
                        league == "all" or code == league
                    ):
                        content += (
                            html_fragment(
                                "lab_dashboard-fragments.html",
                                "tracking_view_p_import_de_resultats",
                            )
                            + esc(LEAGUES[code][0])
                            + " : "
                            + esc(status["error"])
                            + html_fragment(
                                "lab_dashboard-fragments.html",
                                "p_close",
                            )
                        )
    pages = max(1, (len(result["matches"]) + 17) // 18)
    page = min(max(1, page), pages)
    content += html_fragment(
        "lab_dashboard-fragments.html",
        "tracking_view_div_match_prono_enregistre_resulta",
    )
    ordered = sorted(
        result["matches"],
        key=lambda row: (
            row["status"] != "pending",
            (
                timestamp(row["fixture"]["kickoff"]).timestamp()
                if row["status"] == "pending"
                else -timestamp(row["fixture"]["kickoff"]).timestamp()
            ),
        ),
    )
    for row in ordered[(page - 1) * 18 : page * 18]:
        f = row["fixture"]
        outcome = row["outcome"]
        r = row["result"]
        predicted = (
            LABELS[outcome] + " · " + metric(row["probabilities"][outcome], True)
        )
        score = (
            f"{r['home_goals']} – {r['away_goals']}"
            if r and r["status"] == "settled"
            else "Reporté" if row["status"] == "rescheduled" else "En attente"
        )
        state = (
            "Choix correct"
            if r and r.get("actual") == outcome
            else (
                "Choix incorrect"
                if row["status"] == "settled"
                else (
                    "Prévision à renouveler"
                    if row["status"] == "rescheduled"
                    else (
                        "Avant match"
                        if timestamp(f["kickoff"]) > utcnow()
                        else "Résultat non publié ou non chargé"
                    )
                )
            )
        )
        match = (
            esc(f["home"] + " / " + f["away"])
            + html_fragment("lab_dashboard-fragments.html", "tracking_view_br_markup")
            + esc(
                LEAGUES[row["division"]][0]
                + " · "
                + timestamp(f["kickoff"]).astimezone(zone).strftime("%d/%m à %H:%M")
            )
            + html_fragment("lab_dashboard-fragments.html", "small_close")
        )
        archived = (
            esc(predicted)
            + html_fragment("lab_dashboard-fragments.html", "tracking_view_br_markup")
            + esc(
                "Enregistré le "
                + timestamp(row["created_at"])
                .astimezone(zone)
                .strftime("%d/%m à %H:%M")
            )
            + html_fragment("lab_dashboard-fragments.html", "small_close")
        )
        content += (
            html_fragment("lab_dashboard-fragments.html", "tracking_view_tr_markup")
            + match
            + html_fragment("lab_dashboard-fragments.html", "tracking_view_td_markup")
            + archived
            + html_fragment("lab_dashboard-fragments.html", "td_close")
            + "".join(
                (
                    html_fragment("lab_dashboard-fragments.html", "td_open")
                    + esc(v)
                    + html_fragment("lab_dashboard-fragments.html", "td_close")
                    for v in [score, state]
                )
            )
            + html_fragment("lab_dashboard-fragments.html", "tr_close")
        )
    content += html_fragment(
        "lab_dashboard-fragments.html", "tracking_view_tbody_markup"
    )
    if not result["matches"]:
        content += html_fragment(
            "lab_dashboard-fragments.html",
            "tracking_view_p_aucun_prono_enregistre_pour_ces_",
        )
    if pages > 1:
        content += (
            html_fragment(
                "lab_dashboard-fragments.html", "tracking_view_div_pagination"
            )
            + (
                html_fragment(
                    "lab_dashboard-fragments.html",
                    "tracking_view_a_precedent",
                    link=f"{esc(link(page=page - 1))}",
                )
                if page > 1
                else ""
            )
            + html_fragment(
                "lab_dashboard-fragments.html",
                "tracking_view_span_page",
                page=f"{page}",
                pages=f"{pages}",
            )
            + (
                html_fragment(
                    "lab_dashboard-fragments.html",
                    "tracking_view_a_suivant",
                    link=f"{esc(link(page=page + 1))}",
                )
                if page < pages
                else ""
            )
            + html_fragment("lab_dashboard-fragments.html", "div_close")
        )
    return content


def evaluation_view(ws, league, esc, token=None):
    from .evaluation import latest_evaluation

    report = latest_evaluation(ws)
    disabled = "" if token else " disabled"
    content = html_fragment(
        "lab_dashboard-fragments.html",
        "evaluation_view_div_qualite_des_probabilites_etu",
    )
    content += html_fragment(
        "lab_dashboard-fragments.html",
        "evaluation_view_div_evaluation_etude_retrospecti",
        disabled=f"{disabled}",
    )
    content += html_fragment(
        "lab_dashboard-fragments.html",
        "evaluation_view_div_le_modele_utilise_pour_les_p",
    )
    if not report:
        return content + html_fragment(
            "lab_dashboard-fragments.html",
            "evaluation_view_p_aucune_etude_enregistree_la_co",
        )
    content += (
        html_fragment(
            "lab_dashboard-fragments.html", "evaluation_view_p_derniere_etude"
        )
        + esc(report["created_at"])
        + " · "
        + (
            "Archives rétrospectives"
            if report["mode"] == "snapshot"
            else "Connaissance strictement antérieure"
        )
        + html_fragment("lab_dashboard-fragments.html", "evaluation_view_p_markup")
        + esc(report["notice"])
        + html_fragment("lab_dashboard-fragments.html", "p_close")
    )
    if report.get("not_evaluated"):
        content += (
            html_fragment(
                "lab_dashboard-fragments.html",
                "evaluation_view_p_competitions_chargees_sans_etu",
            )
            + esc(", ".join((LEAGUES[c][0] for c in report["not_evaluated"])))
            + html_fragment("lab_dashboard-fragments.html", "evaluation_view_p")
        )
    for code, result in report["leagues"].items():
        if league != "all" and code != league:
            continue
        content += (
            html_fragment("lab_dashboard-fragments.html", "evaluation_view_h_markup")
            + esc(LEAGUES[code][0])
            + html_fragment(
                "lab_dashboard-fragments.html", "evaluation_view_h_markup_2"
            )
        )
        currency = report["currency"][code]
        if not currency["current"]:
            content += (
                html_fragment(
                    "lab_dashboard-fragments.html",
                    "evaluation_view_p_etude_a_actualiser",
                )
                + esc(" ".join(currency["reasons"]))
                + html_fragment("lab_dashboard-fragments.html", "p_close")
            )
        if result.get("error"):
            content += (
                html_fragment("lab_dashboard-fragments.html", "p_open")
                + esc(result["error"])
                + html_fragment("lab_dashboard-fragments.html", "p_close")
            )
            continue
        if result["synthetic"]:
            content += html_fragment(
                "lab_dashboard-fragments.html",
                "evaluation_view_p_donnees_synthetiques_demonstra",
            )
        content += (
            html_fragment("lab_dashboard-fragments.html", "p_open")
            + str(result["target_count"])
            + " matchs dans la période de test · "
            + str(result["skipped"])
            + " non évaluables. "
            + esc(result["method"])
            + html_fragment("lab_dashboard-fragments.html", "p_close")
        )
        content += html_fragment(
            "lab_dashboard-fragments.html",
            "evaluation_view_div_modele_matchs_brier_log_loss",
        )
        for name, model in result["models"].items():
            c = model["comparison"]
            delta = metric(c["delta_brier"]) + (
                f" [{metric(c['lower'])} ; {metric(c['upper'])}]"
                if c["lower"] is not None
                else ""
            )
            content += (
                html_fragment("lab_dashboard-fragments.html", "tr_open")
                + "".join(
                    (
                        html_fragment("lab_dashboard-fragments.html", "td_open")
                        + esc(v)
                        + html_fragment("lab_dashboard-fragments.html", "td_close")
                        for v in [
                            NAMES[name],
                            model["evaluated"],
                            metric(model["brier"]),
                            metric(model["log_loss"]),
                            metric(model["accuracy"], True),
                            delta,
                        ]
                    )
                )
                + html_fragment("lab_dashboard-fragments.html", "tr_close")
            )
        content += html_fragment(
            "lab_dashboard-fragments.html",
            "evaluation_view_tbody_un_score_plus_bas_est_meil",
        )
        market = result.get("market_comparison")
        if market is None:
            content += html_fragment(
                "lab_dashboard-fragments.html",
                "evaluation_view_p_reference_marche_absente_de_ce",
            )
        else:
            content += html_fragment(
                "lab_dashboard-fragments.html",
                "evaluation_view_h_reference_marche_memes_matchs_",
                evaluated=f"{market['evaluated']}",
                metric=f"{metric(market['market']['brier'])}",
            )
            content += html_fragment(
                "lab_dashboard-fragments.html",
                "evaluation_view_table_modele_matchs_apparies_bri",
            )
            for name, model in market["models"].items():
                content += (
                    html_fragment("lab_dashboard-fragments.html", "tr_open")
                    + "".join(
                        (
                            html_fragment(
                                "lab_dashboard-fragments.html",
                                "td_open",
                            )
                            + esc(value)
                            + html_fragment(
                                "lab_dashboard-fragments.html",
                                "td_close",
                            )
                            for value in [
                                NAMES[name],
                                model["evaluated"],
                                metric(model["brier"]),
                                metric(market["market"]["brier"]),
                                metric(model["delta_brier"]),
                            ]
                        )
                    )
                    + html_fragment("lab_dashboard-fragments.html", "tr_close")
                )
            content += (
                html_fragment(
                    "lab_dashboard-fragments.html", "evaluation_view_tbody_markup"
                )
                + esc(market["method"] + " " + market["notice"])
                + html_fragment("lab_dashboard-fragments.html", "p_close")
            )
            content += (
                html_fragment(
                    "lab_dashboard-fragments.html", "evaluation_view_p_matchs_exclus"
                )
                + esc(exclusion_summary(market["excluded"]))
                + ". Motifs des cotes : "
                + esc(exclusion_summary(market["quote_exclusions"]))
                + html_fragment("lab_dashboard-fragments.html", "evaluation_view_p")
            )
        content += html_fragment(
            "lab_dashboard-fragments.html",
            "evaluation_view_details_voir_la_calibration_de_l",
        )
        for b in result["models"]["poisson-baseline-v1"]["calibration"]:
            content += (
                html_fragment("lab_dashboard-fragments.html", "tr_open")
                + "".join(
                    (
                        html_fragment("lab_dashboard-fragments.html", "td_open")
                        + esc(v)
                        + html_fragment("lab_dashboard-fragments.html", "td_close")
                        for v in [
                            LABELS[b["outcome"]],
                            metric(b["lower"], True) + " à " + metric(b["upper"], True),
                            b["count"],
                            metric(b["mean_probability"], True),
                            metric(b["observed_frequency"], True),
                        ]
                    )
                )
                + html_fragment("lab_dashboard-fragments.html", "tr_close")
            )
        content += (
            html_fragment(
                "lab_dashboard-fragments.html",
                "evaluation_view_tbody_lecture_descriptive_petits",
            )
            + esc(result["variant_notes"])
            + html_fragment(
                "lab_dashboard-fragments.html", "tracking_view_small_markup"
            )
        )
    return content


SCRIPT = asset_text("dashboard.js")
