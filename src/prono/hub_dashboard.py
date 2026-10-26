"""Vue multi-championnats en lecture seule, calculée à partir des fichiers locaux."""

from .presentation import html_fragment
import html
import json
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from .leagues import LEAGUES, league_workspace
from .branding import ICON_LINK
from .model import load_history
from .presentation import asset_text
from .workspace import utcnow, timestamp


def page(ws, params=None, token=None):
    params = params or {}
    esc = lambda value: html.escape(str(value), quote=True)
    code = params.get("league", "all")
    if code != "all" and code not in LEAGUES:
        raise ValueError("Championnat inconnu.")
    query = params.get("q", "").strip()[:100]
    period = params.get("period", "upcoming")
    if period not in ("upcoming", "today", "all"):
        raise ValueError("Période inconnue.")
    tab = params.get("tab", "pronos")
    if tab not in (
        "matches",
        "results",
        "coverage",
        "team",
        "pronos",
        "accumulators",
        "tracking",
        "evaluation",
    ):
        raise ValueError("Vue inconnue.")
    page_number = max(1, int(params.get("page", "1")))
    now, zone = (
        utcnow(),
        ZoneInfo(ws.config.get("coaching", {}).get("timezone", "Europe/Paris")),
    )
    manifest_path = ws.path("data/league-hub.json")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    from .market_watch import public_calendar

    market = public_calendar(ws)
    selected = list(LEAGUES) if code == "all" else [code]
    histories, errors, windows = ({key: [] for key in selected}, {}, {})
    for key in selected if tab in ("results", "coverage") else []:
        try:
            child = league_workspace(ws, key)
            windows[key] = int(child.config["model"]["max_history_days"])
            histories[key] = load_history(child.path("data/history.csv"))
        except (ValueError, OSError) as exc:
            histories[key], errors[key] = ([], str(exc))
    selected_history = [(key, row) for key in selected for row in histories[key]]
    filtered_history = [
        (key, r)
        for key, r in selected_history
        if query.casefold() in (r["home"] + " " + r["away"]).casefold()
    ]
    filtered_history.sort(key=lambda item: timestamp(item[1]["kickoff"]), reverse=True)
    matches = []
    for row in market.get("matches", []):
        if (
            row["division"] not in selected
            or query.casefold() not in (row["home"] + " " + row["away"]).casefold()
        ):
            continue
        kickoff = timestamp(row["kickoff"])
        if period == "upcoming" and kickoff <= now:
            continue
        if (
            period == "today"
            and kickoff.astimezone(zone).date() != now.astimezone(zone).date()
        ):
            continue
        matches.append(row)
    matches.sort(key=lambda row: timestamp(row["kickoff"]))

    def link(**changes):
        values = {
            "league": code,
            "q": query,
            "period": period,
            "tab": tab,
            "horizon": params.get("horizon", "today"),
        }
        values.update(changes)
        return "/?" + urlencode(values)

    nav = html_fragment(
        "hub_dashboard-fragments.html",
        "page_a_tous_les_championnats",
        value=f"{('active' if code == 'all' else '')}",
        link=f"{esc(link(league='all'))}",
        len=f"{len(LEAGUES)}",
    )
    country = None
    for key, (name, nation, slug) in LEAGUES.items():
        if nation != country:
            nav += html_fragment(
                "hub_dashboard-fragments.html",
                "page_div_country",
                nation=f"{esc(nation)}",
            )
            country = nation
        nav += html_fragment(
            "hub_dashboard-fragments.html",
            "page_a_league_value",
            value=f"{('active' if code == key else '')}",
            link=f"{esc(link(league=key))}",
            name=f"{esc(name)}",
        )
    titles = {
        "pronos": "Les pronos",
        "accumulators": "Les combinés fictifs",
        "tracking": "Mon suivi",
        "matches": "Le calendrier",
        "results": "Les résultats",
        "team": "L’équipe et les dossiers",
        "coverage": "Les données et leurs sources",
        "evaluation": "Évaluer le modèle",
    }
    title = titles[tab]
    subtitle = (
        "Toutes les compétitions"
        if code == "all"
        else LEAGUES[code][0] + " · " + LEAGUES[code][1]
    )
    options = html_fragment(
        "hub_dashboard-fragments.html", "page_option_toutes_les_competitions"
    ) + "".join(
        (
            html_fragment(
                "hub_dashboard-fragments.html",
                "page_option_markup",
                key=f"{key}",
                value=f"{('selected' if key == code else '')}",
                value_2=f"{esc(nation + ' · ' + name)}",
            )
            for key, (name, nation, _) in LEAGUES.items()
        )
    )

    def tab_links(entries):
        return "".join(
            (
                html_fragment(
                    "hub_dashboard-fragments.html",
                    "tab_links_a_tab_value",
                    value=f"{('chosen' if tab == value else '')}",
                    value_2=f"{('aria-current=page' if tab == value else '')}",
                    link=f"{esc(link(tab=value))}",
                    label=f"{label}",
                )
                for value, label in entries
            )
        )

    tabs = tab_links(
        [("pronos", "Pronos"), ("accumulators", "Combinés"), ("tracking", "Suivi"), ("matches", "Calendrier")]
    )
    advanced = tab_links(
        [
            ("results", "Résultats"),
            ("team", "Équipe et dossiers"),
            ("coverage", "Données et sources"),
            ("evaluation", "Évaluation"),
        ]
    )
    advanced_open = (
        " open" if tab in ("results", "team", "coverage", "evaluation") else ""
    )
    controls = html_fragment(
        "hub_dashboard-fragments.html",
        "page_form_competition",
        tab=f"{esc(tab)}",
        options=f"{options}",
    )
    if tab not in ("coverage", "evaluation"):
        controls += html_fragment(
            "hub_dashboard-fragments.html", "page_label_equipe", query=f"{esc(query)}"
        )
    if tab == "matches":
        controls += (
            html_fragment("hub_dashboard-fragments.html", "page_label_calendrier")
            + "".join(
                (
                    html_fragment(
                        "hub_dashboard-fragments.html",
                        "page_option_markup_2",
                        value=f"{value}",
                        value_2=f"{('selected' if value == period else '')}",
                        label=f"{label}",
                    )
                    for value, label in [
                        ("upcoming", "À venir"),
                        ("today", "Aujourd’hui"),
                        ("all", "Tout le fichier"),
                    ]
                )
            )
            + html_fragment("hub_dashboard-fragments.html", "page_select_markup")
        )
    controls += html_fragment("hub_dashboard-fragments.html", "page_button_filtrer")
    content = ""
    items = matches if tab == "matches" else filtered_history
    per_page = 18
    pages = max(1, (len(items) + per_page - 1) // per_page)
    page_number = min(page_number, pages)
    visible = items[(page_number - 1) * per_page : page_number * per_page]
    if tab == "tracking":
        from .lab_dashboard import tracking_view

        content = tracking_view(
            ws,
            code,
            query,
            esc,
            zone,
            link,
            max(1, int(params.get("page", "1"))),
            token,
        )
    elif tab == "evaluation":
        from .lab_dashboard import evaluation_view

        content = evaluation_view(ws, code, esc, token)
    elif tab == "accumulators":
        from .accumulators import propose, render
        from .accumulator_preparation import preparation, render_preparation

        budget = params.get("budget", "0")
        horizon = params.get("horizon", "today")
        ticket_mode = params.get("format", "auto")
        quote_mode = params.get("quotes", "indicative")
        plan = preparation(ws, horizon, code, now, quote_mode=quote_mode)
        controls = ""
        content = render_preparation(plan, esc, zone, options, ticket_mode, params.get('budget', ''))
        if 'budget' in params:
            result = propose(ws, budget, horizon, code, query, now, ticket_mode=ticket_mode,
                             allow_indicative=quote_mode == 'indicative',
                             event_ids=json.loads(params['event_ids']) if params.get('event_ids') else None)
            content += '<section id="combo-results" tabindex="-1">' + render(result, esc, zone,
                              coach_url='/chat?' + urlencode({'league': code, 'period': horizon})) + '</section>'
    elif tab == "pronos":
        from .pronos import selections, render

        result = selections(ws, params.get("horizon", "today"), code, query, now)
        content = render(
            result, link, esc, page_number=max(1, int(params.get("page", "1")))
        )
        controls = html_fragment(
            "hub_dashboard-fragments.html",
            "page_form_competition_equipe_filtrer",
            period=f"{esc(result['period'])}",
            options=f"{options}",
            query=f"{esc(query)}",
        )
    elif tab == "matches":
        content += (
            html_fragment(
                "hub_dashboard-fragments.html",
                "page_div_le_calendrier_du_marche_heures_locales",
            )
            + esc(str(zone))
            + html_fragment("hub_dashboard-fragments.html", "page_span_markup")
        )
        content += html_fragment("hub_dashboard-fragments.html", "page_div_match_grid")
        for row in visible:
            kickoff = timestamp(row["kickoff"]).astimezone(zone)
            prices = ""
            for offer in row["offers"]:
                prices += (
                    html_fragment("hub_dashboard-fragments.html", "page_div_offer")
                    + esc(offer["bookmaker"])
                    + html_fragment("hub_dashboard-fragments.html", "page_small_markup")
                    + "".join(
                        (
                            html_fragment(
                                "hub_dashboard-fragments.html",
                                "page_div_markup",
                                label=f"{label}",
                                value=f"{offer['odds'][outcome]:.2f}",
                            )
                            for outcome, label in [
                                ("home", "1"),
                                ("draw", "N"),
                                ("away", "2"),
                            ]
                        )
                    )
                    + html_fragment("hub_dashboard-fragments.html", "page_div_markup_2")
                )
            started = timestamp(row["kickoff"]) <= now
            from .identity import freshness

            health = freshness(row, now, float(ws.config["data"]["max_odds_age_hours"]))
            revisions = (
                html_fragment(
                    "hub_dashboard-fragments.html",
                    "page_p_horaire_mis_a_jour_changement_s_conserve_",
                    len=f"{len(row['schedule_revisions'])}",
                )
                if row.get("schedule_revisions")
                else ""
            )
            if row.get("identity_warning"):
                revisions += (
                    html_fragment("hub_dashboard-fragments.html", "p_open")
                    + esc(row["identity_warning"])
                    + html_fragment("hub_dashboard-fragments.html", "p_close")
                )
            content += html_fragment(
                "hub_dashboard-fragments.html",
                "page_article_vs_cotation_non_horodatee_observati",
                value_0=f"{esc(LEAGUES[row['division']][0])}",
                value=f"{kickoff.strftime('%d/%m · %H:%M')}",
                home=f"{esc(row['home'])}",
                away=f"{esc(row['away'])}",
                value_2=f"{prices or html_fragment('hub_dashboard-fragments.html', 'page_p_cotes_indisponibles_pour_les_bookmakers_p')}",
                revisions=f"{revisions}",
                value_3=f"{('Match commencé · ' if started else '')}",
                health=f"{esc(health)}",
            )
        content += html_fragment("hub_dashboard-fragments.html", "div_close")
        if not matches:
            content += html_fragment(
                "hub_dashboard-fragments.html",
                "page_div_aucune_rencontre_dans_cette_selection_e",
            )
    elif tab == "results":
        content += (
            html_fragment(
                "hub_dashboard-fragments.html",
                "page_div_les_derniers_resultats_charges",
            )
            + str(len(filtered_history))
            + html_fragment(
                "hub_dashboard-fragments.html",
                "page_span_matchs_filtres_actifs_date_championnat",
            )
        )
        for key, row in visible:
            content += (
                html_fragment("hub_dashboard-fragments.html", "tr_open")
                + "".join(
                    (
                        html_fragment(
                            "hub_dashboard-fragments.html",
                            "page_td_markup",
                            value=f"{esc(value)}",
                        )
                        for value in [
                            timestamp(row["kickoff"])
                            .astimezone(zone)
                            .strftime("%d/%m/%Y %H:%M"),
                            LEAGUES[key][0],
                            row["home"],
                            f"{row['home_goals']} – {row['away_goals']}",
                            row["away"],
                        ]
                    )
                )
                + html_fragment("hub_dashboard-fragments.html", "tr_close")
            )
        content += html_fragment("hub_dashboard-fragments.html", "page_tbody_markup")
        if not visible:
            content += html_fragment(
                "hub_dashboard-fragments.html",
                "page_div_aucun_resultat_pour_ces_filtres",
            )
    elif tab == "team":
        from .context import contexts

        roles = [
            (
                "coach",
                "Coach coordinateur",
                "Croise les avis, explique les désaccords et conserve la décision finale.",
            ),
            (
                "sports-journalist",
                "Journaliste sportif",
                "Actualité des deux clubs, déclarations, blessures et suspensions. Sources lues et datées.",
            ),
            (
                "lineup-analyst",
                "Expert effectif",
                "Absents, incertains, retours et onze officiel. Distingue probable et confirmé.",
            ),
            (
                "bookmaker-expert",
                "Expert bookmakers",
                "Qualité des cotes, règles du marché et mouvements documentés par plusieurs captures.",
            ),
            (
                "match-analyst",
                "Analyste sportif",
                "Contexte tactique, calendrier, récupération et limites de la baseline.",
            ),
            (
                "market-analyst",
                "Analyste du marché",
                "Explique marge, probabilités implicites et écarts calculés par les outils.",
            ),
            (
                "risk-manager",
                "Responsable des limites",
                "Vérifie fraîcheur, exposition fictive et motifs d’abstention.",
            ),
            (
                "performance-analyst",
                "Analyste des performances",
                "Bilan du journal, qualité prédictive et taille des échantillons.",
            ),
        ]
        enabled = ws.config["agents"]["enabled"]
        content = html_fragment(
            "hub_dashboard-fragments.html",
            "page_div_une_equipe_pour_preparer_chaque_match_r",
        )
        for key, name, description in roles:
            content += html_fragment(
                "hub_dashboard-fragments.html",
                "page_article_match",
                value=f"{('ACTIVÉ' if key in enabled else 'DÉSACTIVÉ')}",
                name=f"{esc(name)}",
                description=f"{esc(description)}",
            )
        content += html_fragment(
            "hub_dashboard-fragments.html",
            "page_div_demander_une_analyse_complete_dans_votr",
        )
        event_ids = {
            r["event_id"]
            for r in market.get("matches", [])
            if r["division"] in selected
        }
        dossiers = [
            d
            for d in contexts(ws)
            if (code == "all" or d["event_id"] in event_ids)
            and query.casefold() in (d["home"] + " " + d["away"]).casefold()
        ]
        if not dossiers:
            content += html_fragment(
                "hub_dashboard-fragments.html",
                "page_div_aucun_dossier_source_archive_les_roles_",
            )
        for dossier in dossiers[:20]:
            content += html_fragment(
                "hub_dashboard-fragments.html",
                "page_article_dossier_archive_verifier_les_evolut",
                home=f"{esc(dossier['home'])}",
                away=f"{esc(dossier['away'])}",
                as_of=f"{esc(dossier['as_of'])}",
            )
            for fact in dossier["findings"]:
                status_label = {
                    "confirmed": "Confirmé par la source",
                    "reported": "Rapporté",
                    "uncertain": "Incertain",
                    "contradicted": "Contradiction",
                }[fact["status"]]
                content += html_fragment(
                    "hub_dashboard-fragments.html",
                    "page_p",
                    status_label=f"{status_label}",
                    team=f"{esc(fact['team'])}",
                    claim=f"{esc(fact['claim'])}",
                )
                for source in fact["sources"]:
                    content += html_fragment(
                        "hub_dashboard-fragments.html",
                        "page_a",
                        url=f"{esc(source['url'])}",
                        title=f"{esc(source['title'])}",
                    )
                content += html_fragment("hub_dashboard-fragments.html", "p_close")
            content += (
                html_fragment("hub_dashboard-fragments.html", "page_p_manques")
                + esc("; ".join(dossier["missing"]))
                + html_fragment("hub_dashboard-fragments.html", "page_p_markup_3")
            )
    else:
        content += html_fragment(
            "hub_dashboard-fragments.html",
            "page_div_ce_qui_est_reellement_disponible_couver",
        )
        for key in selected:
            rows = histories[key]
            last = max((timestamp(r["kickoff"]) for r in rows), default=None)
            first = min((timestamp(r["kickoff"]) for r in rows), default=None)
            status = manifest.get("leagues", {}).get(key, {})
            calendar_status = {**market.get("domestic_sources", {}),
                               **market.get("europe_sources", {})}.get(key, {})
            issue = (
                errors.get(key)
                or (status.get("message") if status.get("status") == "error" else None)
                or (
                    calendar_status.get("message")
                    if calendar_status.get("status") == "error"
                    else None
                )
            )
            availability = (
                "Disponible · "
                + str(status["rejected"])
                + " résultat(s) exclus avec trace"
                if status.get("rejected")
                else "Disponible" if rows else "À importer"
            )
            window = (
                f"{windows[key] / 365.25:.0f} ans maximum" if key in windows else "—"
            )
            content += (
                html_fragment("hub_dashboard-fragments.html", "tr_open")
                + "".join(
                    (
                        html_fragment(
                            "hub_dashboard-fragments.html",
                            "page_td_markup",
                            value=f"{esc(value)}",
                        )
                        for value in [
                            LEAGUES[key][0],
                            len(rows),
                            first.strftime("%d/%m/%Y") if first else "—",
                            last.strftime("%d/%m/%Y") if last else "—",
                            window,
                            issue or availability,
                        ]
                    )
                )
                + html_fragment("hub_dashboard-fragments.html", "tr_close")
            )
        content += asset_text("coverage-notes.html")
    if tab in ("matches", "results") and pages > 1:
        content += html_fragment("hub_dashboard-fragments.html", "page_div_pagination")
        if page_number > 1:
            content += html_fragment(
                "hub_dashboard-fragments.html",
                "page_a_precedent",
                link=f"{esc(link(page=page_number - 1))}",
            )
        content += html_fragment(
            "hub_dashboard-fragments.html",
            "page_span_page",
            page_number=f"{page_number}",
            pages=f"{pages}",
        )
        if page_number < pages:
            content += html_fragment(
                "hub_dashboard-fragments.html",
                "page_a_suivant",
                link=f"{esc(link(page=page_number + 1))}",
            )
        content += html_fragment("hub_dashboard-fragments.html", "div_close")
    collected = (
        " · ".join(
            (
                d["label"]
                + " : "
                + timestamp(d["collected_at"])
                .astimezone(zone)
                .strftime("%d/%m/%Y à %H:%M")
                for d in market["datasets"]
                if d.get("collected_at")
            )
        )
        or "non effectuée"
    )
    errors_count = sum(
        (v.get("status") == "error" for v in manifest.get("leagues", {}).values())
    )
    import_warning = (
        html_fragment(
            "hub_dashboard-fragments.html",
            "page_div_import_s_en_echec_consultez_couverture_",
            errors_count=f"{errors_count}",
        )
        if errors_count
        else ""
    )
    collection_note = (
        html_fragment(
            "hub_dashboard-fragments.html",
            "page_details_dates_de_collecte_et_limites_des_co",
            collected=f"{esc(collected)}",
        )
        if tab in ("matches", "coverage")
        else ""
    )
    return asset_text("hub.html").format_map(
        {
            "title": esc(title),
            "icon_link": ICON_LINK,
            "css": CSS,
            "competitions_open": " open" if code != "all" else "",
            "nav": nav,
            "token": esc(token or ""),
            "coach_query": esc(
                urlencode({"league": code, "period": params.get("horizon", "today")})
            ),
            "subtitle": esc(subtitle),
            "tabs": tabs,
            "advanced_open": advanced_open,
            "advanced": advanced,
            "import_warning": import_warning,
            "controls": controls,
            "collection_note": collection_note,
            "content": content,
            "date": now.astimezone(zone).strftime("%d.%m.%Y"),
            "scripts": (
                '<script src="/accumulators.js"></script>' if tab == "accumulators" else
                html_fragment("hub_dashboard-fragments.html", "page_script_markup")
                if tab in ("tracking", "evaluation")
                else ""
            ),
        }
    )


CSS = asset_text("hub.css")
