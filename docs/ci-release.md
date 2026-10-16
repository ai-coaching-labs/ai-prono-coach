# Tests, DMG et releases GitHub

Les workflows sont versionnés dans `.github/workflows/`. Ils sont activés lorsque
ces fichiers sont poussés sur GitHub. Aucun secret personnel n’est nécessaire pour
les tests, la construction ad hoc ou la publication d’une release avec `GITHUB_TOKEN`.

## Déclenchements

| Événement | Contrôles | DMG | Release GitHub |
|---|---|---|---|
| Pull request | Python 3.11–3.14, MCP, JavaScript, shell, workflows, versions | Non | Non |
| Push sur `main`, notamment après fusion | Mêmes contrôles, puis tests macOS/Swift | Artefact conservé 14 jours | Non |
| Push d’un tag `vX.Y.Z` | Mêmes contrôles et concordance du tag | Artefact et fichier SHA256SUMS | Oui, après succès |
| Lancement manuel de CI | Contrôles de la référence choisie | Non | Non |
| Lancement manuel de Build and release | Uniquement `main` ou un tag de version valide | Oui | Seulement sur un tag |

Un push direct sur `main` déclenche le même build qu’une fusion de PR. Pour imposer
les fusions, protéger la branche comme indiqué plus bas. Les builds sur `main` ne
remplacent pas la dernière release : ils apparaissent dans **Actions → Build and release
→ exécution → Artifacts → macos-dmg**. Les releases suivent la visibilité du dépôt.

## Contenu des workflows

- [`ci.yml`](../.github/workflows/ci.yml) : contrôles des versions, syntaxe des scripts,
  JavaScript et workflows avec actionlint, puis suite complète sur quatre versions
  de Python sous Linux. Le SDK MCP et Node.js sont installés pour exécuter leurs tests.
  Le contrôle final **Required checks** échoue si une étape requise échoue ou est annulée.
- [`macos.yml`](../.github/workflows/macos.yml) : workflow réutilisable appelé après
  les contrôles. Il exécute aussi les tests macOS, construit les deux architectures,
  vérifie la version, l’empreinte du moteur, les ressources embarquées, les signatures,
  les architectures et l’intégrité du DMG, puis conserve le DMG et sa somme SHA-256.
- [`release.yml`](../.github/workflows/release.yml) : orchestre les contrôles et le
  build sur `main` et les tags. Sur un tag, le dernier job dispose de `contents: write`
  pour créer la release avec GitHub CLI, les notes générées et les deux fichiers.

Les jobs de test et de build ont seulement accès en lecture au contenu du dépôt.
Les pull requests de forks ne reçoivent aucun secret de publication. Les tests ne
lancent pas d’analyse IA payante ni de synchronisation sportive réelle.
Une erreur de contrôle ou de construction empêche la publication. Un tag incompatible
avec les versions du projet est refusé avant les tests et la construction.

La signature automatique est **ad hoc**, sans certificat Developer ID ni notarisation
Apple. Elle vérifie la cohérence du paquet mais ne lui donne pas une identité éditeur
reconnue par Gatekeeper. Une distribution notarisée nécessite une configuration Apple
supplémentaire ; voir [la construction Mac](macos.md#construire-le-dmg).

## Préparer le dépôt GitHub

1. Créer le dépôt GitHub, configurer son remote et pousser le projet sur `main`.
2. Vérifier que **Settings → Actions → General** autorise les actions utilisées.
   Le job de publication demande explicitement la permission `contents: write`.
   Une politique d’organisation peut néanmoins interdire cette permission.
3. Dans les règles de protection de `main`, imposer une pull request et le contrôle
   **Required checks** du workflow CI. GitHub le proposera après sa première exécution.
4. Ouvrir une PR pour observer les tests, puis la fusionner pour obtenir le premier
   DMG dans les artefacts du workflow **Build and release**.

La protection de branche est un réglage GitHub ; les fichiers YAML ne l’activent pas.
Aucun remote n’est fourni par ce guide : utiliser l’URL réelle de son dépôt.

## Publier une version

La même version stable `X.Y.Z` doit figurer dans :

- `pyproject.toml`, clé `[project].version` ;
- `src/prono/__init__.py`, variable `__version__`.

Pour la première release, la version actuelle est `0.3.10`. Pour les suivantes,
modifier les deux déclarations dans une PR, puis fusionner cette PR sur `main`.
Une fois `main` à jour et les modifications locales traitées :

```bash
git switch main
git pull --ff-only origin main
python3 .github/scripts/check_version.py --tag v0.3.10
git tag -a v0.3.10 -m "AI Prono Coach 0.3.10"
git push origin v0.3.10
```

Remplacer `0.3.10` par la version à publier. Le workflow reconstruit le DMG à partir
du commit tagué, sans reprendre le dernier artefact de `main`. La release contient :

- `AI-Prono-Coach-X.Y.Z.dmg` ;
- `SHA256SUMS` ;
- des notes GitHub générées, précédées des instructions d’installation.

Le workflow ne modifie ni la version ni les tags automatiquement. Il n’écrase pas
une release existante. Pour un nouvel essai après échec avant publication, relancer
le workflow sur le même tag ; après publication, utiliser une nouvelle version.
Les préversions comme `v1.0.0-rc1` ne sont pas prises en charge par ces contrôles.

Après téléchargement des deux fichiers dans le même dossier, vérifier sous macOS :

```bash
shasum -a 256 -c SHA256SUMS
```

## Vérifier localement

```bash
python3 .github/scripts/check_version.py
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
bash -n install.sh scripts/prono scripts/build-macos-dmg.sh
node --check src/prono/assets/chat.js
```

Sur macOS, `bash scripts/build-macos-dmg.sh` construit le paquet. La sortie indique
le chemin de l’application ; le passer à `python3 .github/scripts/verify_macos.py
"dist/macos-…/AI Prono Coach.app"` pour vérifier le contenu du moteur.
Le workflow ajoute les vérifications Apple des signatures, architectures et du DMG.
Les builds locaux ne remplacent pas une exécution effective sur les runners GitHub.

Références : [workflows réutilisables](https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows),
[création de releases avec GitHub CLI](https://cli.github.com/manual/gh_release_create),
[artefacts GitHub Actions](https://github.com/actions/upload-artifact).
