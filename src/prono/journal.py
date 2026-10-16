from uuid import uuid4
from .analysis import analyze
from .workspace import write_record, number, utcnow, timestamp
from .model import OUTCOMES


def journal(ws):
    entries = ws.records("journal")
    ids = set()
    for r in entries:
        if r.get("kind") != "paper_bet" or r.get("mode") != "paper" or r["id"] in ids:
            raise ValueError("Journal incohérent.")
        ids.add(r["id"])
        number(r["stake"], 0.000001)
        number(r["odds"], 1.000001)
        if r["outcome"] not in OUTCOMES or r["status"] not in ("open", "settled"):
            raise ValueError("État du journal invalide.")
        if r["status"] == "settled":
            expected = (
                r["stake"] * (r["odds"] - 1)
                if r["result"] == "win"
                else -r["stake"] if r["result"] == "loss" else 0
            )
            if (
                r["result"] not in ("win", "loss", "void")
                or abs(expected - r["pnl"]) > 1e-8
            ):
                raise ValueError("Résultat du journal incohérent.")
    return entries


def summary(ws):
    entries = sorted(journal(ws), key=lambda r: r.get("settled_at", r["created_at"]))
    settled = [r for r in entries if r["status"] == "settled"]
    opened = [r for r in entries if r["status"] == "open"]
    pnl = sum(r["pnl"] for r in settled)
    total_staked = sum(r["stake"] for r in settled if r["result"] != "void")
    initial = float(ws.config["paper"]["starting_balance"])
    equity = peak = initial
    dd = 0
    for r in settled:
        equity += r["pnl"]
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    groups = {}
    for r in settled:
        g = groups.setdefault(r["outcome"], {"count": 0, "pnl": 0.0})
        g["count"] += 1
        g["pnl"] += r["pnl"]
    exposure = sum(r["stake"] for r in opened)
    return {
        "mode": "paper",
        "initial_balance": initial,
        "balance": initial + pnl,
        "available_balance": initial + pnl - exposure,
        "open_exposure": exposure,
        "open_count": len(opened),
        "settled_count": len(settled),
        "net_pnl": pnl,
        "roi": pnl / total_staked if total_staked else None,
        "max_drawdown_units": dd,
        "by_outcome": groups,
        "notice": "Simulation fictive, sans argent réel. Le ROI observé ne démontre pas un avantage futur.",
    }


def add_paper(ws, event_id, outcome, note=""):
    if outcome not in OUTCOMES:
        raise ValueError("Issue attendue : home, draw ou away.")
    result = analyze(ws, event_id)
    if result["status"] != "analysis_only":
        raise ValueError(
            "Simulation refusée : cotes périmées ou historique insuffisant."
        )
    if any(r["event_id"] == event_id for r in journal(ws)):
        raise ValueError("Un pari fictif existe déjà pour ce match.")
    stats = summary(ws)
    stake = float(ws.config["paper"]["unit"])
    if stats["available_balance"] < stake or stats["open_exposure"] + stake > float(
        ws.config["paper"]["max_open_exposure"]
    ):
        raise ValueError("Limite de simulation atteinte.")
    ident = uuid4().hex
    record = {
        "id": ident,
        "mode": "paper",
        "created_at": utcnow().isoformat(),
        "event_id": event_id,
        "kickoff": result["fixture"]["kickoff"],
        "outcome": outcome,
        "stake": stake,
        "odds": result["fixture"]["odds"][outcome],
        "quoted_at": result["fixture"]["quoted_at"],
        "source": result["fixture"]["source"],
        "bookmaker": result["fixture"]["bookmaker"],
        "status": "open",
        "note": note,
        "forecast": result["model"],
    }
    write_record(ws.path(f"journal/{ident}.md"), "paper_bet", record)
    return record


def settle(ws, ident, result):
    if result not in ("win", "loss", "void"):
        raise ValueError("Résultat attendu : win, loss ou void.")
    matches = [r for r in journal(ws) if r["id"] == ident]
    if len(matches) != 1:
        raise ValueError("Pari fictif introuvable.")
    r = matches[0]
    if r["status"] != "open":
        raise ValueError("Résultat déjà enregistré : aucune modification silencieuse.")
    if result != "void" and utcnow() < timestamp(r["kickoff"]):
        raise ValueError("Impossible d'enregistrer un résultat avant le coup d'envoi.")
    r.update(
        status="settled",
        result=result,
        settled_at=utcnow().isoformat(),
        pnl=(
            r["stake"] * (r["odds"] - 1)
            if result == "win"
            else -r["stake"] if result == "loss" else 0
        ),
    )
    write_record(
        ws.path(f"journal/{ident}.md"),
        "paper_bet",
        r,
        "Résultat saisi manuellement ; non vérifié auprès d'un fournisseur sportif.",
    )
    return r
