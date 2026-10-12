# App Mac et chat intégré

Le fichier `dist/AI-Prono-Coach-0.3.6.dmg` contient **AI Prono Coach.app**
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

L’app lance son dashboard sur `http://127.0.0.1:8877` ; le projet en développement
utilise le port 8876. Le bouton d’import suit les profondeurs configurées (cinq ans pour les ligues nationales, dix pour les coupes UEFA) et
le calendrier public. Le suivi des prévisions est actif pendant l’ouverture du dashboard. Les résultats
publics des seuls matchs suivis sont vérifiés après le match, au plus une fois par heure
et par championnat. Les mises à jour de cotes et les appels IA nécessitent une demande.

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

L’analyse **Équipe IA** consulte les spécialistes activés dans des appels séparés au
modèle choisi, puis le coach. Elle montre l’avancement et chaque avis, y compris les
échecs ; le serveur archive les faits et les rapports dans `analyses/team-<id>.md`.
Le journaliste intervient avant l’expert effectifs et l’analyste sportif. Les avis
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
