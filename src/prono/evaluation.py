"""Comparaison chronologique de variantes expérimentales et suivi de calibration."""

import hashlib
import random
from collections import defaultdict
from datetime import timedelta
from .workspace import utcnow, timestamp, write_record, read_record
from .model import load_history, predict_rows, OUTCOMES, HistoryWindow
from .metrics import performance, score
from .leagues import LEAGUES, league_workspace

VARIANTS = {
    "poisson-baseline-v1": {},
    "poisson-recency-research-v1": {"half_life_days": 180},
    "dc-correction-research-v1": {"half_life_days": 180, "correction": True},
}
NOTICE = (
    "Étude rétrospective sur une capture actuelle des résultats : les anciennes dates de publication "
    "ne sont pas connues. En mode archives, l’entraînement utilise uniquement des matchs commencés "
    "au moins 24 h avant le match évalué, avec leurs résultats finaux aujourd’hui collectés. "
    "Ce délai est une hypothèse de recherche, pas une date de connaissance reconstituée. "
    "Les dates originales de connaissance sont conservées. Aucun rendement de pari évalué ; les écarts de scores ne prouvent pas un avantage exploitable."
)


def paired_interval(predictions, baseline):
    """Rééchantillonnage de semaines entières pour ne pas traiter chaque match comme indépendant."""
    groups = defaultdict(list)
    for r, b in zip(predictions, baseline):
        day = timestamp(r["kickoff"]).date()
        week = day - timedelta(days=day.weekday())
        groups[str(week)].append(
            score(r["probabilities"], r["actual"])["brier"]
            - score(b["probabilities"], b["actual"])["brier"]
        )
    if len(groups) < 5:
        return {
            "delta_brier": None,
            "lower": None,
            "upper": None,
            "blocks": len(groups),
            "notice": "Trop peu de semaines pour cet intervalle.",
        }
    blocks = list(groups.values())
    rng = random.Random(20261010)
    values = []
    for _ in range(300):
        sample = [v for _ in blocks for v in rng.choice(blocks)]
        values.append(sum(sample) / len(sample))
    values.sort()
    all_values = [v for block in blocks for v in block]
    return {
        "delta_brier": sum(all_values) / len(all_values),
        "lower": values[7],
        "upper": values[292],
        "blocks": len(blocks),
        "notice": "Intervalle descriptif à 95 % par bootstrap de semaines, 300 tirages ; ne valide aucune rentabilité.",
    }


def evaluate_league(
    ws, mode="snapshot", now=None, archived_forecasts=(), resolve=lambda x: x
):
    if mode not in ("snapshot", "observed"):
        raise ValueError("Mode attendu : snapshot ou observed.")
    now = now or utcnow()
    path = ws.path("data/history.csv")
    history = load_history(path)
    history = sorted(
        [
            r
            for r in history
            if timestamp(r["result_known_at"]) <= now and timestamp(r["kickoff"]) < now
        ],
        key=lambda r: timestamp(r["kickoff"]),
    )
    window = HistoryWindow(history)
    n = len(history)
    start = timestamp(history[min(n - 1, int(n * 0.8))]["kickoff"]) if n else None
    targets = [r for r in history if timestamp(r["kickoff"]) >= start] if start else []
    predictions = {v: [] for v in [*VARIANTS, "league-frequency"]}
    skipped = 0
    for row in targets:
        cutoff = window.kickoff_times[id(row)]
        eligible = window.eligible(cutoff, ws.config["model"]["max_history_days"], mode)
        forecasts = {
            v: predict_rows(
                eligible,
                row["home"],
                row["away"],
                cutoff,
                ws.config["model"],
                kickoff_times=window.kickoff_times,
                **parameters,
            )
            for v, parameters in VARIANTS.items()
        }
        if not all(f["available"] for f in forecasts.values()):
            skipped += 1
            continue
        actual = (
            "home"
            if row["home_goals"] > row["away_goals"]
            else "away" if row["home_goals"] < row["away_goals"] else "draw"
        )
        base = {
            "event_id": row["event_id"],
            "kickoff": row["kickoff"],
            "actual": actual,
            "training_rows": len(eligible),
            "training_latest_kickoff": max(r["kickoff"] for r in eligible),
        }
        for v, f in forecasts.items():
            predictions[v].append(
                {
                    **base,
                    "probabilities": f["probabilities"],
                    "parameters": f.get("parameters", {}),
                }
            )
        counts = {k: 1 for k in OUTCOMES}
        for r in eligible:
            counts[
                (
                    "home"
                    if r["home_goals"] > r["away_goals"]
                    else "away" if r["home_goals"] < r["away_goals"] else "draw"
                )
            ] += 1
        predictions["league-frequency"].append(
            {
                **base,
                "probabilities": {
                    k: v / sum(counts.values()) for k, v in counts.items()
                },
            }
        )
    models = {
        v: {
            **performance(rows),
            "comparison": paired_interval(rows, predictions["poisson-baseline-v1"]),
        }
        for v, rows in predictions.items()
    }
    from .market_evaluation import historical_quotes, compare_historical_market

    quotes = historical_quotes(ws, archived_forecasts)
    market = compare_historical_market(
        ws, window, targets, VARIANTS, mode, now, quotes, resolve
    )
    return {
        "market_comparison": market,
        "quotes_sha256": quotes_digest(quotes),
        "history_rows": n,
        "target_count": len(targets),
        "skipped": skipped,
        "test_start": start.isoformat() if start else None,
        "mode": mode,
        "models": models,
        "predictions": predictions,
        "history_sha256": (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        ),
        "synthetic": any(r["source"] == "synthetic-demo" for r in history),
        "method": "Derniers 20 % des matchs, groupes de coup d’envoi conservés ; ré-estimation sur le passé uniquement.",
        "notice": (
            NOTICE
            if mode == "snapshot"
            else "Connaissance strictement antérieure au coup d’envoi. Variantes expérimentales, sans promotion automatique."
        ),
        "production_model": "poisson-baseline-v1",
        "promoted": False,
        "model_config": dict(ws.config["model"]),
        "variant_notes": "Récence : demi-vie fixée à 180 jours. Correction de type Dixon–Coles : rho ajusté sur les seuls scores passés ; forces régularisées de la baseline, pas un ajustement joint complet du modèle original.",
    }


