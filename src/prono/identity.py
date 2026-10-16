"""Identités locales explicites ; aucune correspondance floue entre noms de clubs."""

import hashlib
import json
import unicodedata
from collections import Counter
from .workspace import timestamp, atomic_write


def team_resolver(ws, division):
    path = ws.path("data/team-aliases.json")
    aliases = json.loads(path.read_text()) if path.exists() else {}
    mapping = aliases.get(division, {})
    if not isinstance(mapping, dict):
        raise ValueError("Table de noms de clubs invalide.")

    def resolve(name):
        text = " ".join(unicodedata.normalize("NFKC", name).strip().casefold().split())
        target = mapping.get(text, text)
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Nom canonique de club invalide.")
        return " ".join(
            unicodedata.normalize("NFKC", target).strip().casefold().split()
        )

    return resolve


def canonical_team(ws, division, name):
    return team_resolver(ws, division)(name)


def team_id(ws, division, name):
    return (
        "club-"
        + hashlib.sha256(
            (division + "|" + canonical_team(ws, division, name)).encode()
        ).hexdigest()[:20]
    )


def pair(ws, division, row):
    return (
        division,
        team_id(ws, division, row["home"]),
        team_id(ws, division, row["away"]),
    )


def register_matches(ws, capture):
    """Garder l'identifiant initial lors d'un report non ambigu avant le coup d'envoi."""
    path = ws.path("data/match-registry.json")
    registry = (
        json.loads(path.read_text())
        if path.exists()
        else {"schema_version": 1, "matches": {}}
    )
    entries = registry["matches"]
    now = timestamp(capture["collected_at"])
    previous_path = ws.path("data/market-watch.json")
    previous = (
        json.loads(previous_path.read_text()).get("matches", [])
        if previous_path.exists()
        else []
    )
    for old in previous:
        if old["event_id"] not in entries:
            entries[old["event_id"]] = {
                **old,
                "pair": list(pair(ws, old["division"], old)),
                "source_ids": [old["event_id"]],
                "schedule_revisions": [],
            }
    incoming = capture["matches"]
    counts = Counter(pair(ws, r["division"], r) for r in incoming)
    raw_ids = {r["event_id"] for r in incoming}
    used = set()
    for row in incoming:
        raw_id = row["event_id"]
        key = pair(ws, row["division"], row)
        exact = [
            (ident, e)
            for ident, e in entries.items()
            if not e.get("linked_to")
            and tuple(e["pair"]) == key
            and timestamp(e["kickoff"]) == timestamp(row["kickoff"])
        ]
        # Un ancien match déjà commencé n'est jamais fusionné automatiquement avec une autre rencontre.
        candidates = [
            (ident, e)
            for ident, e in entries.items()
            if not e.get("linked_to")
            and tuple(e["pair"]) == key
            and timestamp(e["kickoff"]) > now
            and ident not in raw_ids
            and ident not in used
        ]
        chosen = (
            exact[0]
            if len(exact) == 1
            else (
                candidates[0]
                if not exact and counts[key] == 1 and len(candidates) == 1
                else None
            )
        )
        if chosen:
            ident, entry = chosen
            if timestamp(entry["kickoff"]) != timestamp(row["kickoff"]):
                entry["schedule_revisions"].append(
                    {
                        "previous_kickoff": entry["kickoff"],
                        "kickoff": row["kickoff"],
                        "observed_at": capture["collected_at"],
                        "source": row["source"],
                    }
                )
            if raw_id not in entry["source_ids"]:
                entry["source_ids"].append(raw_id)
        else:
            ident = raw_id
            entry = {
                "pair": list(key),
                "source_ids": [raw_id],
                "schedule_revisions": [],
            }
            if len(exact) > 1 or candidates:
                row["identity_warning"] = (
                    "Correspondance de calendrier ambiguë : nouvelle identité conservée."
                )
        row.update(
            event_id=ident,
            source_event_id=raw_id,
            home_id=key[1],
            away_id=key[2],
            schedule_revisions=list(entry["schedule_revisions"]),
        )
        entry.update(row)
        entries[ident] = entry
        used.add(ident)
    atomic_write(path, json.dumps(registry, ensure_ascii=False, indent=2))
    return capture


def freshness(row, now, max_hours=6):
    quoted = row.get("quoted_at")
    collected = row.get("collected_at")
    if quoted:
        age = (now - timestamp(quoted)).total_seconds() / 3600
        return (
            "Cote future invalide"
            if age < 0
            else "Cote récente" if age <= max_hours else "Cote ancienne"
        )
    if not collected:
        return "Collecte inconnue · cotation inconnue"
    age = (now - timestamp(collected)).total_seconds() / 3600
    return (
        "Collecte future invalide"
        if age < 0
        else ("Collecte récente" if age <= max_hours else "Collecte ancienne")
        + " · cotation inconnue"
    )


def price_changes(previous, current):
    """Différences de captures, sans prétendre connaître les heures de cotation."""
    old = {r["event_id"]: r for r in previous}
    result = []
    for row in current:
        before = old.get(row["event_id"])
        if not before:
            continue
        bookmakers = {o["bookmaker"]: o["odds"] for o in before.get("offers", [])}
        for offer in row.get("offers", []):
            odds = bookmakers.get(offer["bookmaker"])
            if odds and odds != offer["odds"]:
                result.append(
                    {
                        "event_id": row["event_id"],
                        "bookmaker": offer["bookmaker"],
                        "previous": odds,
                        "current": offer["odds"],
                        "previous_collected_at": before.get("collected_at"),
                        "collected_at": row.get("collected_at"),
                        "notice": "Variation entre captures publiques ; heure de cotation inconnue.",
                    }
                )
    return result


def link_schedule(ws, previous_id, current_id, now):
    """Confirmation explicite d'un report ambigu ; historique et prévisions restent intacts."""
    if previous_id == current_id:
        raise ValueError("Deux identifiants distincts sont requis.")
    path = ws.path("data/match-registry.json")
    registry = json.loads(path.read_text())
    entries = registry["matches"]
    if previous_id not in entries or current_id not in entries:
        raise ValueError("Match absent du registre.")
    old, new = entries[previous_id], entries[current_id]
    if old["pair"] != new["pair"]:
        raise ValueError("Clubs ou championnat différents : association refusée.")
    if timestamp(new["kickoff"]) <= now:
        raise ValueError("Confirmer le report avant le nouveau coup d’envoi.")
    revision = {
        "previous_kickoff": old["kickoff"],
        "kickoff": new["kickoff"],
        "observed_at": now.isoformat(),
        "source": new["source"],
        "confirmation": "manual",
    }
    entries[previous_id] = {
        **new,
        "event_id": previous_id,
        "source_ids": list(dict.fromkeys(old["source_ids"] + new["source_ids"])),
        "schedule_revisions": old["schedule_revisions"] + [revision],
    }
    entries[current_id]["linked_to"] = previous_id
    atomic_write(path, json.dumps(registry, ensure_ascii=False, indent=2))
    watch_path = ws.path("data/market-watch.json")
    watch = json.loads(watch_path.read_text())
    for row in watch["matches"]:
        if row["event_id"] == current_id:
            row["event_id"] = previous_id
            row["schedule_revisions"] = entries[previous_id]["schedule_revisions"]
    atomic_write(watch_path, json.dumps(watch, ensure_ascii=False, indent=2))
    return {
        "event_id": previous_id,
        "linked_source_event": current_id,
        "revision": revision,
    }
