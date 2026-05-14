# cloudbreak-backend

API backend de l'application Cloudbreak — prédit la probabilité de mer de nuage depuis un sommet donné.

## Stack

- **Python 3.12** + **FastAPI 0.115**
- **PostgreSQL 16** — base de données principale
- **Redis 7** — cache météo (TTL 10min) + quota freemium
- **SQLAlchemy async** + **Alembic** — ORM et migrations
- **Pydantic v2** — validation et settings
- **Gunicorn + Uvicorn** — serveur de production

## Setup (première fois)

```bash
# 1. Créer le virtualenv (pour les outils qualité en local — pas pour lancer le serveur)
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 2. Copier le fichier d'environnement
cp .env.example .env
# puis remplir les valeurs dans .env
```

## Lancer en dev

Le backend tourne **toujours sous Docker** — même setup que la prod.

```bash
make dev      # démarrer db + redis + api
make migrate  # appliquer les migrations Alembic
make seed     # insérer les données initiales (sommets)
make down     # arrêter
make logs     # suivre les logs en temps réel
```

Pour tester le quota freemium en local, créer des users de test Supabase :

```bash
source .venv/bin/activate
make seed-test        # crée freemium@cloudbreak.app + pro@cloudbreak.app dans Supabase
make unseed-test      # supprime les users de test

make clean-subscriptions   # vide la table subscriptions (reset plan → freemium)
make reset-db              # reset complet BD (drop + recreate + seed) — ⚠ destructif
```

Containers lancés :

- `cloudbreak-backend` → API FastAPI sur http://localhost:8000
- `cloudbreak-db` → PostgreSQL sur port 5432
- `cloudbreak-redis` → Redis sur port 6379

La doc Swagger est sur http://localhost:8000/docs

## Migrations

```bash
source .venv/bin/activate

make migrate      # appliquer les migrations
make migration    # créer une nouvelle migration (demande une description)
```

## Donnees peaks

Workflow safe pour enrichir ou regenerer les donnees sommets :

```bash
source .venv/bin/activate

# 1. Backup local du JSON source + enrichissement region
python scripts/enrich_region.py

# 2. Verifier le dataset enrichi
pytest tests/test_peaks_data.py

# 3. Mettre a jour la base via upsert sur slug
make seed
```

Notes :

- `scripts/enrich_region.py` n'appelle pas `generate_peaks.py`
- un backup local temporaire est ecrit dans `.tmp/peaks_data_backup.json` avant modification
- `make seed` fait maintenant un upsert sur `slug` pour remettre la DB en phase avec `peaks_data.json`
- le backend lit ensuite `region` depuis `app/db/peaks_data.json` et le propage dans les endpoints peaks / favoris / score (`peak_region`)

## Qualité & Tests

Ces commandes se lancent **en local** (pas dans Docker) avec le virtualenv activé :

```bash
source .venv/bin/activate

make validate     # ✅ tout valider d'un coup — à lancer avant chaque commit
```

Cette commande enchaîne dans l'ordre :

1. `ruff check .` — 0 erreur lint
2. `ruff format --check .` — code bien formaté
3. `mypy app/` — 0 erreur typage
4. `pytest --cov=app --cov-report=term-missing` — tous les tests passent, coverage 100%

Commandes individuelles :

```bash
make lint         # ruff check uniquement
make format       # ruff format (applique le formatage)
make typecheck    # mypy uniquement
make test         # pytest --cov uniquement
```

## Structure

```
app/
├── api/v1/endpoints/   # Routes HTTP (health, score, peaks, auth...)
├── core/               # config.py, errors.py
├── db/                 # session.py + seed.py (données initiales)
├── domain/             # Logique métier pure (zero I/O) — score, weather_types
├── models/             # ORM SQLAlchemy
├── schemas/            # Pydantic Request/Response
├── services/           # Intégrations I/O (cache Redis, providers HTTP)
└── main.py             # Point d'entrée FastAPI
alembic/                # Migrations DB
scripts/                # Outils dev (generate_peaks.py, enrich_region.py)
tests/                  # Tests unitaires
tests/features/         # Tests de feature (flux HTTP complets)
docs/                   # Documentation par feature
```

## Variables d'environnement

Copie `.env.example` en `.env` et remplis les valeurs :

```bash
cp .env.example .env
```

| Variable            | Description                                       |
| ------------------- | ------------------------------------------------- |
| `DATABASE_URL`      | URL PostgreSQL async (`postgresql+asyncpg://...`) |
| `REDIS_URL`         | URL Redis (`redis://localhost:6379`)              |
| `WEATHER_API_KEY`   | Non requis — Open-Meteo est gratuit sans clé      |
| `SUPABASE_URL`      | URL du projet Supabase                            |
| `SUPABASE_KEY`      | Clé publique Supabase (validation JWT locale)     |
| `POSTHOG_API_KEY`   | Clé PostHog analytics                             |
| `EXPO_ACCESS_TOKEN` | Token Expo Push Notifications                     |

## Documentation features

Chaque feature implementée a sa documentation dans `docs/` :

- [Setup squelette FastAPI](docs/story-1-2-setup-backend.md)
- [Auth Supabase JWT](docs/story-2-1-auth-supabase.md)
- [Algorithme score mer de nuage](docs/story-3-1-algorithme-score.md)
- [Seed base de données des sommets](docs/story-3-2-seed-sommets.md)
- [Gestion des données sommets — guide opérationnel](docs/peaks-data-management.md)
- [Refactoring domain/ layer](docs/story-refactor-domain-layer.md)
- [Contrat score de présentation — story 3.5](docs/story-3-5-contrat-score-presentation.md)
- [Refactorisation i18n score — traduction déplacée côté mobile](docs/story-refacto-i18n-score.md)
