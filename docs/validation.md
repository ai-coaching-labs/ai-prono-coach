# Validation de la livraison V1

## Forme nationale et contenu des prestations 0.3.5 — 12 octobre 2026

- 130 tests réussis sur 131 ; un test MCP ignoré (SDK absent). Bilans 5/10 matchs et domicile/extérieur, alias explicites, promotion, noms ambigus, sources manquantes, doubles résultats/contradictions, données synthétiques et anciennes vérifiés.
- Tests temporels : coup d'envoi et connaissance strictement antérieurs à l'analyse et au match cible ; égalité et futurs exclus ; fenêtre limitée à 180 jours.
- Préparation réelle du contexte et pipeline simulé : forme nationale transmise aux rôles puis archivée, probabilités européennes identiques au calcul antérieur. Aucun appel réel au modèle ni lecture d'article annoncée pendant les tests.
- Les consignes du journaliste couvrent la lecture des trois dernières prestations et des déclarations d'entraîneurs, avec URL/date et réserves. La consigne serveur s'applique aussi aux anciens workspaces conservant leurs prompts locaux.
- Les données nationales chargées des six clubs du pré-tri sont disponibles, mais leurs derniers résultats datent du 19–20 septembre : avertissements de forme ancienne présents. Aucun classement de rentabilité ou ajustement intuitif des probabilités.
- Actualisation ponctuelle publique des six championnats du pré-tri : succès, aucun nouveau résultat ; dates de première connaissance conservées. Aucun appel à une API de cotes.
- Vérification visuelle : bloc de forme national dans le chat, 5/10 résultats de Lens et Sporting, dates anciennes signalées et liste des sources consultable. Aperçu dist/forme-championnat-0.3.5.jpg. Conversation existante conservée ; aucun appel réel à Claude/Ollama ni lecture d’article pendant cette livraison.

- Réutilisation des avis vérifiée : le simple écoulement des secondes conserve le cache ; un nouveau bilan le rend invalide.

## Pré-tri expliqué 0.3.4 — 12 octobre 2026

- 120 tests réussis sur 121 ; 1 MCP ignoré (SDK absent). Rencontre forte après la 30e position, indépendance de l’ordre d’entrée, limites de quantité, données récentes insuffisantes, résultats historiques futurs/trop anciens, probabilités invalides et absence de remplissage forcé vérifiés.
- Le tri ne calcule pas d’espérance sur les cotes indicatives. Les candidats fictifs déjà validés par le moteur constituent un groupe séparé ; les choix manuels sont exacts et conservent leurs exclusions.
- Pipeline de rôles simulé avec préparation réelle : pré-tri complet, périmètre de deux matchs, cinq appels adaptatifs, archivage/restauration de la méthode et des rangs dans les traces vérifiés. Discussion simple avec match manuel également vérifiée.
- Données locales : 54 rencontres, 22 choix calculables, 4 admissibles au filtre. Les trois retenues sont Arsenal/Lille, Inter/Bruges puis Galatasaray/Barcelona ; Atlético/Manchester United est exclu notamment pour son choix sous 50 % et un seul match récent de United dans cette compétition.
- Vérification visuelle du chat : pré-tri de 54 matchs, classement et critères, exclusions détaillées, demande de cinq matchs limitée aux quatre admissibles, choix manuel Atlético avec avertissements, connexion Claude sans envoi. Aperçu conservé dans dist/selection-classee-0.3.4.jpg.
- Aucun appel réel à Claude/Ollama, recherche de nouvelles ou API de cotes payante pendant cette validation. Pré-tri exploratoire, aucun combiné optimal revendiqué.


## Championnats sur cinq ans 0.3.3 — 12 octobre 2026

- 108 tests réussis sur 109 ; 1 MCP ignoré (SDK optionnel absent). Héritage de la fenêtre du hub, priorité utilisateur, connaissance future exclue, première collecte conservée et archivage sans perte des fichiers Windows-1252 vérifiés.
- Import réel des 22 championnats réussi : 40 163 résultats, saisons 2021/22 à début 2026/27. Ligue 1 : 1 723 ; Ligue 2 : 1 813 ; Premier League et Serie A : 1 950 chacune ; Eredivisie : 1 593.
- Fenêtre de 1826 jours dans les 22 workspaces nationaux ; paramètres précédents sauvegardés. Coupes UEFA inchangées à 3653 jours. Aucun prono gelé ni journal remplacé ; aucune date de connaissance antidatée.
- Les études restent datées et la baseline affichée se rapporte à leur calcul ; les nouvelles études enregistrent leurs paramètres. Aucun gain de précision ni rentabilité démontré.
- Dashboard relancé ; tableau Couverture & sources vérifié visuellement : dates d’archives depuis 2021, compte des rencontres et fenêtre de cinq ans par championnat.


