# 🌤️ Architecture météo & cache — Cloudbreak Backend

Architecture du pipeline météo : de la requête mobile jusqu'au score, en passant par Open-Meteo et Redis.

---

## 🎯 Le problème à résoudre

Un écran mobile type affiche **42 slots** (7 jours × 6 heures par jour).
Chaque slot = 1 appel potentiel `GET /api/v1/score?peak_id=&date=&hour=`.

Sans cache, cela représente :

| Scénario | Appels Open-Meteo potentiels |
|----------|------------------------------|
| 1 user, 1 sommet, 42 slots | 42 appels |
| 1 user, 5 sommets, 42 slots | 210 appels |
| 10 users simultanés, 1 sommet | 420 appels en rafale |

Open-Meteo est gratuit mais rate-limité (429 observé lors de la génération des peaks en story 3.2).
Un cache Redis intercale une couche de protection entre le backend et l'API externe.

---

## 📦 Stratégie de cache Redis

### Granularité de la clé

```
weather:{lat}:{lng}:{date}:{hour}
```

Exemples réels :
```
weather:45.8326:6.8652:2026-10-15:6
weather:45.8326:6.8652:2026-10-15:9
weather:43.1:5.87:2026-10-15:6
```

| Dimension | Granularité | Raison |
|-----------|-------------|--------|
| Coordonnées | `lat:lng` exact | Chaque sommet a sa propre position GPS → données météo différentes |
| Date | jour ISO 8601 | Prévision par journée |
| Heure | heure entière 0-23 | Open-Meteo retourne 24 valeurs horaires par requête, on extrait 1 index |

### TTL : 600 secondes (10 minutes)

```python
CACHE_TTL = 600  # app/services/weather.py
```

Pourquoi 10 minutes :
- Les prévisions Open-Meteo sont mises à jour toutes les heures (modèle GFS / IFS)
- 10 minutes = bon compromis fraîcheur / économie d'appels
- Un user qui recharge l'écran plusieurs fois dans la minute reçoit les données cachées
- En cas de pointe de trafic, la fenêtre de 10 minutes absorbe les rafales

### Ce qui est caché

La réponse **parsée et normalisée** — un `WeatherData` sérialisé en JSON :

```python
# Stockage (weather.py)
await self._redis.setex(cache_key, CACHE_TTL, json.dumps(asdict(weather)))

# Lecture
return _weather_data_from_dict(json.loads(cached))
```

Ce qui est stocké par clé (`~350 bytes` JSON) :

```json
{
  "cloud_base": 1200,
  "humidity": 85.0,
  "wind_speed": 8.0,
  "temperature_2m": 12.0,
  "temperature_850hpa": 6.5,
  "temperature_925hpa": 4.0,
  "pressure": 1018.0,
  "cloud_cover_low": 72.0,
  "month": 10,
  "pressure_levels": [
    {"pressure_hpa": 925, "altitude_m": 800, "temperature_c": 4.0, "relative_humidity": 91.0, "dew_point_spread": 1.2},
    ...
  ]
}
```

**Pas la réponse brute Open-Meteo** — les 24 heures × tous les niveaux de pression.
Seule l'heure demandée est extraite et stockée, ce qui réduit la taille et découple le cache du format API externe.

---

## 🗻 Données météo par sommet

### Pourquoi lat/lng détermine les données météo

Open-Meteo interpole les données de son modèle numérique de prévision à la position GPS exacte du sommet.
Deux sommets à 20 km de distance reçoivent des données différentes.

```
Peak (DB)
  ├── lat    = 45.8326   ← envoyé à Open-Meteo comme paramètre de localisation
  ├── lng    = 6.8652    ←
  └── altitude = 4808   ← utilisé UNIQUEMENT dans calculate_score(), pas dans l'appel météo
```

### Rôle de `peak.altitude` dans le calcul

Open-Meteo retourne la météo **au niveau de la coordonnée GPS**, pas au sommet lui-même.
L'altitude du sommet est une donnée de référence pour comparer avec `cloud_base` :

```python
# score.py — conditions bloquantes
if weather.cloud_base >= peak_altitude:   # nuages au-dessus du sommet → impossible
    return ScoreResult(score=0, verdict="none", ...)

# Composante cloud_base (poids 0.35)
# Score max si cloud_base ≤ (peak_altitude - 200m) → nuages bien sous le sommet
# Score nul si cloud_base ≥ (peak_altitude + 500m) → nuages clairement au-dessus
```

### Diagramme : sommet → données météo → score

