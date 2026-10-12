# AI Prono Coach

Analyser un match de football, comprendre les probabilités et suivre les résultats.
Les calculs viennent de Python ; le coach IA les explique sur demande.
**Football 1N2 avant match, simulations fictives uniquement.** Le modèle n’est pas
calibré et aucune rentabilité n’est démontrée.

## Démarrer

Python 3.11+ est nécessaire. Depuis le dossier du projet :

```bash
./install.sh --ide claude
./scripts/prono ui
```

Ouvrir [le tableau local](http://127.0.0.1:8766). Si le projet est déjà installé,
seule la seconde commande est nécessaire. Pour l’application Mac, suivre
[le guide macOS](docs/macos.md).

La première collecte se lance explicitement :

```bash
./scripts/prono sync-leagues --leagues F1 E0 --markets
```

Cet exemple importe les historiques de Ligue 1 et Premier League et le calendrier
public du catalogue. Omettre `--leagues F1 E0` pour importer les 25 compétitions.
La collecte utilise des sources publiques ; elle n’appelle aucun modèle IA.
`sync-odds` est une commande distincte qui peut consommer le quota de votre API de cotes.

## Le parcours quotidien

1. **Pronos** : choisir la compétition et la période, puis lire les probabilités
   et les raisons d’abstention. « Comprendre ce match » ouvre le coach sur ce match.
2. **Coach** : poser une question ou demander une analyse aux spécialistes.
   Les réglages du modèle et les actualisations sont dans des panneaux repliables.
   Le message et les faits sont transmis uniquement à votre demande ; Claude peut
   utiliser son quota. Local utilise les données chargées sans recherche web.
3. **Suivi** : consulter les prévisions archivées avant match et leurs résultats.
   Ce suivi est distinct du journal des simulations fictives.

**Calendrier** donne les rencontres et cotes publiques. **Outils et données** regroupe
les résultats, les dossiers de l’équipe, les sources et l’évaluation expérimentale.
Sans données multi-compétitions, le tableau initial présente le workspace et son diagnostic.

Les cotes publiques sans heure de cotation restent indicatives et bloquent les simulations.
Le suivi automatique dépend de `[tracking]` et fonctionne pendant l’ouverture du serveur.
Aucun modèle IA n’est appelé à l’ouverture d’une page.

## Configurer et comprendre

Les préférences vont dans `config/workspace.user.toml` et priment sur les valeurs
par défaut, sans les écraser. Le profil se trouve dans `memory/Player_Profile.md`.

- [Guide détaillé : installation, commandes, données et intégrations](docs/guide.md)
- [Application Mac et chat](docs/macos.md)
- [Modèle et limites](docs/model.md)
- [Format des données](docs/data-contract.md) et [dossiers sourcés](docs/context-contract.md)
- [Évolutions fonctionnelles](docs/evolutions.md)
- [Audit et simplification du 12 octobre 2026](docs/audit-20261012.md)

Les archives d’analyses, le journal, les rapports et les données restent locaux.
Les données de démonstration sont **synthétiques**.

## Développement

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
bash -n install.sh
bash -n scripts/build-macos-dmg.sh
```

Les agents et skills restent versionnés avec le moteur. Le MCP sportif expose
quatre outils en lecture seule. Voir [AGENTS.md](AGENTS.md) pour les règles du projet.

Inspiré de AI Running Coach et AI Finance Coach de Marco Mornati.
Projet indépendant, code original, sans affiliation ni validation de Marco.