## Échantillons UEFA 0.3.2 — 12 octobre 2026

- 106 tests réussis sur 107 ; 1 MCP ignoré (SDK absent). Fenêtre de dix ans, exclusion des connaissances futures, décompte récent, années de saison en hiver, profondeur nationale inchangée et priorité utilisateur vérifiés.
- Historiques locaux : 1 723 résultats UCL, 2 862 UEL, 704 UECL. Archives ESPN et premières dates de connaissance conservées ; aucun ancien prono gelé remplacé.
- Échantillons calculés sur dix ans pour les rencontres du 13 octobre : Arsenal/Lille 44/25 (27/9 récents), Galatasaray/Barcelona 30/95 (12/24 récents), Inter/Bruges 71/65 (23/21 récents).
- Le coach reçoit la profondeur et les décomptes récents (transport de faits testé). Agrandir l’historique ne valide pas le modèle ; les effectifs anciens influencent les probabilités. Aucun appel réel au modèle de langage effectué.
- Dashboard relancé et carte Arsenal/Lille vérifiée visuellement : 44/25 matchs, dont 27/9 récents, fenêtre de dix ans et limite de représentativité affichées.


## Coupes d’Europe 0.3.1 — 12 octobre 2026

- 103 tests réussis sur 104 ; 1 MCP ignoré (SDK absent). Conversion des cotes, triplets incomplets, connaissance non antidatée, résultats futurs, rencontres en cours, prolongations et tirs au but vérifiés.
- Import réel ESPN : 216 rencontres du calendrier, 53 triplets publics ; 1 072 résultats à 90 minutes (389 UCL, 386 UEL, 297 UECL), historiques séparés. 40 résultats hors contrat exclus avec captures conservées.
- Sur les trois prochains jours : 54 rencontres, 10 choix calculables par la baseline ; les autres restent sans choix faute d’historique suffisant. Cotes non horodatées, aucune simulation fictive validée.
- Imports répétés sans changement de première connaissance, conservation des anciennes données après erreur/correction, et calendrier national indépendant des coupes vérifiés. Aucun modèle de langage ni API de cotes payante appelé.
- Dashboard relancé ; filtre Ligue des champions, 18 matchs à J+3, abstentions explicites et triplet DraftKings déplié vérifiés visuellement. Capture dans dist/coupes-europe-0.3.1.jpg.


## Optimisation 0.3.0 — 10 octobre 2026

- 96 tests réussis sur 97, 1 test MCP ignoré (SDK optionnel absent). Contrôles temporels, données contradictoires, prévisions immuables, reports, identités et limitation des imports publics vérifiés.
- 56 prévisions réelles conservées avant match ; aucun résultat encore comparé au moment de la livraison. Le suivi importe les résultats publics nécessaires pendant le fonctionnement du serveur, sans appel à une API de cotes payante ou à un modèle de langage.
- Étude rétrospective sur 392 matchs : 122 Ligue 1, 115 Ligue 2, 155 Premier League. Ces archives ne prouvent pas les anciennes dates de publication ; aucun horodatage de connaissance modifié.
- La pondération par récence et la correction des petits scores restent expérimentales. Tous leurs intervalles de différence de Brier incluent zéro sur cette étude : la baseline demeure en production. Calibration descriptive, sans correction automatique.
- Parcours HTTP protégés, stratégie adaptative, réutilisation datée des avis, invalidation du cache et comptage des appels/tokens vérifiés avec transports simulés. Aucun appel réel à Claude/Ollama pendant cette validation.
- Syntaxe de install.sh, du script de construction macOS et des deux scripts JavaScript vérifiée.
- Vérification visuelle dans le navigateur : suivi de 56 prévisions et dates, enregistrement sans doublon, tableaux de comparaison et calibration dépliée, mode adaptatif et option de recherche forcée, Claude connecté. Aucun message envoyé au modèle.


## Consultations effectives dans le chat — 10 octobre 2026

