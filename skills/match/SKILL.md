---
name: match
description: "Analyser un match football 1N2 à partir des données locales et archiver le résultat."
---

Appliquer `AGENTS.md`. Résoudre le match avec `list_fixtures`, sans inventer l'identifiant.
Utiliser `analyze_match` ou `prono analyze ID --save`.
Afficher les probabilités et comparaisons seulement si `model.available` vaut true.
Si `status` vaut `stale_odds` ou `insufficient_data`, expliquer l'abstention.
Sinon préciser le modèle non calibré, les absences/compositions manquantes et l'observation paper.
Coordonner les spécialistes activés conformément à `agents/coach.md`.
Les arrondis sont destinés à l'affichage ; conserver les valeurs précises de l'outil dans le bloc JSON.

Pour une analyse complète, suivre aussi `skills/news/SKILL.md` puis lire le dossier
avec `prono context ID`. Croiser les avis activés, y compris expert bookmaker et effectif.
La recherche de contexte reste utile si les cotes sont bloquées, sans lever le blocage.
