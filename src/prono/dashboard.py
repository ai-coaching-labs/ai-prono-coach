"""Dashboard loopback : lecture et opérations explicites protégées par un jeton."""

from .presentation import html_fragment, asset_text
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import threading
from urllib.parse import urlsplit, parse_qs
from .journal import summary
from .analysis import fixtures
from .briefing import daily_briefing
from .branding import ICON_SVG, ICON_LINK
from .history_import import history_status


def page(ws):
    stats = summary(ws)
    matches = fixtures(ws)
    esc = lambda v: html.escape(str(v), quote=True)
    brief = daily_briefing(ws)
    history = history_status(ws)
    dataset = (
        "DÉMONSTRATION SYNTHÉTIQUE"
        if history["synthetic"]
        else "DONNÉES SOURCÉES" if history["rows"] else "HISTORIQUE ABSENT"
    )
    daily_rows = "".join(
        (
            html_fragment(
                "dashboard-fragments.html",
                "page_li",
                home=f"{esc(i['fixture']['home'])}",
                away=f"{esc(i['fixture']['away'])}",
                kickoff_local=f"{esc(i['kickoff_local'])}",
                reason=f"{esc(i['reason'])}",
                value=f"{(' — Données SYNTHÉTIQUES' if i['synthetic'] else '')}",
            )
            for i in brief["matches"]
        )
    )
    daily_actions = "".join(
        (
            html_fragment(
                "dashboard-fragments.html", "page_li_markup", action=f"{esc(action)}"
            )
            for action in brief["next_steps"]
        )
    )
    cards = "".join(
        (
            html_fragment(
                "dashboard-fragments.html",
                "page_article_markup",
                label=f"{label}",
                value=f"{esc(value)}",
            )
            for label, value in [
                ("Solde fictif", f"{stats['balance']:.2f} u"),
                ("Résultat fictif", f"{stats['net_pnl']:+.2f} u"),
                ("Exposition ouverte", f"{stats['open_exposure']:.2f} u"),
                ("Paris clôturés", stats["settled_count"]),
            ]
        )
    )
    rows = "".join(
        (
            html_fragment("dashboard-fragments.html", "tr_open")
            + "".join(
                (
                    html_fragment(
                        "dashboard-fragments.html", "page_td_markup", v=f"{esc(v)}"
                    )
                    for v in [
                        f["home"] + " / " + f["away"],
                        f["kickoff"],
                        f["odds"]["home"],
                        f["odds"]["draw"],
                        f["odds"]["away"],
                        f["source"],
                    ]
                )
            )
            + html_fragment("dashboard-fragments.html", "tr_close")
            for f in matches
        )
    )
    return html_fragment(
        "dashboard-fragments.html",
        "page_html_ai_prono_coach_body_h1_tag_cards_artic",
        icon_link=f"{ICON_LINK}",
        css=asset_text("workspace.css"),
        dataset=f"{dataset}",
        rows=f"{history['rows']}",
        len=f"{len(history['teams'])}",
        value=f"{esc(history['latest_kickoff'] or 'indisponible')}",
        notice=f"{esc(history['notice'])}",
        value_2=f"{esc(', '.join(history['teams']))}",
        value_3=f"{esc(' · '.join(history['sources']))}",
        cards=f"{cards}",
        date=f"{esc(brief['date'])}",
        timezone=f"{esc(brief['timezone'])}",
        notice_2=f"{esc(brief['notice'])}",
        value_4=f"{daily_rows or html_fragment('dashboard-fragments.html', 'page_li_aucun_match_charge_pour_cette_journee')}",
        daily_actions=f"{daily_actions}",
        rows_2=f"{rows}",
        notice_3=f"{esc(stats['notice'])}",
    )