```
Peak (PostgreSQL)
  id, name, slug
  lat=45.8326, lng=6.8652   ──────────────────────────────┐
  altitude=4808 (mètres)  ──────────────────────────────┐ │
                                                         │ │
                                                         ▼ │
                                            Open-Meteo API │
                                         ?latitude=45.8326 │
                                         &longitude=6.8652 │
                                         &start_date=...   │
                                         &hourly=...       │
                                                  │        │
                                                  ▼        │
                                            WeatherData    │
                                          cloud_base=1200m │
                                          humidity=85%     │
                                          wind_speed=8kmh  │
                                          ...              │
                                                  │        │
                                                  ▼        ▼
                                            calculate_score(weather, peak_altitude=4808)
                                                  │
                                                  ├── cloud_base (1200) < peak_altitude (4808) ✅
                                                  ├── cloud_cover_low (72%) >= 45% ✅
                                                  ├── cloud_base_score = 1.0 (bien sous le sommet)
                                                  ├── inversion_score = f(T850 - T925)
                                                  ├── humidity_score = f(85%)
                                                  ├── wind_score = f(8 km/h)
                                                  └── → score=82, verdict="high"
```

---

## ⏰ Fenêtre temporelle — batch des heures

### Comment Open-Meteo retourne les données

Une seule requête `GET /v1/forecast` retourne **24 valeurs horaires** pour la journée complète :

```python
# open_meteo.py — paramètre start_date = end_date = la même date
params = {
    "start_date": date,   # "2026-10-15"
    "end_date": date,     # "2026-10-15" — même date
    "hourly": "relative_humidity_2m,wind_speed_10m,cloud_cover_low,...",
}
# Retour : {"hourly": {"time": [...24 timestamps...], "relative_humidity_2m": [...24 values...]}}
```

### Extraction de l'heure demandée

```python
idx = hour  # index direct — heure locale 0-23
temp_850 = hourly.get("temperature_850hPa", [8.0] * 24)[idx]
humidity = hourly.get("relative_humidity_2m", [70.0] * 24)[idx]
# etc. pour chaque variable
```

### Conséquence sur le cache

Open-Meteo fait 1 appel par `(lat, lng, date)` quelle que soit l'heure demandée.
Mais le cache est clé par `(lat, lng, date, hour)` — chaque heure est stockée séparément.

Cela signifie que pour un même sommet et une même date :
- Requête heure=6 → cache MISS → appel Open-Meteo → stockage clé `weather:...:6`
- Requête heure=9 → cache MISS → appel Open-Meteo → stockage clé `weather:...:9`
- Requête heure=9 (même user, 5 min après) → cache HIT → retour immédiat

```
Slot    Clé Redis                         1er appel         2e appel
6h   →  weather:45.83:6.86:2026-10-15:6  MISS → API        HIT (600s TTL)
9h   →  weather:45.83:6.86:2026-10-15:9  MISS → API        HIT (600s TTL)
12h  →  weather:45.83:6.86:2026-10-15:12 MISS → API        HIT (600s TTL)
```

Chaque heure déclenche un appel Open-Meteo distinct — pas de batch côté serveur.
En revanche, si deux users demandent le même sommet/date/heure dans la fenêtre de 10 minutes, seul le premier appelle l'API.

---

## 🔄 Flux complet optimisé

```
Mobile (42 slots : 7 jours × 6 heures)
  │
  │  GET /api/v1/score?peak_id=mont-blanc&date=2026-10-15&hour=6
  │  Authorization: Bearer {jwt}
  ▼
Backend FastAPI
  │
  ├── 1. JWT validé (dependencies.py)
  ├── 2. Quota Redis vérifié (freemium: 1 check/jour, quota:user:{id}:{date})
  ├── 3. Peak récupéré en PostgreSQL (lat, lng, altitude)
  │
  ├── 4. WeatherService.get_forecast(lat, lng, date, hour=6)
  │       │
  │       ├── cache_key = "weather:45.8326:6.8652:2026-10-15:6"
  │       │
  │       ├── Redis GET cache_key
  │       │       │
  │       │       ├── HIT  → désérialiser JSON → WeatherData ─────────────┐
  │       │       │         log: weather_cache_hit                         │
  │       │       │                                                        │
  │       │       └── MISS → OpenMeteoProvider.get_forecast()              │
  │       │                   │                                            │
  │       │                   ├── GET api.open-meteo.com/v1/forecast       │
  │       │                   │   ?latitude=45.8326                        │
  │       │                   │   &longitude=6.8652                        │
  │       │                   │   &start_date=2026-10-15                   │
  │       │                   │   &end_date=2026-10-15                     │
  │       │                   │   &hourly=relative_humidity_2m,...         │
  │       │                   │                                            │
  │       │                   ├── Extraire index idx=6 (heure demandée)    │
  │       │                   ├── Skew-T → cloud_base via RH + dew spread  │
  │       │                   └── WeatherData normalisé                    │
  │       │                           │                                    │
  │       │                   Redis SETEX cache_key 600 json(WeatherData) ─┤
  │       │                                                                │
  │       └── WeatherData ◄───────────────────────────────────────────────┘
  │
  ├── 5. calculate_score(weather, peak_altitude=4808)
  │       ├── Hard gates (cloud_base vs altitude, cloud_cover_low)
  │       └── Score pondéré 5 composantes
  │
  └── 6. ScoreResponse JSON → Mobile
        score, verdict, cloud_base, conditions, cloud_layer_viz, ...
```

