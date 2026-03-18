# Story 1-2 — Setup Backend FastAPI (Squelette Complet)

## Ce qui a été fait

Mise en place du squelette complet du backend FastAPI avec tous les outils de qualité configurés.

### Fichiers créés

| Fichier | Rôle |
|---------|------|
| `app/main.py` | Point d'entrée FastAPI, lifespan startup |
| `app/core/config.py` | Chargement des variables d'environnement via Pydantic Settings |
| `app/core/errors.py` | Constantes de codes d'erreur (QUOTA_EXCEEDED, PEAK_NOT_FOUND...) |
| `app/db/session.py` | Moteur SQLAlchemy async + générateur de session `get_db()` |
| `app/api/v1/endpoints/health.py` | Endpoint `GET /health` |
| `alembic/env.py` | Configuration Alembic pour les migrations async |
| `alembic.ini` | Config Alembic (URL DB, logs) |
| `pyproject.toml` | Config ruff (lint/format) + mypy (typage) + pytest |
| `requirements.txt` | Dépendances de production |
| `requirements-dev.txt` | Dépendances de développement |
| `tests/test_health.py` | Test smoke sur `/health` |

### Comment ça fonctionne

**FastAPI + lifespan** : au démarrage du serveur, un événement `startup` est loggué (pattern moderne `lifespan` au lieu du deprecated `on_event`).

**Pydantic Settings** : `config.py` lit automatiquement les variables d'environnement depuis `.env`. Si une variable manque, le serveur démarre quand même avec les valeurs par défaut (sauf en prod où tu voudras les rendre obligatoires).

**SQLAlchemy async** : `get_db()` est un générateur async injectable dans les routes FastAPI via `Depends(get_db)`. La session se ferme automatiquement après chaque requête.

**Alembic async** : configuré pour fonctionner avec SQLAlchemy async. Les migrations se créent avec `alembic revision --autogenerate` et s'appliquent avec `alembic upgrade head`.

**ErrorCode** : classe simple avec des constantes string. Utilisé dans les réponses d'erreur format `{"detail": "...", "code": "QUOTA_EXCEEDED"}`.

---

## Comment tester

### 1. Installer les dépendances

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Lancer le serveur

```bash
uvicorn app.main:app --reload
```

Tu dois voir dans le terminal :
```
INFO:     Application startup complete.
```

### 3. Tester l'endpoint /health

```bash
curl http://localhost:8000/health
```

Réponse attendue :
```json
{"status": "ok"}
```

Ou ouvre http://localhost:8000/docs dans le navigateur — tu verras la doc Swagger auto-générée avec le endpoint `/health`.

### 4. Lancer les outils qualité

```bash
ruff check .          # doit retourner : All checks passed!
ruff format --check . # doit retourner : N files already formatted
mypy app/             # doit retourner : Success: no issues found
pytest tests/test_health.py -v  # doit retourner : 1 passed
```

### 5. Vérifier la structure des dossiers

```bash
ls app/
# api  core  db  models  schemas  services  __init__.py  main.py

ls app/api/v1/endpoints/
# health.py  __init__.py

ls tests/
# features/  test_health.py  __init__.py
```

---

## Acceptance Criteria vérifiés

- ✅ `GET /health` répond `{"status": "ok"}`
- ✅ Structure dossiers complète (`api/v1/endpoints/`, `core/`, `models/`, `schemas/`, `services/`, `db/`, `tests/`)
- ✅ `errors.py` contient QUOTA_EXCEEDED, PEAK_NOT_FOUND, WEATHER_UNAVAILABLE, SUBSCRIPTION_REQUIRED
- ✅ `config.py` charge les variables d'environnement via Pydantic Settings
- ✅ `ruff check . && ruff format --check . && mypy app/` → zéro erreur
- ✅ `pytest` → 1 test smoke passant
