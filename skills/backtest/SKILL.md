---
name: backtest
description: "Évaluer chronologiquement les probabilités du modèle football et leurs limites."
---

Appliquer `AGENTS.md`. Appeler `model_evaluation` ou `prono backtest`.
Lire le nombre de prédictions réellement évaluées, les exclusions, Brier, log loss et baseline.
Expliquer qu'une baseline uniforme est faible ; une comparaison aux probabilités du marché reste à faire.
Le ROI n'est pas évalué sans cotes historiques pré-match datées. Ne pas annoncer une rentabilité.
Sur données synthétiques : démonstration du pipeline seulement, pas validation du modèle.

Pour une comparaison demandée, `prono evaluate --leagues F1 F2 E0` archive une étude
rétrospective locale ; `--mode observed` applique les dates de connaissance strictes.
Lire le mode et les hypothèses avant de commenter les scores. Ne jamais présenter
le mode archives comme une preuve de disponibilité historique. Lire `prono tracking`
pour les prévisions réellement enregistrées avant match. Aucune promotion automatique
ni interprétation d'un intervalle de score comme une confiance de pari.