def serve(ws, port=8766):
    token = secrets.token_urlsafe(32)
    operation_lock = threading.Lock()
    from .team import TeamJobs

    team_jobs = TeamJobs(ws)
    from .evaluation import EvaluationJobs

    evaluation_jobs = EvaluationJobs(ws)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Ne rien exposer hors loopback, ni servir de fichiers du disque.
            if self.headers.get("Host", "").split(":")[0] not in (
                "127.0.0.1",
                "localhost",
            ):
                self.send_error(403)
                return
            parsed = urlsplit(self.path)
            job_path = parsed.path.startswith("/api/chat/jobs/")
            history_path = parsed.path == "/api/chat/analyses" or parsed.path.startswith("/api/chat/analyses/")
            if (
                job_path or history_path or parsed.path == "/api/evaluation"
            ) and not secrets.compare_digest(
                self.headers.get("X-Prono-Token", ""), token
            ):
                self.send_error(403)
                return
            if (
                parsed.path
                not in (
                    "/",
                    "/icon.svg",
                    "/api/summary",
                    "/api/health",
                    "/chat",
                    "/chat.js",
                    "/dashboard.js",
                    "/api/evaluation",
                    "/api/tracking",
                    "/api/chat/options",
                    "/api/chat/matches",
                )
                and not job_path and not history_path
            ):
                self.send_error(404)
                return
            try:
                if parsed.path == "/api/health":
                    payload = b'{"ready":true}'
                elif parsed.path == "/icon.svg":
                    payload = ICON_SVG.encode()
                elif parsed.path == "/api/evaluation":
                    payload = json.dumps(
                        evaluation_jobs.get(), ensure_ascii=False
                    ).encode()
                elif parsed.path == "/api/tracking":
                    from .tracking import tracking_summary

                    payload = json.dumps(
                        tracking_summary(ws), ensure_ascii=False
                    ).encode()
                elif parsed.path == "/dashboard.js":
                    from .lab_dashboard import SCRIPT

                    payload = SCRIPT.encode()
                elif job_path:
                    payload = json.dumps(
                        team_jobs.get(parsed.path.rsplit("/", 1)[-1]),
                        ensure_ascii=False,
                    ).encode()
                elif history_path:
                    from .review_history import archived_review, list_reviews

                    if parsed.path == "/api/chat/analyses":
                        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
                        result = list_reviews(ws, params.get("q", ""), int(params.get("offset", 0)),
                                              int(params.get("limit", 5)))
                    else:
                        result = archived_review(ws, parsed.path.rsplit("/", 1)[-1])
                    payload = json.dumps(result, ensure_ascii=False).encode()
                elif parsed.path == "/api/chat/matches":
                    from .chat import coach_facts

                    params = {
                        key: values[-1]
                        for key, values in parse_qs(parsed.query).items()
                    }
                    result = coach_facts(
                        ws,
                        params.get("league", "all"),
                        params.get("period", "today"),
                        limit=None,
                        selection_count=int(
                            params.get(
                                "count",
                                ws.config.get("selection", {}).get("default_count", 3),
                            )
                        ),
                    )
                    selected = {
                        (r["division"], r["event_id"])
                        for r in result["selection"]["rows"]
                        if r["selected"]
                    }
                    payload = json.dumps(
                        {
                            "matches": [
                                {
                                    "event_id": r["event_id"],
                                    "name": r["match"],
                                    "domestic_form": r.get("domestic_form"),
                                }
                                for r in result["matches"]
                            ],
                            "selection": result["selection"],
                            "preview": [
                                r
                                for r in result["matches"]
                                if (r["division"], r["event_id"]) in selected
                            ],
                        },
                        ensure_ascii=False,
                    ).encode()
                elif parsed.path == "/chat":
                    from .chat import page as chat_page

                    payload = chat_page(token).encode()
                elif parsed.path == "/chat.js":
                    from .chat import SCRIPT

                    payload = SCRIPT.encode()
                elif parsed.path == "/api/chat/options":
                    from .chat import models, claude_status
                    from .leagues import LEAGUES
                    from .team import ROLES
                    from .shortlist import validate_count

                    payload = json.dumps(
                        {
                            "models": models(),
                            "claude": claude_status(),
                            "roles": [
                                {"role": r, "name": v[0]}
                                for r, v in ROLES.items()
                                if r in ws.config["agents"]["enabled"]
                            ],
                            "selection_default_count": validate_count(
                                ws.config.get("selection", {}).get("default_count", 3)
                            ),
                            "leagues": [
                                {"code": k, "name": v[0]} for k, v in LEAGUES.items()
                            ],
                        },
                        ensure_ascii=False,
                    ).encode()
                elif parsed.path == "/":
                    if ws.path("data/league-hub.json").exists():
                        from .hub_dashboard import page as hub_page

                        params = {
                            key: values[-1]
                            for key, values in parse_qs(parsed.query).items()
                        }
                        payload = hub_page(ws, params, token).encode()
                    else:
                        payload = page(ws).encode()
                else:
                    payload = json.dumps(summary(ws), ensure_ascii=False).encode()
            except ValueError:
                self.send_error(400, "Invalid request or workspace data")
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                (
                    "image/svg+xml"
                    if parsed.path == "/icon.svg"
                    else (
                        "text/javascript; charset=utf-8"
                        if parsed.path in ("/chat.js", "/dashboard.js")
                        else (
                            "text/html; charset=utf-8"
                            if parsed.path in ("/", "/chat")
                            else "application/json"
                        )
                    )
                ),
            )
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            host = self.headers.get("Host", "")
            if host.split(":")[0] not in (
                "127.0.0.1",
                "localhost",
            ) or not secrets.compare_digest(
                self.headers.get("X-Prono-Token", ""), token
            ):
                self.send_error(403)
                return
            if self.headers.get("Origin") not in (None, "http://" + host):
                self.send_error(403)
                return
            if self.path not in (
                "/api/chat",
                "/api/refresh",
                "/api/tracking",
                "/api/evaluation",
            ):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 100_000:
                    raise ValueError("Message trop volumineux ou vide.")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Une demande JSON structurée est requise.")
                if self.path == "/api/evaluation":
                    result = evaluation_jobs.start(
                        body.get("league", "all"), body.get("mode", "snapshot")
                    )
                elif self.path == "/api/tracking":
                    from .tracking import tick

                    if body.get("action") not in ("capture", "results"):
                        raise ValueError("Action de suivi inconnue.")
                    if not operation_lock.acquire(blocking=False):
                        raise ValueError("Une mise à jour est déjà en cours.")
                    try:
                        result = tick(ws, refresh=body["action"] == "results")
                    finally:
                        operation_lock.release()
                elif self.path == "/api/chat":
                    from .chat import reply
                    from .team import explicit_team_request

                    if body.get("mode") not in (None, "coach", "team"):
                        raise ValueError("Mode d’analyse inconnu.")
                    if body.get("mode") == "team" or explicit_team_request(
                        body["message"]
                    ):
                        result = {"job_id": team_jobs.start(body)}
                    else:
                        previous = (
                            team_jobs.receipts(body["last_team_run"])
                            if body.get("last_team_run")
                            else []
                        )
                        result = reply(
                            ws,
                            body["message"],
                            body.get("model", ""),
                            body.get("history"),
                            body.get("league", "all"),
                            body.get("provider", "local"),
                            body.get("period", "today"),
                            previous,
                            body.get("event_id"),
                            body.get("selection_count"),
                            body.get("event_ids"),
                        )
                else:
                    from .leagues import LEAGUES, sync_leagues
                    from .market_watch import sync_markets

                    league = body.get("league", "all")
                    if league != "all" and league not in LEAGUES:
                        raise ValueError("Championnat inconnu.")
                    if not operation_lock.acquire(blocking=False):
                        raise ValueError("Une mise à jour est déjà en cours.")
                    try:
                        if body["action"] == "markets":
                            facts = sync_markets(ws)
                            end = facts.get("domestic", {}).get("end", "J+3")
                            failures = len(facts.get("issues", []))
                            result = {
                                "message": f"Calendrier actualisé, championnats chargés jusqu’au {end} : {facts['matches']} rencontres et {facts['offers']} triplets de cotes publiques. {failures} source(s) en échec ; détail dans Couverture & sources. Heure de cotation inconnue : observation uniquement."
                            }
                        elif body["action"] == "xg":
                            from .understat import LEAGUES as XG_LEAGUES, sync_xg
                            from .leagues import EUROPE

                            if league != "all" and league not in XG_LEAGUES and league not in EUROPE:
                                raise ValueError("Cette compétition n’est pas couverte par Understat. Choisir un grand championnat couvert ou Toutes les compétitions.")
                            facts = sync_xg(ws, None if league == "all" or league in EUROPE else [league])
                            failed = sum(r["status"] == "error" for r in facts["imports"])
                            result = {"message": f"xG Understat : {len(facts['imports']) - failed} import(s) réussi(s), {failed} en échec. Saison courante et précédente ; contexte descriptif uniquement.", "understat": facts}
                        elif body["action"] == "history":
                            facts = sync_leagues(
                                ws, codes=None if league == "all" else [league]
                            )
                            failed = sum(
                                v["status"] == "error"
                                for v in facts["leagues"].values()
                            )
                            result = {
                                "message": f"Historiques mis à jour. {failed} import(s) en échec ; consulter Couverture & sources."
                            }
                        else:
                            raise ValueError("Opération inconnue.")
                        from .tracking import tick

                        if body["action"] != "xg":
                            result["tracking"] = tick(ws)
                    finally:
                        operation_lock.release()
                payload = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                payload = json.dumps({"error": str(exc)}, ensure_ascii=False).encode()
                self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        from .tracking import start_worker

        stop = start_worker(ws, operation_lock)
        print(f"Dashboard : http://127.0.0.1:{port} — Ctrl+C pour arrêter.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
