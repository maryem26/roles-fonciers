# Rôles d'évaluation foncière du Québec : import dans PostgreSQL

Ce projet lit les fichiers XML des **rôles d'évaluation foncière du Québec** (Données Québec), vérifie leur contenu et les charge dans une base **PostgreSQL**. Le code est en **Python**, le chargement est **rejouable** (aucun doublon si on relance) et chaque fichier est chargé en **une seule transaction** (tout ou rien).

> Contexte : test technique de recrutement. L'analyse, le modèle de données et la conception de l'import sont décrits dans le dossier [`docs/`](docs/).

## Démarrage rapide (sans rien télécharger)

Le dépôt contient un petit fichier d'exemple (`tests/fixtures/RL45080_sample.xml`, une seule propriété) et un index d'exemple. Avec Docker et uv installés :

```bash
git clone <adresse-du-depot>
cd roles-fonciers

uv sync                                   # installe Python 3.12 et les dépendances
docker compose up -d                      # démarre PostgreSQL (port 5433)
uv run roles-fonciers init-db             # crée les tables
uv run roles-fonciers load-index tests/fixtures/index_sample.csv
uv run roles-fonciers load-roles tests/fixtures/RL45080_sample.xml
```

Résultat attendu : `RL45080_sample.xml : chargé | 1 lue(s), 1 chargée(s), 0 écartée(s)`.

## Prérequis

| Outil | Pourquoi | Installation |
|---|---|---|
| **Git** | récupérer le dépôt | https://git-scm.com |
| **Docker Desktop** | lancer PostgreSQL 16 sans l'installer | https://www.docker.com/products/docker-desktop (le démarrer avant de continuer) |
| **uv** | installer Python 3.12 et les dépendances | Windows : `winget install --id=astral-sh.uv -e` ; autres systèmes : https://docs.astral.sh/uv |

## Installation

```bash
uv sync                          # dépendances (lxml, psycopg, typer, pydantic, httpx, pytest)
docker compose up -d             # PostgreSQL 16 sur localhost:5433
docker compose ps                # attendre l'état « healthy »
uv run roles-fonciers init-db    # crée les tables (sans danger si elles existent déjà)
```

La connexion par défaut correspond à `docker-compose.yml` (base `roles`, utilisateur `roles`, port 5433). Elle se change avec la variable d'environnement `DATABASE_URL`. La taille des lots se règle avec `BATCH_SIZE` (5 000 par défaut).

> Le mot de passe du fichier `docker-compose.yml` est un mot de passe de **développement local** : ne le réutilisez pas ailleurs.

## Les données

Les fichiers de données ne sont **pas** dans le dépôt (5,4 Go décompressés). Pour travailler sur les vraies données :

