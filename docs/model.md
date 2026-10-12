# Baseline statistique

Objectif V1 : montrer une chaîne déterministe et auditable, pas vendre un modèle gagnant.

1. À l'instant de cotation, sélectionner les matchs dont le coup d'envoi ET la connaissance
du résultat sont strictement antérieurs. Conserver la fenêtre `max_history_days`.
2. Estimer les moyennes de buts domicile/extérieur du championnat, régularisées par
10 pseudo-matchs à 1,4 et 1,1 buts. Ces constantes sont des priors techniques non calibrés.
3. Estimer attaque et défense de chaque équipe sur ses matchs domicile et extérieur,
avec `prior_matches` de régularisation vers la moyenne du championnat.
4. Combiner attaque/défense et moyenne domicile/extérieur pour les buts attendus ;
borner les intensités à [0,05 ; 8]. Modéliser les buts comme deux Poisson indépendants.
5. Sommer les scores 0–40 pour produire 1N2 puis normaliser la masse restante.

Le minimum de matchs par équipe vaut 8, configurable. Noms inconnus ou historique
insuffisant : aucune probabilité. Le modèle n'est pas ajusté sur des matchs futurs.
Il ignore blessures, compositions, xG, force du calendrier, changements de division,
dépendance des scores et récence pondérée. Un grand échantillon ne supprime pas ces biais.

## Comparaison au marché

Pour chaque issue, probabilité implicite brute = `1/cote`.
Marge totale = `somme(1/cote) - 1`.
Normalisation proportionnelle hors marge = `(1/cote)/somme(1/cote)`.
Espérance estimée par unité = `p_modèle*cote - 1`.

Ces valeurs sont mathématiques mais leur intérêt dépend de la fiabilité du `p_modèle`.
La normalisation proportionnelle n'est pas la vraie probabilité d'une issue.
Aucun seuil ne transforme cette baseline en recommandation de mise réelle.

## Évaluation

Walk-forward strict, prévision à chaque coup d'envoi, seulement les résultats déjà connus.
Métriques : Brier multiclasse **somme sur les trois classes**, puis moyenne par match
(plage [0 ; 2]), et log loss en logarithme naturel. Baseline uniforme à 1/3 par issue.
La V1 ne comporte ni calibration, ni intervalles de confiance, ni ROI de backtest sans
cotes historiques. Les statistiques du journal paper proviennent des choix de l'utilisateur,
pas d'une stratégie automatique. Le drawdown est celui du solde clôturé, hors risque ouvert.


## Étude des variantes, version 0.3

La production conserve `poisson-baseline-v1`. La grille 0–40 est calculée en réutilisant
les masses Poisson : les probabilités restent équivalentes à la formule précédente.

Le mode `evaluate --mode observed` applique la connaissance strictement antérieure.
Le mode `snapshot` étudie des résultats aujourd'hui collectés, avec 24 h d'embargo
entre les matchs d'entraînement et le match cible. Il ne modifie aucune date de
connaissance et ne prouve pas la disponibilité historique. Les captures peuvent
contenir des corrections ultérieures ; cette limite est conservée dans le rapport.

Les paramètres sont fixés avant le test : demi-vie de 180 jours pour la récence ;
rho recherché sur [-0,15 ; 0,15] par pas de 0,01 sur les seuls scores d'entraînement
pour la correction de petits scores. Celle-ci applique les facteurs de type Dixon–Coles
aux scores 0–0, 0–1, 1–0 et 1–1. Les forces restent celles de la baseline régularisée ;
ce n'est pas un ajustement joint complet de tous les paramètres du modèle original.

Les derniers 20 % des matchs, groupés par coup d'envoi, constituent le test. Tous les
modèles sont évalués sur les mêmes rencontres calculables. Les écarts Brier utilisent
un bootstrap de semaines entières, 300 tirages avec graine fixe ; la calibration est
une table descriptive en cinq groupes par issue. Petits échantillons et regroupements
limitent l'interprétation. Il n'y a ni probabilité automatiquement recalibrée, ni
promotion automatique, ni preuve de profitabilité.

Références : [Dixon et Coles, 1997](https://doi.org/10.1111/1467-9876.00065),
[Dimitriadis, Gneiting et Jordan, calibration](https://arxiv.org/abs/2008.03033).

La fenêtre nationale par défaut est de cinq ans (1826 jours) depuis la version 0.3.3.
Les coupes UEFA gardent leur réglage séparé. Le décompte des deux dernières années est
affiché à côté du total ; augmenter la fenêtre ne démontre pas une meilleure précision.
Les nouvelles études enregistrent leur configuration pour distinguer leurs paramètres
de ceux du modèle utilisé aujourd’hui.


## Contexte national des coupes UEFA, version 0.3.5

`domestic_form` est un bilan descriptif indépendant du modèle : fenêtres des 5/10 derniers
résultats nationaux chargés dans les 180 jours, et 5 derniers à domicile/extérieur.
Le coup d'envoi et `result_known_at` doivent être strictement antérieurs au minimum de
l'instant d'analyse et du match cible. Sources et connaissance sont conservées dans les
faits archivés des consultations. Identités exactes ou aliases explicites, sans correspondance
floue ; pays ambigus et résultats contradictoires sont indisponibles. Changements de division
visibles dans le bilan ; force des adversaires et écarts entre ligues non corrigés.
Plus de 21 jours depuis le dernier résultat chargé déclenche un avertissement, sans prétendre
qu'il s'agit du dernier match réellement joué. Les jours entre ce match et la rencontre UEFA
ne mesurent pas la récupération toutes compétitions. Les dates de première connaissance
et les prévisions déjà gelées restent inchangées.

La forme et les comptes rendus lus par le journaliste servent à discuter ou écarter un choix,
jamais à modifier intuitivement les probabilités. Une nouvelle probabilité intégrant plusieurs
ligues et la récence nécessiterait une variante mesurée et validée séparément.
