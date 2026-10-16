# Contrat de données V1

Les imports comparent les noms d’équipes en majuscules pour reconnaître une même
rencontre malgré une différence de casse. Les noms, identifiants et dates de première
connaissance déjà enregistrés restent conservés. Un changement de score, d’horaire
ou d’identité d’équipe exige toujours une revue ; les captures sources restent disponibles.

Le calendrier national jusqu’à J+3 est conservé dans `data/domestic-calendar.json`,
séparément des résultats historiques et des cotes horodatées de `fixtures.json`.
La collecte explicite interroge ESPN pour les mois couvrant aujourd’hui à J+3 dans
le fuseau du workspace. Seuls les matchs futurs programmés avec heure confirmée
sont retenus. Les captures brutes sont conservées ; une erreur garde le calendrier
précédent de la compétition et apparaît dans la couverture des sources.
Les correspondances de noms ESPN/Football-Data sont explicites, sans rapprochement
flou. Les cotes restent indicatives et ne débloquent pas les simulations fictives.

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

## Captures dédupliquées

Les nouvelles sources CSV et ESPN sont nommées par empreinte de contenu, par
saison ou période. Un contenu identique réutilise sa capture et conserve la date
de première collecte. Un contenu différent reste archivé, même lorsqu’une
correction de résultat bloque l’import. Aucun ancien fichier n’est supprimé.
Les observations du calendrier conservent leur date de collecte propre ; elle
ne devient jamais une heure de cotation.

## Référence marché dans l’évaluation

Le fichier de fixtures de chaque compétition peut conserver des cotes passées,
au même format que les cotes pré-match, avec un champ `collected_at` supplémentaire :
la date documentée à laquelle le système pouvait accéder à ce triplet. Il faut
`quoted_at <= collected_at < kickoff`. Une date de collecte actuelle ne rend
pas une cote historique disponible avant le match. Sans `collected_at`, cette
cote est exclue de l’étude, même si `quoted_at` est renseigné.

Les prévisions archivées avant match fournissent aussi des cotes lorsqu’elles
sont horodatées ; leur date d’archivage constitue la preuve de disponibilité.
Les résultats sont associés par équipes et coup d’envoi exact, avec seulement
les aliases explicites. Les identifiants de fournisseurs peuvent différer.
Des cotes simultanées contradictoires d’une même source et bookmaker sont exclues.

Pour chaque match de la période de test, la dernière observation valide avant
match est retenue, sans tenir compte du résultat. Les variantes sont recalculées
à cet instant et comparées sur les mêmes matchs. Les statistiques de ce
sous-échantillon sont distinctes de celles de l’étude complète au coup d’envoi.
Les cotes sans horodatage présentes dans les CSV publics ne sont jamais
converties en référence historique horodatée.
