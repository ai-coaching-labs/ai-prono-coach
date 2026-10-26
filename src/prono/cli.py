import argparse
import json
import sys
from pathlib import Path
from .workspace import Workspace, write_record, utcnow


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="prono", description="AI Prono Coach — analyses et journal fictif locaux"
    )
    p.add_argument(
        "--workspace", default=".", help="Racine du workspace (avant la sous-commande)"
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("doctor")
    sub.add_parser("demo")
    sub.add_parser("fixtures")
    today = sub.add_parser(
        "today", help="Briefing des matchs du jour, sans appel réseau"
    )
    today.add_argument("--timezone", help="Fuseau IANA, par défaut celui du workspace")
    today.add_argument(
        "--save", action="store_true", help="Archiver le point dans rapports/"
    )
    a = sub.add_parser("analyze")
    a.add_argument("event_id")
    a.add_argument("--save", action="store_true")
    sub.add_parser("backtest")
    track = sub.add_parser(
        "track",
        help="Archiver les prévisions pré-match et associer les résultats chargés",
    )
    track.add_argument(
        "--refresh-results",
        action="store_true",
        help="Vérifier les résultats publics des matchs suivis",
    )
    ts = sub.add_parser(
        "tracking", help="Bilan des prévisions réellement archivées avant match"
    )
    ts.add_argument("--league", default="all")
    ev = sub.add_parser(
        "evaluate", help="Comparer localement les variantes expérimentales"
    )
    ev.add_argument("--leagues", nargs="+")
    ev.add_argument("--mode", choices=["snapshot", "observed"], default="snapshot")
    ev.add_argument("--no-save", action="store_true")
    sl = sub.add_parser(
        "schedule-link",
        help="Confirmer explicitement un report ambigu entre deux captures",
    )
    sl.add_argument("previous_id")
    sl.add_argument("current_id")
    sub.add_parser("summary")
    combos = sub.add_parser("combinés", aliases=["accumulators"], help="Proposer des doubles et triples fictifs, sans écriture ni réseau")
    combos.add_argument("--budget", type=float, required=True)
    combos.add_argument("--league", default="all")
    combos.add_argument("--period", choices=["today", "next3"], default="today")
    combos.add_argument("--format", dest="ticket_mode", choices=["auto", "doubles", "triples"], default="auto")
    combos.add_argument("--indicative", action="store_true", help="Explorer les cotes disponibles sans valider de mise")
    sub.add_parser("report")
    sub.add_parser("sync-odds")
    history = sub.add_parser(
        "sync-history", help="Télécharger explicitement les résultats de Ligue 1"
    )
    history.add_argument("--seasons", nargs="+", required=True)
    leagues = sub.add_parser(
        "sync-leagues",
        help="Importer les divisions nationales et les coupes d’Europe séparément",
    )
    leagues.add_argument(
        "--seasons",
        nargs="+",
        help="Par défaut : archives récentes nationales et profondeur configurée des coupes d’Europe",
    )
    leagues.add_argument(
        "--markets",
        action="store_true",
        help="Inclure le calendrier et les cotes publiques indicatives",
    )
    leagues.add_argument(
        "--leagues", nargs="+", help="Limiter aux codes indiqués, par exemple F1 F2 E0"
    )
    sub.add_parser(
        "sync-markets",
        help="Collecter une fois les cotes publiques, sans horodatage de cotation garanti",
    )
    europe = sub.add_parser(
        "sync-europe",
        help="Importer explicitement le calendrier et les cotes des trois coupes d’Europe",
    )
    europe.add_argument("--leagues", nargs="+", choices=["UCL", "UEL", "UECL"])
    europe.add_argument(
        "--seasons",
        nargs="+",
        help="Importer aussi les résultats à 90 minutes des saisons indiquées",
    )
    xg = sub.add_parser("sync-xg", help="Collecter explicitement les xG publics Understat")
    xg.add_argument("--leagues", nargs="+", choices=["F1", "E0", "D1", "I1", "SP1"])
    xg.add_argument("--seasons", nargs="+", type=int, help="Années de début ; saison courante et précédente par défaut")
    ci = sub.add_parser("context-import", help="Archiver un dossier pré-match sourcé")
    ci.add_argument("file", type=Path)
    context = sub.add_parser("context", help="Lire les dossiers sourcés d'un match")
    context.add_argument("event_id")
    ih = sub.add_parser("import-history")
    ih.add_argument("file", type=Path)
    iff = sub.add_parser("import-fixtures")
    iff.add_argument("file", type=Path)
    b = sub.add_parser("paper-add")
    b.add_argument("event_id")
    b.add_argument("outcome", choices=["home", "draw", "away"])
    b.add_argument("--note", default="")
    s = sub.add_parser("paper-settle")
    s.add_argument("id")
    s.add_argument("result", choices=["win", "loss", "void"])
    chat = sub.add_parser("ask")
    chat.add_argument("question")
    chat.add_argument(
        "--event", help="Ajouter une analyse déterministe au contexte du coach"
    )
    chat.add_argument("--dry-run", action="store_true")
    ui = sub.add_parser("ui")
    ui.add_argument("--port", type=int, default=8766)
    sub.add_parser("mcp")
    args = p.parse_args(argv)
    try:
        ws = Workspace(args.workspace)
        from .analysis import fixtures, analyze, save_analysis, backtest
        from .journal import summary, add_paper, settle

        if args.command == "init":
            for folder in ("data", "journal", "analyses", "rapports", "memory"):
                ws.path(folder).mkdir(exist_ok=True)
            profile = ws.path("memory/Player_Profile.md")
            if not profile.exists():
                profile.write_text(
                    "# Profil\n\n- Objectif : comprendre les probabilités et tester en fictif\n- Sport : football\n- Marché : 1N2\n- Préférences : réponses concises en français\n",
                    encoding="utf-8",
                )
            result = {"workspace": str(ws.root), "mode": "paper", "initialized": True}
        elif args.command == "doctor":
            from .model import load_history

            result = {
                "python": sys.version.split()[0],
                "history_rows": len(load_history(ws.path("data/history.csv"))),
                "fixtures": len(fixtures(ws)),
                "paper": summary(ws),
                "llm": ws.config["llm"]["backend"],
            }
        elif args.command == "demo":
            from .demo import seed

            result = seed(ws)
        elif args.command in ("combinés", "accumulators"):
            from .accumulators import propose

            result = propose(ws, args.budget, args.period, args.league, ticket_mode=args.ticket_mode,
                             allow_indicative=args.indicative)
        elif args.command == "fixtures":
            result = fixtures(ws)
        elif args.command == "today":
            from .briefing import daily_briefing, save_briefing

            result = daily_briefing(ws, timezone_name=args.timezone)
            if args.save:
                result["saved_to"] = str(save_briefing(ws, result))
        elif args.command == "analyze":
            result = analyze(ws, args.event_id)
            if args.save:
                result["saved_to"] = str(save_analysis(ws, result))
        elif args.command == "backtest":
            result = backtest(ws)
        elif args.command == "track":
            from .tracking import tick

            result = tick(ws, refresh=args.refresh_results)
        elif args.command == "tracking":
            from .tracking import tracking_summary

            result = tracking_summary(ws, args.league)
        elif args.command == "evaluate":
            from .evaluation import evaluate

            result = evaluate(ws, args.leagues, args.mode, not args.no_save)
        elif args.command == "schedule-link":
            from .identity import link_schedule

            result = link_schedule(ws, args.previous_id, args.current_id, utcnow())
        elif args.command == "summary":
            result = summary(ws)
        elif args.command == "paper-add":
            result = add_paper(ws, args.event_id, args.outcome, args.note)
        elif args.command == "paper-settle":
            result = settle(ws, args.id, args.result)
        elif args.command == "sync-odds":
            from .providers import sync_odds

            result = sync_odds(ws)
        elif args.command == "sync-history":
            from .history_import import sync_history

            result = sync_history(ws, args.seasons)
        elif args.command == "sync-xg":
            from .understat import sync_xg

            result = sync_xg(ws, args.leagues, args.seasons)
        elif args.command == "sync-leagues":
            from .leagues import sync_leagues

            result = sync_leagues(ws, args.seasons, args.markets, args.leagues)
        elif args.command == "sync-markets":
            from .market_watch import sync_markets

            result = sync_markets(ws)
        elif args.command == "sync-europe":
            from .europe import sync_europe

            result = sync_europe(ws, args.leagues)
            if args.seasons:
                from .leagues import sync_leagues, EUROPE

                result["history"] = sync_leagues(
                    ws, args.seasons, codes=args.leagues or list(EUROPE)
                )
        elif args.command == "context-import":
            from .context import import_context

            result = import_context(
                ws, json.loads(args.file.read_text(encoding="utf-8"))
            )
        elif args.command == "context":
            from .context import contexts

            result = contexts(ws, args.event_id)
        elif args.command == "import-history":
            from .model import load_history
            from .workspace import atomic_write

            if not args.file.is_file():
                raise ValueError("Fichier historique introuvable.")
            rows = load_history(args.file)
            if not rows:
                raise ValueError("Historique vide.")
            atomic_write(
                ws.path("data/history.csv"), args.file.read_text(encoding="utf-8-sig")
            )
            result = {"imported": len(rows), "destination": "data/history.csv"}
        elif args.command == "import-fixtures":
            from .analysis import validate_fixture
            from .workspace import atomic_write

            rows = json.loads(args.file.read_text())
            if not isinstance(rows, list):
                raise ValueError("Liste JSON attendue.")
            for row in rows:
                validate_fixture(row)
            if len({r["event_id"] for r in rows}) != len(rows):
                raise ValueError("Match dupliqué.")
            atomic_write(
                ws.path("data/fixtures.json"),
                json.dumps(rows, ensure_ascii=False, indent=2),
            )
            result = {"imported": len(rows), "destination": "data/fixtures.json"}
        elif args.command == "report":
            facts = summary(ws)
            when = utcnow()
            path = ws.path(f"rapports/{when.strftime('%Y-%m-%d_%H%M%S')}_bilan.md")
            text = (
                f"## Bilan fictif\n\nSolde : {facts['balance']:.2f} unités. Résultat net : {facts['net_pnl']:+.2f} unités.\n\n"
                f"Paris clôturés : {facts['settled_count']}. Paris ouverts : {facts['open_count']}.\n\n"
                "Un historique court ne permet pas de conclure à une rentabilité. Aucune mise réelle recommandée."
            )
            write_record(
                path, "report", {"created_at": when.isoformat(), "summary": facts}, text
            )
            result = {"report": str(path), "summary": facts}
        elif args.command == "ask":
            facts = summary(ws)
            if args.event:
                facts = {"summary": facts, "analysis": analyze(ws, args.event)}
            if args.dry_run:
                result = {
                    "sent_if_requested": {"question": args.question, "summary": facts},
                    "backend": ws.config["llm"]["backend"],
                    "network_called": False,
                }
            else:
                from .providers import ask

                print(
                    "Réponse générée par IA — vérifier les chiffres dans prono summary.\n"
                )
                print(ask(ws, args.question, facts))
                return 0
        elif args.command == "ui":
            from .dashboard import serve

            serve(ws, args.port)
            return 0
        elif args.command == "mcp":
            from .mcp_server import run

            run(ws.root)
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
