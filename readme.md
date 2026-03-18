# cloudbreak-backend

API backend de l'application Cloudbreak — prédit la probabilité de mer de nuage depuis un sommet donné.

## Stack

- **Python 3.12** + **FastAPI 0.115**
- **PostgreSQL 16** — base de données principale
- **Redis 7** — cache météo (TTL 10min) + quota freemium
- **SQLAlchemy async** + **Alembic** — ORM et migrations
- **Pydantic v2** — validation et settings
- **Gunicorn + Uvicorn** — serveur de production

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

## Lancer en dev

```bash
# Démarrer PostgreSQL + Redis en local
docker compose -f ../infra/docker-compose.dev.yml up -d

# Lancer les migrations
alembic upgrade head

# Démarrer le serveur
uvicorn app.main:app --reload
```

L'API est disponible sur http://localhost:8000
La doc Swagger est sur http://localhost:8000/docs

## Qualité

```bash
ruff check .          # lint
ruff format .         # format
mypy app/             # typage
pytest                # tous les tests
pytest --cov=app      # avec couverture
```

## Structure

```
app/
├── api/v1/endpoints/   # Routes HTTP (health, score, peaks, auth...)
├── core/               # config.py, errors.py
├── db/                 # session.py SQLAlchemy
├── models/             # ORM SQLAlchemy
├── schemas/            # Pydantic Request/Response
├── services/           # Logique métier (score, weather...)
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