- 72 tests réussis, 1 test MCP ignoré car SDK absent ; syntaxe Bash et JavaScript vérifiée.
- Huit appels distincts simulés, rôles activés uniquement, dépendance journaliste → effectifs → analyse sportive → coach.
- Tests des échecs de spécialistes, archivage des avis si le coach échoue, conservation des chiffres Python et abstention pré-match si le coup d’envoi est passé pendant la consultation.
- Parcours HTTP réel avec transport modèle simulé : lancement, suivi protégé par jeton, synthèse, puis suivi avec traces serveur ; les fausses traces du navigateur sont ignorées.
- Vérification visuelle du parcours complet avec données SYNTHÉTIQUES et réponses SIMULÉES, sans compte Claude ni modèle Ollama appelé.
- Dashboard local relancé ; chat Claude connecté et sélection de matchs disponibles vérifiés visuellement. App universelle et DMG reconstruits, signatures et image disque vérifiées, archive sans données personnelles.
- Aucune réponse réelle de Claude/Ollama ni recherche d’actualité sportive réalisée pendant cette validation. Les qualités des avis produits restent à évaluer en usage réel.

## Réponse du coach centrée sur les pronos — 10 octobre 2026

- Le bouton de préparation demande une présentation compacte des choix, probabilités,
  cotes par bookmaker et raisons ; il ne demande plus un bilan de simulations.
- Le coach reçoit une consigne de limites brèves pour cette demande ; les contrôles
  de fraîcheur et de données suffisantes du moteur sont conservés.
- 60 tests réussis, 1 MCP ignoré ; syntaxe Bash et JavaScript vérifiée.
  Le suivi de cette consigne par un modèle réel n’est pas testé dans cette vérification.


## Pronos sportifs et simulations distincts — 10 octobre 2026

- 60 tests réussis, 1 MCP ignoré sur 61 ; syntaxe Bash et JavaScript vérifiées.
- Un prono 1/N/2 calculé reste visible quand les cotes publiques non horodatées
  ne permettent pas de valider une simulation fictive ; aucun blocage du journal retiré.
- Les cartes Pronos montrent les offres par bookmaker, les probabilités et le choix
  déterministe. L’absence de données ou une égalité n’entraîne pas de choix inventé.
- Le chat reçoit le choix Python, les échantillons et les buts attendus du modèle.
  Son sélecteur de période couvre aujourd’hui ou demain à J+3. Le bouton de préparation
  appelle le coach uniquement au clic ; aucun modèle réel appelé pendant ces tests.


## Cotes enregistrées et contexte du chat — 10 octobre 2026

- 58 tests réussis, 1 MCP ignoré sur 59 ; syntaxe Bash vérifiée.
- Contrôle local : 199 matchs, 596 triplets enregistrés dans market-watch.json,
  trois captures CSV conservées ; dernière collecte à 12:08 Europe/Paris.
- Les offres par bookmaker, la source, l’heure de collecte, l’heure de cotation
  (nulle quand inconnue) et le marqueur synthétique sont maintenant transmis au chat.
- Test du transport simulé : cotes présentes accessibles au coach sans transformer
  l’heure d’import en heure de cotation. Aucun appel réel à un modèle ou à une API de cotes.

## Chat intégré et app macOS — 10 octobre 2026

- 57 tests réussis, 1 MCP ignoré sur 58 ; syntaxe des trois scripts Bash vérifiée.
- Transports Ollama et Claude simulés : sélection du fournisseur, contexte calculé,
  historique, délais/erreurs, filtrage des modèles cloud et absence de fuite des
  détails de connexion. Claude est limité à WebSearch/WebFetch, sans shell ni écriture.
- HTTP réel : jeton et origine obligatoires pour les opérations ; actions inconnues
  refusées. Lecture du statut Claude sans appel au modèle ; connexion locale détectée.
- Chat affiché dans le navigateur, Claude sélectionné, envoi disponible ; capture
  enregistrée dans dist/chat-claude.jpg. Aucun message envoyé à un modèle réel.
- App compilée pour arm64 et x86_64 ; signature locale, sans notarisation Apple.
  La compilation universelle ne vaut pas un test sur un Mac Intel.


## Pronos aujourd'hui / demain à J+3 — 10 octobre 2026

- 49 tests réussis, 1 MCP ignoré sur 50 tests ; syntaxe Bash vérifiée.
- Tests ajoutés : minuit local, borne de J+3, coup d'envoi exact, heure d'hiver,
  absence de fuite de connaissance future, cotes périmées/futures/non horodatées,
  historique insuffisant, capacité fictive, filtres du dashboard et absence d'écritures.
- Les tendances des cotes publiques restent en abstention, sans comparaison de marché.
  Aucune sélection conseillée n'est produite avec ces cotes non horodatées.