def evaluate(ws, codes=None, mode="snapshot", save=True, now=None, progress=None):
    now = now or utcnow()
    codes = codes or ws.config.get("evaluation", {}).get("leagues", ["F1", "F2", "E0"])
    if not codes or any(c not in LEAGUES for c in codes):
        raise ValueError("Championnat inconnu.")
    from .tracking import forecasts
    from .identity import team_resolver

    archived = forecasts(ws)
    results = {}
    for code in dict.fromkeys(codes):
        if progress:
            progress(code)
        try:
            results[code] = evaluate_league(
                league_workspace(ws, code),
                mode,
                now,
                [f for f in archived if f["division"] == code],
                team_resolver(ws, code),
            )
        except (ValueError, OSError) as exc:
            results[code] = {"error": str(exc)}
    result = {
        "created_at": now.isoformat(),
        "mode": mode,
        "leagues": results,
        "production_model": "poisson-baseline-v1",
        "promoted": False,
        "notice": (
            NOTICE
            if mode == "snapshot"
            else "Évaluation stricte selon les dates de connaissance enregistrées."
        ),
    }
    if save:
        path = ws.path("rapports/" + now.strftime("%Y%m%dT%H%M%S%f") + "_evaluation.md")
        write_record(path, "model_comparison", result)
        result["saved_to"] = str(path)
    return result


def quotes_digest(quotes):
    import json

    return hashlib.sha256(
        json.dumps(quotes, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def latest_evaluation(ws):
    paths = sorted(ws.path("rapports").glob("*_evaluation.md"))
    if not paths:
        return None
    report = read_record(paths[-1])
    from .tracking import forecasts
    from .market_evaluation import historical_quotes

    archived = forecasts(ws)
    current = {}
    for code, result in report["leagues"].items():
        try:
            child = league_workspace(ws, code)
            path = child.path("data/history.csv")
            digest = (
                hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            )
            reasons = []
            if result.get("model_config") != child.config["model"]:
                reasons.append(
                    "Paramètres différents ou non enregistrés dans cette étude."
                )
            if result.get("history_sha256") != digest:
                reasons.append("Historique modifié depuis cette étude.")
            if result.get("quotes_sha256") is not None:
                quotes = historical_quotes(
                    child, [f for f in archived if f["division"] == code]
                )
                if result["quotes_sha256"] != quotes_digest(quotes):
                    reasons.append("Captures de cotes modifiées depuis cette étude.")
            if result.get("error"):
                reasons.append("Étude en erreur.")
            current[code] = {"current": not reasons, "reasons": reasons}
        except (OSError, ValueError) as exc:
            current[code] = {"current": False, "reasons": [str(exc)]}
    report["currency"] = current
    report["not_evaluated"] = [
        code
        for code, (_, _, slug) in LEAGUES.items()
        if ws.path("data/workspaces/" + slug + "/data/history.csv").exists()
        and code not in report["leagues"]
    ]
    return report


class EvaluationJobs:
    def __init__(self, ws):
        import threading

        self.ws = ws
        self.lock = threading.Lock()
        self.state = {"status": "idle"}

    def get(self):
        import json

        with self.lock:
            return json.loads(json.dumps(self.state))

    def start(self, league="all", mode="snapshot"):
        import threading

        if league != "all" and league not in LEAGUES:
            raise ValueError("Championnat inconnu.")
        if mode not in ("snapshot", "observed"):
            raise ValueError("Mode inconnu.")
        with self.lock:
            if self.state["status"] == "running":
                raise ValueError("Une évaluation est déjà en cours.")
            self.state = {"status": "running", "mode": mode, "league": league}

        def progress(code):
            with self.lock:
                self.state["current_league"] = code

        def work():
            try:
                result = evaluate(
                    self.ws,
                    None if league == "all" else [league],
                    mode,
                    progress=progress,
                )
                with self.lock:
                    self.state.update(status="completed", saved_to=result["saved_to"])
            except Exception as exc:
                with self.lock:
                    self.state.update(
                        status="error",
                        error=(
                            str(exc)
                            if isinstance(exc, (ValueError, OSError))
                            else "Erreur d’évaluation."
                        ),
                    )

        threading.Thread(target=work, daemon=True, name="prono-evaluation").start()
        return self.get()
