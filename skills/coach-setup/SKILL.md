---
name: coach-setup
description: "Configurer les préférences et le workspace AI Prono Coach au premier démarrage."
---

Lire `AGENTS.md`, puis exécuter `prono doctor`. Si le profil manque, `prono init`.
Demander une information à la fois, uniquement si elle manque : objectif d'apprentissage,
compétition, style d'explication. V1 football 1N2 et simulation fictive : l'annoncer.
Écrire les préférences dans `memory/Player_Profile.md`. Les réglages personnels vont dans
`config/workspace.user.toml`, jamais dans les défauts partagés. Conserver les réglages existants.
L'activation d'un fournisseur requiert la clé utilisateur ; ne pas réclamer sa valeur dans le chat.
Proposer `prono demo` uniquement sur un workspace vide, ou un workspace de démonstration séparé.