## Hub européen et équipe IA — 10 octobre 2026

- 22 divisions : 16 712 résultats importés pour 2024/25, 2025/26 et le début de 2026/27.
- Un résultat sans scores en Ligue 2 exclu avec trace dans la capture et le manifeste.
- Calendrier public : 199 rencontres, 596 triplets 1N2 de bookmakers identifiés.
  Heure exacte de cotation inconnue : consultation uniquement, aucune simulation.
- 43 tests réussis, 1 test MCP ignoré sur 44 tests ; vérification Bash réussie.
  Couverture ajoutée : isolation par championnat, cotes non horodatées séparées,
  rejets explicites, recherche/échappement du hub, dates des dossiers de contexte.
- Huit rôles, skill `news` et archivage `match_context`. Premier dossier sourcé
  Lille–Le Havre créé après lecture des sites officiels ; aucune délégation réelle
  ni exécution autonome de huit modèles revendiquée.
- Le validateur de skill fourni n'a pas pu démarrer (PyYAML absent). Frontmatter et
  références vérifiés localement. L'outil navigateur macOS a expiré ; les réponses
  HTML/HTTP sont vérifiées, le rendu visuel reste non vérifié dans un navigateur.

## Import réel du 10 octobre 2026

- macOS, Python 3.14.7 : 36 tests réussis et 1 test MCP ignoré (SDK absent).
- Syntaxe Bash vérifiée. Nouveaux tests : conversion été/hiver, connaissance non
  antidatée, fichiers incomplets, mauvaise compétition, dates futures, doublons,
  réimport idempotent, correction refusée, démo protégée et téléchargement partiel.
- Collecte réelle Football-Data : 612 résultats de Ligue 1 pour 2024/25 et 2025/26,
  dans `data/workspaces/ligue1`, sans modification de la démo.
- Backtest réel : 0 évalué, 612 ignorés, car les résultats n'étaient connus du système
  qu'à leur collecte. Aucun score prédictif ou bénéfice revendiqué.
- Dashboard réel lancé sur le port 8876 ; réponse HTTP et présence des 612 résultats
  vérifiées. L'ouverture automatisée du navigateur a rencontré un délai d'attachement.

## Extension du 10 octobre 2026 — point quotidien

Exécutée sur macOS, Python 3.14.7 : **31 tests réussis, 1 ignoré** (SDK MCP
optionnel absent), sur 32 tests découverts. Vérification Bash de `install.sh`
et `scripts/prono` réussie.

Six nouveaux tests couvrent le jour local à minuit, le passage à l'heure d'hiver,
le coup d'envoi exact, les cotes futures/périmées, l'historique insuffisant,
le workspace sans matchs, le fuseau invalide, l'absence d'écritures implicites,
l'archivage du briefing, la commande `today` et la capacité fictive disponible.
Les contrôles HTTP et d'échappement du tableau existants passent avec le briefing.
Le rendu visuel du tableau n'a pas été vérifié dans un navigateur lors de cette extension.
Aucune API externe ni modèle de langage n'a été appelé par les tests.

## Livraison initiale

Exécutée le 9 octobre 2026, Linux, Python 3.12.14.

- **26 tests réussis**, aucun ignoré dans l'environnement avec MCP 1.30.0.
- Vérification des scripts Bash et compilation des modules Python réussies.
- Installation dans un workspace séparé avec les six sorties de configuration IDE,
  données démo et dépendance MCP : réussie.
- MCP : initialisation stdio par le client officiel, liste des quatre outils, appels
  `paper_summary` et `analyze_match` réussis ; aucun journal écrit par les outils.
- Dashboard : HTTP réel, JSON de bilan, réponse HTML, filtrage Host, chemins de fichiers
  refusés, CSP présente. Pas de vérification visuelle dans un navigateur.
- CLI : diagnostic, analyse archivée, rapport Markdown, aperçu d'installation.
- Skills : sept fichiers avec frontmatter et noms correspondant aux dossiers.

Les tests de calcul et de cycle de vie utilisent des données synthétiques. Ils vérifient
le logiciel, pas une qualité prédictive sur de vrais matchs. Le transport du fournisseur
de cotes et celui du LLM sont simulés. Aucun compte de bookmaker n'est connecté.

Non vérifiés : appels authentifiés The Odds API/Ollama/OpenRouter, assistants IDE en session
réelle, macOS, Python 3.11/3.13, CI hébergée. La CI incluse est une configuration prête à
exécuter lors d'un futur dépôt GitHub, pas un résultat de CI déjà obtenue.
