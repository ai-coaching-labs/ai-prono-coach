# App Mac et chat intégré

Le fichier `dist/AI-Prono-Coach-0.3.10.dmg` contient **AI Prono Coach.app**
et un raccourci Applications. Glisser l’app vers Applications, l’ouvrir,
choisir le dossier de travail puis cliquer « Préparer mon coach ».
La version locale n’est pas notarisée par Apple.

## Prérequis

- macOS 13+ ; exécutable universel Apple Silicon et Intel.
- Python 3.11+ à un emplacement standard (python.org ou Homebrew).
- Pour le coach local : Ollama démarré avec un modèle local installé.
- Pour Claude : Claude Code récent installé et compte connecté. Le chat utilise
  cette connexion, selon les limites et la facturation du compte configuré.

La préparation extrait le moteur dans `~/Library/Application Support/AI Prono Coach`
et installe son environnement Python privé ainsi que le SDK MCP depuis PyPI.
Les agents, skills et configurations sont créés dans le dossier choisi ; les fichiers
existants sont conservés. Le DMG ne contient aucune donnée sportive personnelle,
aucun journal, profil, secret ou configuration de compte.

L’app lance son dashboard sur `127.0.0.1`, avec un port libre à chaque démarrage ; le projet en développement
utilise le port 8876. Le bouton d’import suit les profondeurs configurées (cinq ans pour les ligues nationales, dix pour les coupes UEFA) et
le calendrier public. Le suivi des prévisions est actif pendant l’ouverture du dashboard. Les résultats
publics des seuls matchs suivis sont vérifiés après le match, au plus une fois par heure
et par championnat. Les mises à jour de cotes et les appels IA nécessitent une demande.

L’actualisation charge aussi le calendrier national jusqu’à J+3 depuis ESPN,
car le fichier de calendrier Football-Data peut ne contenir que des matchs passés.
Le statut distingue les historiques et les sources de calendrier en échec, et
indique le nombre de rencontres nationales chargées jusqu’à J+3. Le filtre
« Les 3 prochains jours » affiche demain à J+3, sans y ajouter les matchs d’aujourd’hui.

## Coach dans le navigateur et dans l’app

Ouvrir `/chat` ou cliquer « Parler au coach ». Le sélecteur **Coach** propose :

- **Local · Ollama** : explications avec les faits chargés, sans recherche web.
- **Claude · Claude Code** : réponse directement dans la même interface. Les seuls
  outils du chat Claude sont WebSearch et WebFetch pour les nouvelles publiques.
  Les probabilités restent les résultats Python ; la recherche ne les modifie pas.
  L’extrait transmis inclut les cotes enregistrées par bookmaker et leurs dates
  disponibles, pour au maximum 30 matchs de la période et du championnat sélectionnés.
  Choisir « Aujourd’hui » ou « Demain à J+3 », puis « Analyser avec les spécialistes ».
  Le coach présente les pronos et leurs raisons avec une courte mention des limites.
  Le détail des simulations est réservé aux demandes de simulation. Le dashboard
  montre le choix sportif du modèle séparément de l’éligibilité fictive.

À l’envoi vers Claude, le message, les derniers échanges de ce coach et un extrait
calculé des matchs/dossiers lui sont transmis. La vérification de connexion ne renvoie
au navigateur ni adresse e-mail, ni organisation, ni identifiants. Les conversations
Local et Claude sont distinctes et restent en mémoire dans l’onglet ; recharger
l’onglet les efface. Aucun appel au modèle n’a lieu à l’ouverture de la page.

Dans le Coach, **Mes analyses enregistrées** permet de rechercher une équipe et
de rouvrir une consultation, classée par date. Le verdict, la question et les avis
spécialisés proviennent des archives `analyses/team-<id>.md`, y compris après un
redémarrage. Cette lecture ne relance pas l’IA et ne recalcule pas les probabilités.
La date et la consommation de l’analyse initiale restent affichées. Les erreurs
archivées sont consultables sans créer de verdict manquant. L’adresse de la page
ouverte permet de revenir à cette consultation sur le même serveur local.
Les simples échanges de chat sans consultation d’équipe restent en mémoire seulement.

L’analyse **Équipe IA** consulte les spécialistes activés dans des appels séparés au
modèle choisi, puis le coach. Elle montre l’avancement et chaque avis, y compris les
échecs ; le serveur archive les faits et les rapports dans `analyses/team-<id>.md`.
Le journaliste intervient avant l’analyste sportif ; un expert effectifs distinct peut être ajouté sur demande ou en mode complet. Les avis
ne changent pas les probabilités Python. Un match choisi ou un pré-tri de un à cinq matchs
est traité par consultation. Toute la période est examinée avant de retenir les rencontres.
L’aperçu expose les critères et les exclusions avant tout appel à l’IA. Le mode adapté sélectionne les rôles utiles ; le mode
complet peut appeler les huit rôles. Les avis web sourcés récents sont réutilisables
avec leur date affichée ; « Rechercher à nouveau » force des consultations nouvelles. Claude peut utiliser
son quota pour la recherche publique ; Ollama reste sans outils web. Les suivis
réutilisent les traces serveur sans relancer l’équipe. Aucun shell ni outil d’écriture
n’est donné au modèle. Pour actualiser, utiliser les boutons. Le menu **Outils → Claude Code** de l’app ouvre
une conversation terminal dans le workspace, avec les agents et skills installés,
pour les workflows plus complets. L’onglet Équipe décrit les rôles configurés ; les
traces du chat indiquent ceux qui ont effectivement rendu un avis.

