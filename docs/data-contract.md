# Contrat de données V1

Tous les horodatages sont ISO 8601 avec fuseau explicite. UTC est recommandé.
Les sources doivent être non vides. Un seul championnat par workspace ; cette cohérence
métier est à vérifier par l'importateur. Aucun alias d'équipe automatique.

## Résultats — CSV

```csv
event_id,kickoff,home,away,home_goals,away_goals,result_known_at,source
match-001,2026-09-01T18:00:00Z,Équipe A,Équipe B,2,1,2026-09-01T20:15:00Z,mon-fournisseur
```

`event_id` unique. Scores entiers 0–30. `result_known_at` est le moment auquel ce résultat
était réellement accessible au système, pas simplement l'heure estimée de fin du match.
Importer des données tardivement sans connaissance historique vérifiable limite la portée
du backtest : ne pas inventer un horodatage de disponibilité.

## Matchs et cotes — JSON

```json
[
  {
    "event_id": "match-002",
    "kickoff": "2026-10-20T18:00:00Z",
    "home": "Équipe A",
    "away": "Équipe B",
    "quoted_at": "2026-10-20T16:00:00Z",
    "source": "mon-fournisseur",
    "bookmaker": "bookmaker-id",
    "odds": {"home": 2.10, "draw": 3.40, "away": 3.30}
  }
]
```

Trois cotes décimales finies strictement supérieures à 1 ; même bookmaker, même instant.
Cet exemple n'est pas une rencontre réelle. Les analyses doivent être pré-match ; les
cotes futures sont refusées, les cotes trop anciennes empêchent la simulation.

## Markdown — source de vérité

Les outils écrivent un bloc `prono` JSON : `schema_version = 1`, `kind` parmi `analysis`,
`paper_bet`, `report`, `daily_briefing`, `match_context`. Le texte libre peut enrichir l'explication sous le bloc sans modifier
les valeurs. Une analyse embarque le match, les cotes, les probabilités et les limites.
Un pari fictif embarque sa prédiction initiale, unité, cote, source et statut ; son règlement
ajoute résultat, P&L et date. Ne pas recopier ces données vers une base concurrente.
