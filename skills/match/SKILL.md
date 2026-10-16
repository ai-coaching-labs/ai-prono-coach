---
name: match
description: "Analyser un match football 1N2 à partir des données locales et archiver le résultat."
---

Appliquer `AGENTS.md`. Résoudre le match avec `list_fixtures`, sans inventer l'identifiant.
Dans le chat Équipe IA, tous les rôles et le coach reçoivent seulement le contexte
descriptif filtré par le serveur. Ne pas leur transmettre le résultat complet de
`analyze_match` ou `prono analyze` avant le verdict indépendant.
Pour une explication explicitement demandée d’un calcul, utiliser ces commandes ;
cette lecture ne doit pas être présentée comme un nouveau pronostic aveugle.
Afficher les probabilités et comparaisons seulement si `model.available` vaut true.
Si `status` vaut `stale_odds` ou `insufficient_data`, expliquer le blocage de simulation.
Un historique insuffisant pour Python n’interdit pas un pronostic sportif qualitatif
1/N/2 et une confiance motivée à partir de faits sourcés. L’absence de calcul seule
ne justifie pas une abstention sportive ; ne pas inventer les probabilités, scores Python ou BTTS Python.
Un score envisagé LLM compatible avec son pronostic reste possible, comme hypothèse
qualitative explicitement étiquetée, sans probabilité inventée.
Sinon préciser le modèle non calibré, les absences/compositions manquantes et l'observation paper.
Coordonner les spécialistes activés conformément à `agents/coach.md`.
Les arrondis sont destinés à l'affichage ; conserver les valeurs précises de l'outil dans le bloc JSON.

Pour une analyse complète, suivre aussi `skills/news/SKILL.md` puis lire le dossier
avec `prono context ID`. Croiser les avis activés, y compris expert bookmaker et effectif.
La recherche de contexte reste utile si les cotes sont bloquées, sans lever le blocage.