### Inspecter le cache en dev

```bash
# Voir toutes les clés météo cachées
docker exec cloudbreak-redis redis-cli KEYS "weather:*"

# Inspecter une clé (WeatherData JSON)
docker exec cloudbreak-redis redis-cli GET "weather:45.8326:6.8652:2026-10-15:6"

# Voir le TTL restant (secondes)
docker exec cloudbreak-redis redis-cli TTL "weather:45.8326:6.8652:2026-10-15:6"

# Vider le cache météo pour forcer un appel API frais
docker exec cloudbreak-redis redis-cli DEL "weather:45.8326:6.8652:2026-10-15:6"

# Vider tout le cache météo (tous les sommets/dates)
docker exec cloudbreak-redis redis-cli --scan --pattern "weather:*" | xargs docker exec -i cloudbreak-redis redis-cli DEL
```

---

## ⚠️ Limites et trade-offs

### Staleness du cache

Les données météo peuvent être vieilles de jusqu'à 10 minutes.
Acceptable car :
- Open-Meteo met à jour ses modèles numériques toutes les heures (pas plus fréquent)
- Une mer de nuage ne se dissipe pas en 10 minutes
- Le cas d'usage principal est la planification (J+1, J+7) — pas le temps réel

### Comportement si Open-Meteo est down

```python
# score.py endpoint
try:
    weather = await weather_service.get_forecast(...)
except Exception as exc:
    logger.error("weather_provider_failed", extra={"peak_id": ..., "error": str(exc)})
    raise HTTPException(
        status_code=503,
        detail={"detail": "Données météo indisponibles", "code": "WEATHER_UNAVAILABLE"},
    )
```

- Aucun fallback provider implémenté en MVP (Météo-France prévu mais non connecté)
- Le cache Redis protège pendant 10 minutes si l'API tombe après un premier appel réussi
- Au-delà du TTL en cas de panne prolongée → 503 côté mobile

### Pas de cache cross-peaks

Deux sommets proches géographiquement (ex: Mont-Blanc et Aiguille du Midi) ont des coordonnées différentes → deux clés Redis distinctes → deux appels Open-Meteo séparés.
Open-Meteo interpole sur une grille ~1km — les données seront quasi-identiques mais le cache ne le sait pas.

### Taille mémoire Redis estimée

| Scénario | Clés | Taille estimée |
|----------|------|----------------|
| 1 sommet, 6 heures, 7 jours | 42 | ~15 KB |
| 100 sommets actifs, 6h/j, 7j | 4 200 | ~1.5 MB |
| Pic trafic : 1 000 sommets | 42 000 | ~15 MB |

Très faible par rapport à la mémoire Redis disponible. Pas de politique d'éviction nécessaire en MVP.

---

## 📁 Fichiers clés

| Fichier | Rôle |
|---------|------|
| `app/services/weather.py` | Cache Redis + dispatch vers provider |
| `app/domain/weather_types.py` | Interface `WeatherProvider` + dataclasses `WeatherData`, `PressureLevelData` |
| `app/services/weather_providers/open_meteo.py` | Implémentation Open-Meteo + Skew-T |
| `app/domain/score.py` | `calculate_score(weather, peak_altitude)` |
| `app/domain/score_components.py` | 5 composantes + poids + seuils + caps |
| `app/api/v1/endpoints/score.py` | Endpoint GET `/api/v1/score` — orchestre tout |
| `app/models/peak.py` | Modèle SQLAlchemy — `lat`, `lng`, `altitude` |