1. Télécharger sur [Données Québec](https://www.donneesquebec.ca/recherche/dataset/roles-d-evaluation-fonciere-du-quebec) l'archive « Tous les fichiers des rôles d'évaluation foncière du Québec 2026 » et l'index CSV.
2. Les placer ainsi (le dossier `data/` est ignoré par Git) :

```
data/raw/indexRole2026.csv
data/raw/Roles_Donnees_Ouvertes_2026/RL01023_2026.xml
data/raw/Roles_Donnees_Ouvertes_2026/RL01042_2026.xml
...
```

Le programme fonctionne avec n'importe quel fichier XML local : il suffit de passer son chemin à `load-roles`.

## Utilisation

```bash
# 1. Charger les municipalités (une fois, avant les rôles)
uv run roles-fonciers load-index data/raw/indexRole2026.csv

# 2. Charger des rôles
uv run roles-fonciers load-roles data/raw/Roles_Donnees_Ouvertes_2026 --only RL45080 --only RL13075 --only RL08005
uv run roles-fonciers load-roles data/raw/Roles_Donnees_Ouvertes_2026/RL08005_2026.xml    # un seul fichier
uv run roles-fonciers load-roles data/raw/Roles_Donnees_Ouvertes_2026                    # tous les fichiers du dossier
uv run roles-fonciers load-roles data/raw/Roles_Donnees_Ouvertes_2026 --skip-existing    # ignore les rôles déjà chargés

# Outils
uv run roles-fonciers inspect <fichier.xml>   # lit un fichier et affiche un résumé, sans toucher à la base
uv run roles-fonciers --help
```

- `--only` se **répète** devant chaque fichier, et filtre par début de nom.
- Relancer une commande **remplace** le rôle déjà chargé (même municipalité, même année) : aucun doublon.
- Un fichier en erreur est rejeté et noté, mais les autres fichiers sont chargés normalement.

### Vérifier le résultat

```bash
docker compose exec db psql -U roles -d roles -c "SELECT r.municipality_code, r.assessment_year, r.format_version, count(u.id) AS units FROM assessment_role r LEFT JOIN assessment_unit u ON u.role_id = r.id GROUP BY 1,2,3 ORDER BY 1;"

# Problèmes relevés pendant les imports
docker compose exec db psql -U roles -d roles -c "SELECT source_file, severity, code, message FROM import_issue ORDER BY id DESC LIMIT 10;"
```

## Sous-ensemble utilisé et résultats

Le développement et les tests ont porté sur **trois fichiers** :

| Fichier | Version du format | Année du rôle | Propriétés lues | Chargées | Écartées |
|---|---|---|---|---|---|
| `RL45080` (le plus petit) | 2.9 | 2025 | 1 | 1 | 0 |
| `RL13075` | 2.6 | 2025 | 291 | 291 | 0 |
| `RL08005` (fichier médian) | 2.9 | 2026 | 1 119 | 1 119 | 0 |

Un avertissement est attendu sur `RL08005` : `ZERO_OR_MISSING_VALUE`, pour la propriété de matricule `4925-46-3369`, dont la valeur d'immeuble est 0 et qui n'a aucune autre valeur.

**Non réalisé sur les données réelles** : le chargement des 1 134 fichiers et le plus gros fichier (758 Mo, `RL66023`).

## Comment ça marche

Pour chaque fichier : **lire** (en flux, une propriété à la fois, mémoire constante) → **valider** → **transformer** (texte en nombres et dates, zéros conservés) → **charger** (par lots, une transaction par fichier) → **contrôler** (lues = chargées + écartées, et nombre de lignes en base).

Trois niveaux de problèmes, tous consignés dans la table `import_issue` (un message par type de problème et par fichier) :

| Niveau | Effet | Exemples de codes |
|---|---|---|
| Fichier rejeté | Rien n'est chargé, l'ancien rôle reste intact | `XML_INVALID`, `HEADER_MISSING`, `UNKNOWN_MUNICIPALITY`, `CODE_MISMATCH` |
| Propriété écartée | Les autres propriétés sont chargées | `MATRICULE_INCOMPLETE`, `INVALID_CODE`, `DUPLICATE_UNIT` |
| Avertissement | La propriété est chargée | `ZERO_OR_MISSING_VALUE`, `VALUE_MISMATCH`, `REFERENCE_DATE`, `UNKNOWN_TAG`, `CONVERSION` |

## Organisation du dépôt

```
├── docker-compose.yml          PostgreSQL 16
├── pyproject.toml, uv.lock     dépendances
├── sql/                        schéma de la base (migrations numérotées)
├── src/roles_fonciers/
│   ├── cli.py                  commandes (init-db, load-index, load-roles, inspect)
│   ├── config.py, database.py  configuration et connexion
│   ├── index_loader.py         lecture de l'index CSV
│   ├── xml_reader.py           lecture XML en flux
│   ├── transform.py            conversion et validation d'une propriété
│   ├── issues.py               regroupement des problèmes
│   └── loader.py               chargement transactionnel
├── tests/                      tests automatiques (+ fichiers d'exemple dans fixtures/)
├── scripts/                    scripts d'analyse (inventaire, profilage des fichiers XML)
└── docs/                       analyse, modèle de données, conception de l'import
```

Documentation (Word) :
- `docs/Analyse-donnees-roles-fonciers.docx` : structure, contenu et difficultés des données.
- `docs/Modele-base-de-donnees-roles-fonciers.docx` : les 9 tables et la justification de chaque choix.
- `docs/Processus-import-roles-fonciers.docx` : le processus d'import, la gestion des erreurs et des réexécutions.

## Tests

```bash
uv run pytest
```

Les tests de lecture, de transformation et d'analyse de l'index n'ont pas besoin de base. Les **tests de chargement** utilisent la base Docker (`docker compose up -d` puis `init-db`) et sont **ignorés** si elle n'est pas disponible. Ils ne touchent qu'une municipalité fictive (`ZZ999`).

## Choix du langage

**Python** a été retenu plutôt que TypeScript : lecture XML en flux éprouvée (`lxml`), chargement rapide dans PostgreSQL (`psycopg` 3), validation claire, et une meilleure maîtrise du langage. La contrepartie est un typage moins strict que TypeScript. Le détail est dans le document sur le processus d'import.

## Hypothèses

- Les fichiers sont en UTF-8 et disponibles localement (le téléchargement initial est hors périmètre).
- Un rôle est identifié par **sa municipalité et son année** (`RLM02A`, lue dans le fichier et non dans son nom). Une propriété est identifiée par son rôle et son **matricule complet** (8 parties, dont 5 facultatives).
- Les codes de municipalité font 5 caractères. Les 34 codes qui commencent par `NR` (par exemple `NR020`) désignent très probablement des **territoires non organisés** ; cette interprétation n'est pas confirmée.
- Un seul import tourne à la fois sur la même base.

## Limites

- **Couverture** : seuls trois fichiers ont été chargés et vérifiés. Les règles de cohérence (matricule unique, terrain + bâtiment = immeuble) ont été contrôlées sur un fichier détaillé et ne sont pas prouvées sur les 1 133 autres.
- **Performance** : non mesurée sur l'ensemble de l'archive ni sur le plus gros fichier. Une transaction par fichier peut être lourde pour les très gros fichiers.
- **Versions du format** : seules les versions 2.6 et 2.9 ont été comparées (aucune différence de structure notable) ; 2.7 et 2.8 ne l'ont pas été.
- **Champ `RL0103x`** : non documenté dans le guide officiel, conservé tel quel (probablement une désignation cadastrale, à confirmer).
- **Non modélisé** : les sous-catégories `RL0506x` (absentes des fichiers étudiés) et les données géographiques (fichiers GPKG/FGDB, un bonus du sujet).
- **Codes** : les codes (utilisation `CUBF`, classes…) sont stockés tels quels, sans table de libellés. Une propriété dont un code sort des valeurs du guide est écartée ; cette règle pourrait être adoucie en avertissement.
- **Mises à jour** : relancer un rôle le remplace entièrement, sans conserver l'historique.
- **Pas de validation par schéma XML** : le fichier `RL.xsd` est référencé par les XML mais n'est pas fourni.

## Données personnelles

Les noms et adresses des propriétaires, ainsi que les données cadastrales, sont retirés des données publiées. Il est **interdit de réidentifier** ces personnes. Ce projet ne le tente pas et ne contient aucune colonne pour ces informations.

## Dépannage

| Message | Cause | Solution |
|---|---|---|
| `error during connect ... dockerDesktopLinuxEngine` | Docker Desktop n'est pas démarré | Le lancer et attendre qu'il soit prêt |
| `Connexion à la base impossible` | La base n'est pas démarrée | `docker compose up -d` |
| `port is already allocated` | Le port 5433 est pris | Changer `5433:5432` dans `docker-compose.yml` et la valeur de `DATABASE_URL` |
| `uv : le terme n'est pas reconnu` | uv n'est pas installé | Voir « Prérequis », puis rouvrir le terminal |

## Données

Source : [Rôles d'évaluation foncière du Québec](https://www.donneesquebec.ca/recherche/dataset/roles-d-evaluation-fonciere-du-quebec), Données Québec (ministère des Affaires municipales et de l'Habitation). Se reporter à la page du jeu de données pour les conditions d'utilisation.