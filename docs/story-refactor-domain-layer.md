# Refactoring : domain/ layer

_Mise à jour le 2026-03-28_

## Ce qui a été fait

- Créé `app/domain/` — couche domaine pure (zero I/O)
- Déplacé la logique de score depuis `app/services/score.py` vers le domain layer
- Déplacé les types météo partagés dans `app/domain/weather_types.py`
- Éclaté le score en modules plus petits : `score.py`, `score_components.py`, `score_context.py`
- Mis à jour les imports dans les routes, services et tests

## Fichiers créés

- `app/domain/__init__.py` — package marker vide
- `app/domain/score.py` — orchestration du score mer de nuage (zero I/O)
- `app/domain/score_components.py` — composantes métier et seuils produit
- `app/domain/score_context.py` — sélection du contexte i18n et des paramètres
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
app/domain/score_components.py ← composantes pures + seuils
     ↑
app/domain/score_context.py    ← contexte produit / i18n stable
     ↑
app/domain/score.py            ← orchestre score + verdict + contrat de sortie
     ↑
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
    score.py         # orchestration score / verdict / contrat
    score_components.py # composantes métier et seuils
    score_context.py # contexte i18n / produit
    weather_types.py # WeatherData, PressureLevelData, WeatherProvider ABC
  services/         # I/O uniquement
    weather.py      # cache Redis
    weather_providers/
      __init__.py
      open_meteo.py # provider HTTP Open-Meteo
```

## Acceptance Criteria vérifiés

- [x] la logique métier score n'importe ni Redis, ni HTTP, ni SQLAlchemy
- [x] les types météo partagés vivent dans le domain layer
- [x] les composantes score et le contexte produit sont isolés dans des modules dédiés
- [x] les routes et services importent la logique métier depuis `app/domain/`
- [x] `make validate` reste la commande de vérification de référence
