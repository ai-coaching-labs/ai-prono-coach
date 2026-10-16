# AI Prono Coach

Un coach local pour analyser des matchs de football, lire les probabilités et suivre
les résultats. Disponible dans le navigateur et dans une application macOS.

**Football 1N2 avant match, simulations fictives uniquement.** Le modèle Poisson
n’est pas calibré et aucune rentabilité n’est démontrée.

## Ce que fait l’application

- **Pronos** : calendrier, choix Python, probabilités 1/N/2 et limites des données.
- **Coach** : analyse sourcée, pronostic qualitatif, score envisagé LLM et confiance
  faible/modérée/élevée. L’équipe essentielle réunit journaliste/effectifs, analyste
  sportif et coach ; des spécialistes supplémentaires restent disponibles.
- **Suivi** : prévisions archivées avant match, résultats et comparaison au marché
  lorsque les cotes disposent des dates nécessaires.
- **Données** : 25 compétitions, forme nationale et xG Understat pour les championnats
  couverts. Les collectes sont explicites ; leur couverture peut être incomplète.

Les probabilités viennent de Python. Tous les spécialistes et le coach rendent leur
avis sans voir les prévisions Poisson ; l’application ajoute ensuite la comparaison,
sans modifier les chiffres du modèle. Le score envisagé LLM est une hypothèse ;
la confiance porte sur l’issue 1/N/2, pas sur le score exact.

## Installer sur Mac

Depuis la rubrique **Releases** du dépôt GitHub, télécharger le DMG, puis glisser
**AI Prono Coach.app** dans Applications. À l’ouverture, choisir le dossier de travail
et cliquer sur **Préparer mon coach**.

Prérequis : macOS 13+, Python 3.11+, puis **Ollama** avec un modèle installé ou
**Claude Code** connecté pour le coach IA. L’application est universelle Apple Silicon
et Intel. Les builds automatiques ont une signature locale ad hoc et ne sont pas
notarisés par Apple ; une autorisation d’ouverture peut être nécessaire.
Voir le [guide Mac](docs/macos.md) pour l’installation détaillée et la construction locale.

## Démarrer depuis les sources

Python 3.11+ est nécessaire. Depuis le dossier du projet :

```bash
./install.sh --ide claude
./scripts/prono ui
```

Ouvrir l’adresse locale affichée dans le terminal. Le serveur utilise par défaut
`http://127.0.0.1:8766`. La première collecte se lance explicitement, par exemple :

```bash
./scripts/prono sync-leagues --leagues F1 E0 --markets
```

Cet exemple charge les historiques de Ligue 1 et Premier League et le calendrier
public. Sans `--leagues`, l’import couvre les 25 compétitions. Pour les xG, suivre
le [guide Understat](docs/understat.md).

Aucun modèle IA n’est appelé à l’ouverture d’une page. Une analyse demandée utilise
le quota du modèle choisi ; Ollama travaille sans recherche web. Les cotes publiques
sans heure de cotation restent indicatives et bloquent les simulations.
`sync-odds` est un connecteur distinct qui peut consommer le quota d’une API de cotes.

## Données et configuration

Les préférences de `config/workspace.user.toml` priment sur les valeurs par défaut.
Le profil, les données sportives, analyses, rapports et journaux restent locaux et
sont exclus de Git, comme les secrets et les exports vidéo. Les données de démo
sont **synthétiques**. Le suivi fonctionne pendant l’ouverture du serveur.

## Tests, builds et releases

- **Pull request** : tests sur Python 3.11 à 3.14, contrôles JavaScript, scripts et workflows.
- **Fusion ou push sur `main`** : mêmes contrôles, tests Mac, puis construction et
  vérification du DMG universel, téléchargeable dans les artefacts GitHub Actions.
- **Tag `vX.Y.Z`** : contrôles, construction et publication d’une release avec DMG,
  notes automatiques et somme de contrôle SHA-256. Le tag doit correspondre aux versions du code.

Les workflows sont prêts à être exécutés une fois le projet publié sur GitHub.
La [procédure CI et release](docs/ci-release.md) décrit les réglages du dépôt,
la protection de `main` et la publication d’une version.

Pour vérifier localement après installation des dépendances :

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
bash -n install.sh scripts/prono scripts/build-macos-dmg.sh
node --check src/prono/assets/chat.js
```

Node.js permet aussi d’exécuter les tests du rendu du chat. La construction du DMG
nécessite macOS et les outils de développement Apple.

## Documentation

- [Guide d’utilisation et commandes](docs/guide.md)
- [Application Mac, verdicts et consommation IA](docs/macos.md)
- [Modèle, évaluation et limites](docs/model.md)
- [Format des données](docs/data-contract.md) et [dossiers sourcés](docs/context-contract.md)
- [xG Understat](docs/understat.md)
- [CI, DMG et releases GitHub](docs/ci-release.md)
- [Références](docs/references.md)

Les agents et skills sont versionnés avec le moteur. Le MCP sportif expose quatre
outils en lecture seule ; les règles communes sont dans [AGENTS.md](AGENTS.md).

Licence MIT. Inspiré de AI Running Coach et AI Finance Coach de Marco Mornati.
Projet indépendant, sans affiliation ni validation de Marco.