Le pont du chat utilise le mode non interactif documenté par
[Claude Code](https://code.claude.com/docs/en/cli-reference), en mode restreint,
sans persistance de session, sans shell et sans serveur MCP dans cette conversation.
L’intégration MCP installée reste disponible dans la conversation terminal séparée.

## Construire le DMG

Sur GitHub, la fusion sur `main` lance les contrôles puis la construction du DMG.
Un tag de version publie aussi une release ; voir [la procédure CI et release](ci-release.md).

Depuis le dépôt sur macOS avec les outils de développement Apple :

```bash
bash scripts/build-macos-dmg.sh
```

Chaque compilation utilise un dossier distinct sous `dist`. Après succès, les copies
temporaires de cette compilation sont nettoyées ; l’app et le DMG sont conservés.
La version est lue dans `pyproject.toml`. Un ancien DMG est
archivé avant remplacement. Une identité de signature et un profil de notarisation
peuvent être fournis via `PRONO_CODESIGN_IDENTITY` et `PRONO_NOTARY_PROFILE`.


## Suivi et évaluation

L’onglet **Suivi** et **Outils et données → Évaluation** donnent accès aux prévisions
archivées et aux comparaisons locales. Le suivi nécessite que l'app reste ouverte ;
il peut être désactivé dans `[tracking]` du fichier utilisateur. Le calcul d'évaluation
ne fait aucun appel à un modèle IA. L'étude d'archives est signalée comme rétrospective,
avec une hypothèse d'embargo de 24 h ; elle ne prétend pas connaître les dates anciennes
de publication. Les variantes restent expérimentales.

## Navigation simplifiée

L’app ouvre les pronos. La barre propose Pronos, Suivi et Coach ; les accès
Claude Code, fichiers et sources sont regroupés dans Outils. Dans le tableau,
le calendrier reste accessible au premier niveau. Les résultats, dossiers,
sources et évaluations sont dans « Outils et données ». Le chat conserve la
compétition, la période et le match depuis « Comprendre ce match ».

Le démarrage vérifie la disponibilité du serveur indépendamment des bilans sportifs, puis ouvre automatiquement les pronos. En cas d’échec ou de délai dépassé, un message et le bouton « Réessayer » remplacent l’attente.

## Équipe essentielle

L’analyse approfondie conserve le choix du sélecteur : équipe essentielle par défaut
(journaliste et effectifs, analyste sportif, coach), ou équipe complète explicitement
sélectionnée. Les spécialistes supplémentaires interviennent sur demande précise.


## Verdict et lecture des réponses

Tous les spécialistes et le coach travaillent en aveugle aux sorties Poisson :
choix, probabilités, buts attendus, scores et BTTS du modèle, espérances et critères
du tri sont retirés des données envoyées. La forme, les résultats, les xG observés,
les cotes brutes et les sources restent disponibles. Le tri peut encore déterminer
quels matchs sont consultés ; son classement et ses seuils ne sont pas transmis.

Le coach renvoie un verdict structuré indépendant. Le code vérifie l’issue, la
cohérence du score envisagé et la confiance qualitative, puis construit le tableau
avec les chiffres Python et les mentions d’accord/désaccord. Aucun appel IA
supplémentaire n’est effectué pour comparer ou réparer un format invalide : les
champs non exploitables restent indisponibles. Les archives conservent la réponse
brute du coach, les verdicts validés et les données Python complètes séparément.
Les anciens avis en cache sont invalidés pour ces consultations. Les anciennes
analyses restent inchangées. Les explications ou bilans historiques explicitement
demandés peuvent lire les calculs ; ils ne constituent pas de nouvelles prédictions.
Ce dispositif masque les sorties structurées de l’application ; les textes fournis
par l’utilisateur ou les sources restent susceptibles d’évoquer d’autres pronostics.

Le verdict compact distingue le choix Python et ses probabilités du pronostic final
LLM. Le coach peut soutenir Python, retenir une autre issue 1/N/2 sur des faits
sourcés, ou s’abstenir. Un historique insuffisant pour Python ne bloque pas à lui
seul un avis sportif qualitatif ; les faits doivent permettre une orientation raisonnable.
`draw` signifie match nul, tandis que `null` signifie absence de choix calculable.

Le tableau présente aussi un **score envisagé LLM**, compatible avec son pronostic,
comme hypothèse qualitative, même sans calcul Python. Ce n’est pas un score calculé
ni « le plus probable ». Si les faits ne permettent aucun scénario raisonnable,
il reste indéterminé. Les probabilités, scores Python et BTTS Python indisponibles
ne sont pas inventés. Une divergence entre le scénario LLM et le BTTS Python est signalée.
La confiance **faible/modérée/élevée** est motivée et porte sur l’issue 1/N/2,
pas sur le score exact ; ce n’est ni un pourcentage ni une mesure calibrée.

Les raisons décisives, réserves et sources suivent le tableau. Les rapports détaillés
restent consultables sans être recopiés dans chaque verdict. Le chat rend les tableaux,
listes, gras et liens ; les tableaux larges se parcourent horizontalement. Le HTML
fourni par un modèle n’est pas exécuté et seuls les liens HTTP/HTTPS sont ouverts.

## Comprendre la consommation

Trois rôles sont consultés par défaut, jusqu’à huit en équipe complète. Un appel de
rôle avec recherche web peut comporter plusieurs tours internes ; le texte final
ne représente donc pas toute la consommation. Les compteurs séparent les entrées
hors cache, sorties, lectures de cache et créations de cache rapportées par le
fournisseur. Ils ne calculent pas un prix. Les détails absents sont signalés incomplets.
L’usage reçu est archivé par rôle dans les nouvelles consultations.

Les anciens relevés agrégeaient entrées et cache : ils sont affichés sans ventilation,
sans reconstituer les données manquantes. « Avis réutilisé » désigne le rapport d’un
spécialiste repris d’une consultation précédente ; ce compteur est distinct du cache
que gère le fournisseur du modèle.
