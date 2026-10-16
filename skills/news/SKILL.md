---
name: news
description: "Préparer un dossier pré-match sourcé : dernières nouvelles des clubs, blessures, suspensions et compositions."
---

Appliquer `AGENTS.md`. Résoudre la rencontre exacte, son championnat et son coup d'envoi
avec les données locales. Un match de `market-watch.json` peut recevoir un dossier de
contexte, même si ses cotes ne sont pas analysables. Une recherche ne débloque pas ces cotes.

Utiliser la recherche web disponible dans l'assistant, distincte des quatre outils MCP
sportifs. Sans accès web, le dire et travailler uniquement sur des sources fournies.
Ne pas créer de collecte récurrente ni appeler une API de cotes pendant la recherche.

Le journaliste recherche les dernières annonces concernant les deux clubs, puis
l'analyste effectif vérifie absences/suspensions et compositions. Le coach ne délègue
qu'aux rôles activés ; sans délégation disponible, il suit leurs instructions et l'indique.
Consulter les sources primaires datées ; lire les publications et vérifier qu'elles
concernent le bon match. Compléter avec les médias pour éclairer les divergences.
S'arrêter lorsque les rubriques sont documentées ou explicitement indisponibles.

Distinguer : confirmé, rapporté, incertain, contredit. Pour chaque fait conserver une URL
directe, le titre, le type de source, la publication connue et la vérification effective.
Ne pas inventer d'heure lorsque seule la date est publiée : `published_at: null` et
`publication_date: YYYY-MM-DD`. Mentionner les informations anciennes ; les retours
récents peuvent invalider une annonce précédente. Aucune certitude déduite du silence.

Archiver les faits lus avec `prono context-import FICHIER.json`, selon
`docs/context-contract.md`. Le code contrôle les dates et le match, pas la véracité
d'un article : la lecture et les citations relèvent du journaliste. Présenter ensuite
le dossier, ses contradictions et ses manques. Ne pas archiver d'articles complets.

Les nombres du modèle restent ceux des outils. Aucune majoration intuitive de
probabilité, aucun score numérique de confiance. Tous les rôles et le coach analysent
les faits sans les sorties Poisson ; les absences documentées motivent leur avis
qualitatif ou une abstention. La comparaison au modèle est ajoutée après le verdict.

Pour les coupes européennes, consulter aussi les comptes rendus des trois dernières
prestations nationales de chaque club, à partir de la forme Python `domestic_form`.
Lire le texte : occasions, maîtrise, adversaire, difficultés, rotations, explications
du coach. Attribuer les jugements et séparer score, contenu observé et interprétation.
Ne pas inventer xG/tirs ou transformer un commentaire en pourcentage. Si le calendrier
chargé est ancien ou incomplet, vérifier les derniers matchs réellement joués avant
la recherche ; ne pas annoncer une couverture exhaustive. Une source inaccessible
reste indisponible. Les publications utilisées doivent être antérieures à l'analyse.
