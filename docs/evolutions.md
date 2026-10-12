# Évolutions fonctionnelles

## Forme nationale et contenu des prestations · 0.3.5

Les analyses UEFA reçoivent aussi les 5 et 10 derniers matchs de championnat chargés,
les buts pour/contre, les bilans domicile/extérieur et les dates/sources de chaque résultat.
Les clubs sont reliés par noms exacts ou correspondances explicites (Inter/Internazionale,
Manchester United/Man United…) ; un club inconnu ou ambigu reste indisponible.
Le bilan est limité à 180 jours et signale le dernier résultat ancien de plus de 21 jours.
Il apparaît dans le chat et les cartes de pronos ; les consultations l'archivent avec leurs faits.

Le journaliste est chargé de lire les comptes rendus des trois dernières prestations,
les déclarations de l'entraîneur et les nouvelles d'effectif. L'analyste confronte ce contenu
et la forme nationale au choix statistique, avec les sources et les contradictions.
Sans consultation avec accès web, aucun compte rendu n'est annoncé comme lu.
La baseline reste propre à la coupe : ce contexte ne change pas les probabilités Python
ni le pré-tri et ne constitue pas un modèle validé mêlant les championnats.

## Sélection automatique expliquée · 0.3.4

La consultation ne prend plus les trois premiers matchs chronologiques. Python examine
toute la période et trie avant la limite de 30 fiches détaillées du chat. Par défaut, il
exige un choix à au moins 50 %, un écart d’au moins 10 points avec la deuxième issue,
au moins huit matchs par équipe sur les deux dernières années et un dernier résultat
historique dans les 180 derniers jours. Ces seuils de pré-tri sont configurables dans
`[selection]` et ne constituent pas une validation du modèle.

Les candidats fictifs avec cotes vérifiées et espérance théorique positive passent
d’abord, par espérance décroissante. Les autres rencontres admissibles sont des
observations, triées par probabilité Python, écart puis échantillon récent. L’heure ne
sert qu’à départager. Les cotes indicatives n’autorisent aucun classement par rentabilité.

Le chat affiche la liste proposée, les critères et les exclusions avant de lancer les
agents. On peut demander de un à cinq matchs ; une liste insuffisante n’est pas remplie
avec des choix faibles. Un match manuel reste possible et conserve ses avertissements.
La règle, les rangs et les exclusions sont archivés avec chaque nouvelle consultation et
restitués dans ses traces serveur. Les anciennes archives ne sont pas réécrites.

Ce pré-tri sert à choisir les matchs à approfondir. Les spécialistes consultent uniquement
ce périmètre et le coach peut écarter un choix après leurs avis sourcés. Aucun combiné
optimal ni probabilité jointe n’est calculé. Aucun appel au modèle n’est fait par l’aperçu.

## Championnats nationaux sur cinq ans · 0.3.3

Les 22 championnats chargent les saisons 2021/22 à début 2026/27 et utilisent au maximum
1826 jours de résultats connus avant le calcul. Les coupes UEFA conservent leur fenêtre
propre. L’import sans liste explicite de saisons suit les réglages `[domestic]` et `[europe]` :

```bash
.venv/bin/python -m prono.cli sync-leagues
```

L’historique reste conservé dans le CSV de chaque compétition. Changer la fenêtre ne
remplace pas les anciens pronos gelés. La profondeur et les décomptes récents sont envoyés
au coach. Les anciens fichiers Football-Data en Windows-1252 sont lus sans remplacement
de caractères, avec conservation de leurs octets originaux et de leur empreinte.

## Coupes d’Europe · 0.3.3

La Ligue des champions (UCL), la Ligue Europa (UEL) et la Conference League (UECL)
figurent dans les filtres du dashboard et du chat. Le calendrier et les cotes publiques
ESPN sont importés explicitement, sans clé ni appel à une API payante :

```bash
.venv/bin/python -m prono.cli sync-leagues --leagues UCL UEL UECL
```

L’actualisation habituelle du calendrier inclut les trois coupes. Le mois courant et
le suivant sont chargés ; aucun appel au modèle de langage n’est déclenché. Les captures
UEFA sont conservées dans `data/europe-watch.json` et `data/sources/`, séparément du
calendrier national. Un import en échec conserve les précédentes données et affiche
l’erreur dans Couverture & sources.

Chaque coupe possède son propre historique. L’import automatique de saisons utilise
dix années pour les coupes, depuis 2021/22 pour la Conference League, et conserve
cinq années pour les ligues nationales. `[domestic].history_years` règle leurs saisons
importées ; `[model].max_history_days` vaut 1826 par défaut pour leur calcul. `[europe].history_years` règle les saisons
chargées ; `[europe].max_history_days` règle la fenêtre par défaut des nouveaux
workspaces UEFA. Une clé `[model].max_history_days` dans le fichier utilisateur
d’une coupe prime sur ce défaut. Le dashboard et le coach affichent le total ainsi
que les matchs des deux dernières années ; les effectifs anciens participent aux
calculs de la baseline, sans amélioration de fiabilité démontrée.
Les CSV sont dans `data/workspaces/ucl/data/history.csv`, `uel` et `uecl`.

Les résultats restent séparés par compétition. Seuls les résultats ESPN confirmés à
90 minutes sont acceptés : scores après prolongation, tirs au but, rencontres en cours
ou heures incertaines sont exclus. Les résultats sont connus à leur collecte, sans
antidater leur publication. Les cotes sont des triplets complets du même bookmaker,
convertis depuis le format américain ; l’heure de cotation reste inconnue.

La baseline Poisson reste exploratoire pour ces coupes ; elle s’abstient si les équipes
n’ont pas assez de résultats dans cette compétition. Les données nationales ne servent
pas à combler ce manque et aucune simulation n’est proposée sur ces cotes indicatives.

