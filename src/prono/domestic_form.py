"""Forme nationale descriptive pour les coupes UEFA ; aucun ajustement du modèle."""

import unicodedata
from collections import defaultdict
from datetime import timedelta
from .identity import team_resolver
from .leagues import LEAGUES, EUROPE, league_workspace
from .model import load_history
from .workspace import timestamp


def normalized(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


# Correspondances explicites ESPN → Football-Data. Jamais de recherche floue.
ALIASES = {
    "F1": {
        "AS Monaco": "Monaco",
        "Paris Saint-Germain": "Paris SG",
        "Stade Rennais": "Rennes",
        "AJ Auxerre": "Auxerre",
        "Le Havre AC": "Le Havre",
    },
    "E0": {
        "AFC Bournemouth": "Bournemouth",
        "Brighton & Hove Albion": "Brighton",
        "Manchester City": "Man City",
        "Manchester United": "Man United",
        "Hull City": "Hull",
        "Ipswich Town": "Ipswich",
        "Leeds United": "Leeds",
        "Newcastle United": "Newcastle",
        "Nottingham Forest": "Nott'm Forest",
    },
    "D1": {
        "Bayer Leverkusen": "Leverkusen",
        "Borussia Dortmund": "Dortmund",
        "SC Freiburg": "Freiburg",
        "TSG Hoffenheim": "Hoffenheim",
        "VfB Stuttgart": "Stuttgart",
        "Eintracht Frankfurt": "Ein Frankfurt",
        "Borussia Mönchengladbach": "M'gladbach",
    },
    "I1": {"AC Milan": "Milan", "AS Roma": "Roma", "Internazionale": "Inter"},
    "SP1": {
        "Atlético Madrid": "Ath Madrid",
        "Atletico Madrid": "Ath Madrid",
        "Real Betis": "Betis",
        "Real Sociedad": "Sociedad",
        "Celta Vigo": "Celta",
        "Athletic Club": "Ath Bilbao",
        "Rayo Vallecano": "Vallecano",
    },
    "N1": {
        "Ajax Amsterdam": "Ajax",
        "Feyenoord Rotterdam": "Feyenoord",
        "FC Twente": "Twente",
        "NEC Nijmegen": "Nijmegen",
    },
    "B1": {
        "KAA Gent": "Gent",
        "Sint-Truidense": "St Truiden",
        "Union St.-Gilloise": "St. Gilloise",
    },
    "P1": {"FC Porto": "Porto", "Sporting CP": "Sp Lisbon", "Braga": "Sp Braga"},
    "G1": {"AEK Athens": "AEK", "Olympiacos": "Olympiakos"},
    "SC0": {"Heart of Midlothian": "Hearts"},
}
LINKS = {
    normalized(alias): (LEAGUES[code][1], normalized(target))
    for code, aliases in ALIASES.items()
    for alias, target in aliases.items()
}


def window(matches, size):
    chosen = matches[:size]
    n = len(chosen)
    wins = sum(r["result"] == "W" for r in chosen)
    draws = sum(r["result"] == "D" for r in chosen)
    return {
        "requested": size,
        "played": n,
        "wins": wins,
        "draws": draws,
        "losses": n - wins - draws,
        "points": 3 * wins + draws,
        "points_per_match": (3 * wins + draws) / n if n else None,
        "goals_for": sum(r["goals_for"] for r in chosen),
        "goals_against": sum(r["goals_against"] for r in chosen),
        "sequence_oldest_first": " ".join(r["result"] for r in reversed(chosen)),
    }


class DomesticForm:
    def __init__(self, ws, as_of):
        self.as_of = timestamp(as_of)
        settings = ws.config.get("form", {})
        self.max_days = int(settings.get("max_history_days", 180))
        self.stale_days = int(settings.get("stale_after_days", 21))
        if self.max_days < 1 or self.stale_days < 1:
            raise ValueError("Fenêtre de forme invalide.")
        self.clubs = defaultdict(list)
        self.errors = []
        for code in LEAGUES:
            if code in EUROPE:
                continue
            try:
                child = league_workspace(ws, code)
                rows = load_history(child.path("data/history.csv"))
                resolve = team_resolver(ws, code)
                for row in rows:
                    if (
                        timestamp(row["kickoff"]) >= self.as_of
                        or timestamp(row["result_known_at"]) >= self.as_of
                    ):
                        continue
                    for venue, other in (("home", "away"), ("away", "home")):
                        key = (LEAGUES[code][1], resolve(row[venue]))
                        scored = row[venue + "_goals"]
                        conceded = row[other + "_goals"]
                        self.clubs[key].append(
                            {
                                "division": code,
                                "competition": LEAGUES[code][0],
                                "event_id": row["event_id"],
                                "kickoff": row["kickoff"],
                                "opponent": row[other],
                                "venue": venue,
                                "goals_for": scored,
                                "goals_against": conceded,
                                "result": (
                                    "W"
                                    if scored > conceded
                                    else "D" if scored == conceded else "L"
                                ),
                                "source": row["source"],
                                "result_known_at": row["result_known_at"],
                                "synthetic": row["source"] == "synthetic-demo",
                            }
                        )
            except (ValueError, OSError) as exc:
                self.errors.append({"division": code, "reason": str(exc)})

    def team(self, name, kickoff):
        cutoff = min(self.as_of, timestamp(kickoff))
        base = {
            "team": name,
            "as_of": cutoff.isoformat(),
            "available": False,
            "warnings": [],
            "notice": "Statistiques descriptives des matchs de championnat chargés ; probabilités UEFA inchangées.",
        }
        key = LINKS.get(normalized(name))
        if key is None:
            candidates = [k for k in self.clubs if k[1] == normalized(name)]
            if len(candidates) != 1:
                return {
                    **base,
                    "reason": (
                        "Club non relié à un championnat chargé."
                        if not candidates
                        else "Identité nationale ambiguë."
                    ),
                }
            key = candidates[0]
        lower = cutoff - timedelta(days=self.max_days)
        rows = [
            r
            for r in self.clubs.get(key, [])
            if lower <= timestamp(r["kickoff"]) < cutoff
            and timestamp(r["result_known_at"]) < cutoff
        ]
        unique = {}
        for row in sorted(
            rows,
            key=lambda r: (timestamp(r["kickoff"]), r["division"], r["event_id"]),
            reverse=True,
        ):
            identity = (
                timestamp(row["kickoff"]),
                normalized(row["opponent"]),
                row["venue"],
            )
            before = unique.get(identity)
            if before and (before["goals_for"], before["goals_against"]) != (
                row["goals_for"],
                row["goals_against"],
            ):
                return {
                    **base,
                    "reason": "Résultats nationaux contradictoires pour une même rencontre.",
                }
            if before is None:
                unique[identity] = row
        rows = list(unique.values())
        if not rows:
            return {
                **base,
                "reason": f"Aucun résultat national connu dans les {self.max_days} derniers jours.",
            }
        age = (cutoff - timestamp(rows[0]["kickoff"])).total_seconds() / 86400
        warnings = []
        if len(rows) < 10:
            warnings.append(
                f"Échantillon partiel : {len(rows)} matchs sur 10 demandés."
            )
        if age > self.stale_days:
            warnings.append(
                f"Dernier résultat chargé ancien : {age:.0f} jours ; forme actuelle à revérifier."
            )
        if any(r["synthetic"] for r in rows):
            warnings.append("Données SYNTHÉTIQUES.")
        return {
            **base,
            "available": True,
            "country": key[0],
            "canonical_team": key[1],
            "divisions": sorted({r["division"] for r in rows}),
            "warnings": warnings,
            "window_days": self.max_days,
            "last_match_age_days": age,
            "stale": age > self.stale_days,
            "latest_kickoff": rows[0]["kickoff"],
            "days_from_last_domestic_match_to_fixture": (
                timestamp(kickoff) - timestamp(rows[0]["kickoff"])
            ).total_seconds()
            / 86400,
            "last5": window(rows, 5),
            "last10": window(rows, 10),
            "home_last5": window([r for r in rows if r["venue"] == "home"], 5),
            "away_last5": window([r for r in rows if r["venue"] == "away"], 5),
            "matches_newest_first": rows[:10],
            "sources": sorted({r["source"] for r in rows[:10]}),
            "synthetic": any(r["synthetic"] for r in rows),
        }

    def match(self, fixture):
        return {
            "home": self.team(fixture["home"], fixture["kickoff"]),
            "away": self.team(fixture["away"], fixture["kickoff"]),
            "load_issues": self.errors,
            "notice": "Forme nationale séparée du modèle européen. Force des adversaires non corrigée ; pas de comparaison directe de niveau entre championnats. Les jours depuis le dernier match national ne mesurent pas le repos toutes compétitions.",
        }
