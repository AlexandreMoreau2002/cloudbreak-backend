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
make dev      # démarrer db + redis
make down     # arrêter
make logs     # suivre les logs en temps réel
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
├── db/                 # session.py SQLAlchemy
├── domain/             # Logique métier pure (zero I/O) — score, weather_types
├── models/             # ORM SQLAlchemy
├── schemas/            # Pydantic Request/Response
├── services/           # Intégrations I/O (cache Redis, providers HTTP)
└── main.py             # Point d'entrée FastAPI
alembic/                # Migrations DB
tests/                  # Tests unitaires
tests/features/         # Tests de feature (flux HTTP complets)
docs/                   # Documentation par feature
```

## Variables d'environnement

Copie `.env.example` en `.env` et remplis les valeurs :

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | URL PostgreSQL async (`postgresql+asyncpg://...`) |
| `REDIS_URL` | URL Redis (`redis://localhost:6379`) |
| `WEATHER_API_KEY` | Clé API OpenWeather ou Weatherbit |
| `SUPABASE_URL` | URL du projet Supabase |
| `SUPABASE_KEY` | Clé publique Supabase (validation JWT locale) |
| `POSTHOG_API_KEY` | Clé PostHog analytics |
| `EXPO_ACCESS_TOKEN` | Token Expo Push Notifications |

## Documentation features

Chaque feature implementée a sa documentation dans `docs/` :

- [Setup squelette FastAPI](docs/story-1-2-setup-backend.md)
- [Refactoring domain/ layer](docs/story-refactor-domain-layer.md)
