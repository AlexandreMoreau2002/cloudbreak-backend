# Story 3-1 — Pipeline Score Mer de Nuage

## Ce qui a été fait

| Fichier | Action |
|---------|--------|
| `app/models/peak.py` | Fix bug : suppression de la `Base` locale, import depuis `app.db.session` |
| `app/services/weather_providers/base.py` | Nouveau dataclass `PressureLevelData`, enrichissement `WeatherData`, ajout `hour` à `get_forecast()` |
| `app/services/weather_providers/open_meteo.py` | Refonte complète : Skew-T, niveaux réduits (925/850/800/700 hPa), `cloud_cover_low`, paramètre `hour` |
| `app/services/score.py` | Seuils corrigés, inversion T850/T925, composante pression (poids 0.10), bonus cloud_cover_low ±5% |
| `app/services/weather.py` | Ajout `hour` au cache key et à la signature, désérialisation `PressureLevelData` |
| `app/api/v1/endpoints/score.py` | Transmission de `hour` au service météo |
| `app/schemas/score.py` | Ajout `pressure_score` dans `ScoreConditionsSchema` |
| `tests/test_score.py` | Réécriture complète : nouveaux champs WeatherData, tests composante pression, tests bonus cloud_cover_low |
| `tests/test_weather.py` | Adaptation nouveaux champs, test clé cache avec `hour`, test clés distinctes par heure |
| `tests/test_open_meteo.py` | Réécriture complète : tests Skew-T (6 cas), tests `hour`, tests `cloud_cover_low` |
| `tests/test_api_score.py` | Adaptation `MOCK_WEATHER` aux nouveaux champs |

## Comment ça fonctionne

### Fix bug `Base` dupliquée
`Peak` importait sa propre `Base(DeclarativeBase)` au lieu de celle de `db/session.py`. Alembic et les tests utilisaient donc des métadonnées différentes. Corrigé : `Peak` importe maintenant `Base` depuis `app.db.session`.

### Estimation cloud_base — méthode Skew-T
L'ancienne méthode utilisait un seuil de RH > 80% sur une liste large de niveaux (1000–500 hPa). La recherche a confirmé que `cloud_cover` par niveau de pression est non fiable (Open-Meteo issue #416).

La nouvelle méthode Skew-T scan bottom-up les 4 niveaux retenus (925/850/800/700 hPa) :
- Critère de saturation : **RH >= 88%** ET **T - Td < 2°C**
- L'altitude est fournie directement par Open-Meteo via `geopotential_height_{P}hPa` (MSL, confirmé docs officielles)
- Si aucun niveau ne satisfait → ciel clair → `cloud_base = 5000m`

### Algorithme de score amélioré

| Composante | Poids ancien | Poids nouveau | Changement |
|-----------|-------------|--------------|------------|
| cloud_base | 0.40 | 0.35 | Légèrement réduit |
| humidity | 0.20 | 0.20 | Inchangé — seuil min 50% → 60% |
| wind | 0.20 | 0.15 | Réduit — seuil max 50 → 30 km/h |
| inversion | 0.20 | 0.20 | Inchangé — logique T850 vs T925 (plus T_altitude vs T_valley) |
| pressure | — | 0.10 | **Nouveau** — anticyclone > 1025 hPa = favorable |

**Inversion thermique** : comparaison T(850hPa) vs T(925hPa) au lieu de T_altitude vs T_valley. Physiquement plus correct — détecte l'inversion entre ~800m et ~1500m.

**Bonus cloud_cover_low** : validation croisée ±5%. Si `cloud_cover_low > 70%` ET `cloud_base < altitude_sommet` → +5%. Si `cloud_cover_low < 70%` ET `cloud_base >= altitude_sommet` → -5%.

### Paramètre `hour` dans le pipeline
`hour` traverse maintenant tout le pipeline :
- Endpoint → `WeatherService.get_forecast(hour=hour)` → `WeatherProvider.get_forecast(hour=hour)`
- Clé cache Redis : `weather:{lat}:{lng}:{date}:{hour}` (auparavant sans `hour`)
- `OpenMeteoProvider` utilise `idx = hour` au lieu du hardcode `idx = 6`

## Comment tester

```bash
cd backend
source .venv/bin/activate

# 1. Validation complète (lint + types + tests + coverage)
make validate

# 2. Tests unitaires ciblés
pytest tests/test_score.py -v
pytest tests/test_open_meteo.py -v
pytest tests/test_weather.py -v

# 3. Test endpoint (nécessite infra locale)
docker compose -f ../infra/docker-compose.dev.yml up -d
# puis :
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/score?peak_id=peak-1&date=2026-10-15&hour=6"
```

## Acceptance Criteria vérifiés

- [x] Méthode Skew-T implémentée (RH >= 88% + T-Td < 2°C) — 6 tests dédiés
- [x] Altitudes Open-Meteo en MSL via `geopotential_height_{P}hPa`
- [x] Niveaux réduits à 925/850/800/700 hPa (plus utiles pour mer de nuage)
- [x] Inversion thermique via T850 vs T925 (plus T_valley vs T_altitude)
- [x] Composante pression atmosphérique ajoutée (poids 0.10)
- [x] `WIND_MAX` corrigé à 30 km/h, `HUMIDITY_MIN` à 60%
- [x] Bonus cloud_cover_low ±5% (validation croisée)
- [x] Paramètre `hour` dans tout le pipeline (endpoint → cache → provider)
- [x] Clé cache `weather:{lat}:{lng}:{date}:{hour}`
- [x] Bug `Base` dupliquée dans `peak.py` corrigé
- [x] `pressure_score` dans `ScoreConditionsSchema`
- [x] 100% de couverture — 75 tests, 0 erreur mypy, 0 erreur ruff
