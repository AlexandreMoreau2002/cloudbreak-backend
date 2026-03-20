# Refactoring : domain/ layer

## Ce qui a été fait

- Créé `app/domain/` — couche domaine pure (zero I/O)
- Déplacé `app/services/score.py` → `app/domain/score.py`
- Déplacé `app/services/weather_providers/base.py` → `app/domain/weather_types.py`
- Supprimé les anciens fichiers source
- Mis à jour tous les imports dans les fichiers source et les tests

## Fichiers créés

- `app/domain/__init__.py` — package marker vide
- `app/domain/score.py` — algorithme de score mer de nuage (zero I/O)
- `app/domain/weather_types.py` — WeatherData, PressureLevelData, WeatherProvider ABC

## Fichiers modifiés (imports)

- `app/services/weather.py`
- `app/services/weather_providers/open_meteo.py`
- `app/api/v1/endpoints/score.py`
- `tests/test_score.py`
- `tests/test_weather.py`
- `tests/test_open_meteo.py`
- `tests/test_api_score.py`

## Comment ça fonctionne

### Séparation des responsabilités

- `app/domain/` — logique métier pure, aucun import I/O (pas de redis, httpx, SQLAlchemy)
- `app/services/` — intégrations I/O (cache Redis, appels HTTP Open-Meteo)

### Flux des imports

```
app/domain/weather_types.py  ← types partagés (WeatherData, PressureLevelData, WeatherProvider)
     ↑
app/domain/score.py           ← algo score (importe WeatherData depuis domain)
app/services/weather.py       ← cache Redis (importe depuis domain)
app/services/weather_providers/open_meteo.py  ← HTTP provider (importe depuis domain)
     ↑
app/api/v1/endpoints/score.py ← endpoint (importe calculate_score depuis domain)
```

## Comment tester

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -v          # tous les tests doivent passer
python -m ruff check .              # 0 erreur
mypy app/                           # 0 erreur
```

Ou en une commande :

```bash
make validate
```

## Architecture finale

```
app/
  domain/           # pure, zero I/O
    __init__.py
    score.py        # algorithme mer de nuage
    weather_types.py # WeatherData, PressureLevelData, WeatherProvider ABC
  services/         # I/O uniquement
    weather.py      # cache Redis
    weather_providers/
      __init__.py
      open_meteo.py # provider HTTP Open-Meteo
```
