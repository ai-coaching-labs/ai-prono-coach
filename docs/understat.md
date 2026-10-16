# xG Understat : contexte descriptif

Collecte explicite uniquement, sans abonnement : bouton « Actualiser les xG · Understat »
dans le coach, ou `prono sync-xg`. Les lectures de discussion et consultations ne font
aucun appel Understat. Le bouton ne capture pas de nouvelles prévisions.

Couverture intégrée : F1 (Ligue 1), E0 (Premier League), D1 (Bundesliga), I1 (Serie A)
et SP1 (Liga). Pour une coupe UEFA, ces xG nationaux enrichissent le contexte des
clubs couverts ; aucune couverture xG de la coupe elle-même n’est revendiquée.

Par défaut : saison courante et précédente. Années de début explicites possibles
depuis 2014, suivant la disponibilité du site :

```sh
.venv/bin/python -m prono.cli sync-xg --leagues F1 --seasons 2026 2025
.venv/bin/python -m prono.cli sync-xg --leagues F1 --seasons 2014
```

Les captures sont dans `data/xg/understat/` : matches source, xG normalisés, URL,
année de saison, date réelle de collecte et empreinte de contenu. Les captures
identiques réutilisent leur date de première connaissance. Une correction produit
une nouvelle capture sans retirer l’ancienne. À date d’analyse donnée, seuls les
états collectés strictement avant cette date sont utilisés. Deux captures contradictoires
au même instant rendent le périmètre concerné indisponible ; les erreurs sont affichées.
Aucune date n’est inférée depuis les noms de fichiers, résultats ou années de saison.

Le flux public utilisé par le site ne précise pas le fuseau de ses dates naïves.
Elles restent dans `provider_datetime`, sans coup d’envoi UTC inventé. Une borne
conservatrice égale au début UTC de la date fournisseur plus deux jours exclut
le jour courant et la veille des résumés. C’est une règle d’admissibilité, pas
l’heure prétendue de la rencontre. La date de collecte reste également obligatoire.
Les matchs non terminés ou sans xG ne participent pas aux bilans.

`understat_xg` transmis aux modèles contient les totaux et moyennes Python pour
5/10 matchs, 5 à domicile et 5 à l’extérieur, effectifs, avertissements de couverture
ou d’ancienneté, sources et dates de connaissance. Trois rencontres détaillées
au plus sont transmises par équipe pour contenir le volume de contexte ; les
captures complètes restent conservées. Les correspondances de clubs sont exactes
ou explicitement définies, sans rapprochement flou. Les noms inconnus ou ambigus
restent indisponibles.

Les prévisions propres à Understat éventuellement présentes dans le brut ne sont
pas fournies aux modèles de langage. Les xG observés ne sont pas les buts attendus
de `poisson-baseline-v1` : ni modèle, ni paramètres, ni probabilités, ni évaluations
historiques ou prévisions déjà archivées ne sont ajustés. Une variante quantitative
avec xG exigerait une étude distincte et une décision explicite.

Validation réelle du 15 octobre 2026 : collecte des saisons 2025 et 2026 sur les
cinq championnats, plus Ligue 1 2014 ; 11 captures et 2 429 rencontres terminées
avec xG, calculées par les outils. Ces données anciennes sont collectées aujourd’hui,
sans revendication de connaissance historique. L’accès repose sur la route JSON
publique utilisée par le site, non sur une API contractuelle : une évolution ou un
refus HTTP produit une erreur explicite en conservant les captures existantes.
Source : https://understat.com/ ; exemple de saison : https://understat.com/league/Ligue_1/2014

Vérification : 184 tests passent dans la .venv, dont les dates strictes, corrections,
réutilisation des captures, erreurs réseau, import de saisons historiques, contexte
local sans réseau, probabilités inchangées, protection HTTP et cache des agents.
Le rendu HTML servi est contrôlé par le test HTTP ; syntaxe JavaScript et shell valides.
