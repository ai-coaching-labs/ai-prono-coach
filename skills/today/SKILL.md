---
name: today
description: "Lister les matchs pré-match déjà chargés avec dates, cotes et fraîcheur."
---

Appliquer `AGENTS.md`. Si MCP répond, utiliser `list_fixtures`, `analyze_match`
pour les matchs pré-match du jour et `paper_summary` ; ne pas inventer un outil de briefing.
Sinon appeler `prono today` : le calcul utilise `[coaching].timezone` (Europe/Paris par défaut).
`--timezone Europe/Paris` permet de choisir le fuseau ; `--save` archive le briefing dans `rapports/`.
Ne pas enregistrer de simulation pendant le briefing. Afficher les prochaines étapes et les limites.
Comparer les coups d'envoi à la date locale utilisateur : un match chargé n'est pas forcément aujourd'hui.
Montrer match, heure avec fuseau, cotes 1N2, source et date de cotation.
Dire si les données sont synthétiques ou périmées. Ne pas appeler une API implicitement.
Sans match chargé, expliquer comment importer des données ou demander explicitement une synchronisation.
