# 🌊 Score Algorithm — Mer de nuage

Documentation technique de l'algorithme de calcul de probabilité de mer de nuage.

---

## 🎯 Vue d'ensemble

L'algorithme calcule la **probabilité qu'un observateur positionné sur un sommet voie une mer de nuage** à un instant donné.

**Inputs :**
- `peak_altitude` : altitude du sommet en mètres (depuis la DB `peaks`)
- `WeatherData` : données météo normalisées (depuis Open-Meteo via cache Redis)

**Output :**
```python
ScoreResult(
    score=72,           # int, 0-100
    verdict="high",     # "none" | "low" | "medium" | "high"
    cloud_base=1800,    # int, altitude MSL de la base des nuages (mètres)
    conditions=ScoreConditions(
        cloud_base_score=0.9,
        humidity_score=0.8,
        wind_score=1.0,
        inversion_score=0.7,
        pressure_score=0.6,
    )
)
```

**Fichiers concernés :**

| Fichier | Rôle |
|---------|------|
| `app/domain/score.py` | Fonction principale `calculate_score()` |
| `app/domain/score_components.py` | Composantes individuelles + paramètres |
| `app/domain/score_context.py` | Présentation (fenêtre optimale, contexte i18n) |
| `app/domain/weather_types.py` | `WeatherData`, `WeatherProvider` interface |
| `app/services/weather.py` | Cache Redis TTL 10min |
| `app/services/weather_providers/open_meteo.py` | Appel API + méthode Skew-T |
| `app/api/v1/endpoints/score.py` | Endpoint `GET /api/v1/score` |

---

## 🚧 Conditions bloquantes (hard gates)

Vérifiées en premier, avant tout calcul. Si une condition est remplie → `score=0`, `verdict="none"`, retour immédiat.

### Gate 1 — Nuages au-dessus du sommet

```python
if weather.cloud_base >= peak_altitude:
    return ScoreResult(score=0, verdict="none", ...)
```

**Physique** : si la base des nuages est au niveau ou au-dessus du sommet, l'observateur est dans les nuages ou sous un ciel clair — pas de mer de nuage visible depuis le dessus.

### Gate 2 — Couverture nuageuse basse insuffisante

```python
CLOUD_COVER_LOW_BLOCKING_THRESHOLD = 45.0  # %

if weather.cloud_cover_low < CLOUD_COVER_LOW_BLOCKING_THRESHOLD:
    return ScoreResult(score=0, verdict="none", ...)
```

**Physique** : une couche nuageuse basse trop fragmentée (< 45% de couverture) ne forme pas un tapis continu — le phénomène de mer de nuage n'est pas crédible.

---

## 📐 Formule de score conditionnelle

Si aucun hard gate n'est déclenché, le score est calculé comme combinaison linéaire de 5 composantes.

```
score = WEIGHT_CLOUD_BASE * cloud_base_score   (0.35)
      + WEIGHT_HUMIDITY   * humidity_score      (0.20)
      + WEIGHT_INVERSION  * inversion_score     (0.20)
      + WEIGHT_WIND       * wind_score          (0.15)
      + WEIGHT_PRESSURE   * pressure_score      (0.10)
```

Chaque composante est un `float` normalisé entre `0.0` et `1.0`.
Le score brut est multiplié par 100 et arrondi → `int` dans `[0, 100]`.

### 📊 Poids des composantes

| Composante | Poids | Variable source |
|------------|-------|----------------|
| `cloud_base_score` | **35%** | `weather.cloud_base` / `peak_altitude` |
| `humidity_score` | **20%** | `weather.humidity` |
| `inversion_score` | **20%** | `weather.temperature_850hpa` - `weather.temperature_925hpa` |
| `wind_score` | **15%** | `weather.wind_speed` |
| `pressure_score` | **10%** | `weather.pressure` |

---

### 🔹 cloud_base_score (35%)

Distance entre la base des nuages et le sommet. Plus les nuages sont bas sous le sommet, plus le score est élevé.

```python
CLOUD_BASE_OPTIMAL_MARGIN = 200  # mètres — nuages bien sous le sommet → score 1.0
CLOUD_BASE_MAX_MARGIN = 500      # mètres au-dessus du sommet → score 0.0

def _cloud_base_component(cloud_base: int, peak_altitude: int) -> float:
    optimal_threshold = peak_altitude - CLOUD_BASE_OPTIMAL_MARGIN
    max_threshold = peak_altitude + CLOUD_BASE_MAX_MARGIN

    if cloud_base <= optimal_threshold:      # bien sous le sommet
        return 1.0
    if cloud_base >= max_threshold:          # au-dessus du sommet + marge
        return 0.0

    range_size = max_threshold - optimal_threshold
    return 1.0 - (cloud_base - optimal_threshold) / range_size  # interpolation linéaire
```

**Exemple sommet à 2000m :**

| `cloud_base` | Score |
|-------------|-------|
| ≤ 1800m | 1.0 |
| 2000m | 0.71 |
| 2300m | 0.29 |
| ≥ 2500m | 0.0 |

---

### 🔹 humidity_score (20%)

Humidité relative à 2m. Humidité élevée → air proche de la saturation → formation des nuages favorisée.

```python
HUMIDITY_MIN = 60.0  # % → score 0.0 (sous 60%, mer de nuage quasi impossible)
HUMIDITY_MAX = 95.0  # % → score 1.0

def _humidity_component(humidity: float) -> float:
    return max(0.0, min(1.0, (humidity - HUMIDITY_MIN) / (HUMIDITY_MAX - HUMIDITY_MIN)))
```

| `humidity` | Score |
|-----------|-------|
| ≤ 60% | 0.0 |
| 70% | 0.29 |
| 80% | 0.57 |
| 90% | 0.86 |
| ≥ 95% | 1.0 |

---

### 🔹 inversion_score (20%)

Inversion thermique entre 925 hPa (~800m) et 850 hPa (~1500m).
Une inversion thermique piège les nuages bas en empêchant leur ascension.

```python
INVERSION_STRONG = 5.0   # °C de delta → inversion marquée → score 1.0
INVERSION_ABSENT = -3.0  # °C de delta → gradient normal → score 0.0

def _inversion_component(temp_925: float, temp_850: float) -> float:
    delta = temp_850 - temp_925  # positif = air plus chaud en altitude = inversion
    return max(0.0, min(1.0, (delta - INVERSION_ABSENT) / (INVERSION_STRONG - INVERSION_ABSENT)))
```

| `delta T(850) - T(925)` | Interprétation | Score |
|------------------------|----------------|-------|
| ≤ -3°C | Gradient normal (convection) | 0.0 |
| 0°C | Neutre | 0.37 |
| +3°C | Inversion modérée | 0.75 |
| ≥ +5°C | Inversion marquée | 1.0 |

---

### 🔹 wind_score (15%)

Vitesse du vent à 10m. Vent faible = nuages stables = mer de nuage homogène. Vent fort = dispersion.

```python
WIND_MIN = 5.0   # km/h → score 1.0 (calme parfait)
WIND_MAX = 30.0  # km/h → score 0.0 (vent dispersant)

def _wind_component(wind_speed: float) -> float:
    if wind_speed <= WIND_MIN:
        return 1.0
    if wind_speed >= WIND_MAX:
        return 0.0
    return 1.0 - (wind_speed - WIND_MIN) / (WIND_MAX - WIND_MIN)
```

| `wind_speed` | Score |
|-------------|-------|
| ≤ 5 km/h | 1.0 |
| 10 km/h | 0.8 |
| 20 km/h | 0.4 |
| ≥ 30 km/h | 0.0 |

---

### 🔹 pressure_score (10%)

Pression de surface. Anticyclone (haute pression) = stabilité atmosphérique = conditions favorables.

```python
PRESSURE_HIGH = 1025.0  # hPa → score 1.0 (anticyclone)
PRESSURE_LOW  = 1010.0  # hPa → score 0.0

def _pressure_component(pressure: float) -> float:
    return max(0.0, min(1.0, (pressure - PRESSURE_LOW) / (PRESSURE_HIGH - PRESSURE_LOW)))
```

| `pressure` | Score |
|-----------|-------|
| ≤ 1010 hPa | 0.0 |
| 1015 hPa | 0.33 |
| 1020 hPa | 0.67 |
| ≥ 1025 hPa | 1.0 |

---

## 🔒 Plafonnement du score (score caps)

Après calcul du score brut, `_apply_score_caps()` plafonne les faux positifs évidents.
Ces caps sont appliqués cumulativement (ordre d'application : inversion → cloud_base → cloud_cover → wind).

| Condition | Cap absolu | Facteur multiplicatif |
|-----------|-----------|----------------------|
| Pas d'inversion (T850 ≤ T925) | 39 | × 0.55 |
| `cloud_base` trop proche du sommet (< 150m sous sommet) | 55 | × 0.78 |
| `cloud_cover_low` < 55% (couche fragile) | 55 | × 0.82 |
| Vent ≥ 20 km/h (dispersant) | 39 | × 0.60 |

Le cap effectif appliqué pour chaque condition est `min(cap_absolu, int(raw_score × facteur))`.

---

## 🏆 Conversion score → verdict

Le verdict est dérivé après application des caps.

### Règle "high" (stricte — toutes conditions requises)

```python
if (
    final_score >= 70
    and weather.temperature_850hpa > weather.temperature_925hpa   # inversion confirmée
    and weather.cloud_base <= peak_altitude - 150                   # nuages ≥ 150m sous le sommet
    and weather.cloud_cover_low >= 55.0                             # couverture dense
):
    verdict = "high"
```

### Règles "medium" et "low"

```python
elif final_score >= 40:
    verdict = "medium"
else:
    verdict = "low"
```

### Tableau récapitulatif

| Score | Conditions supplémentaires | Verdict |
|-------|---------------------------|---------|
| — | Hard gate déclenché | `none` |
| ≥ 70 | Inversion + cloud_base ≥ 150m sous sommet + cloud_cover ≥ 55% | `high` |
| ≥ 70 | Conditions "high" non toutes remplies | `medium` |
| 40–69 | — | `medium` |
| 0–39 | — | `low` |

---

## 🌤️ Données météo utilisées

### Source Open-Meteo

Tous les champs proviennent de `GET https://api.open-meteo.com/v1/forecast` avec `wind_speed_unit=kmh` et `timezone=Europe/Paris`.
L'index horaire = `hour` (0-23) passé en paramètre (défaut : 6h).

### Mapping champ API → variable algorithme

| Variable Open-Meteo | Champ `WeatherData` | Utilisé par |
|--------------------|---------------------|-------------|
| `relative_humidity_2m[hour]` | `humidity` | `humidity_score` |
| `wind_speed_10m[hour]` | `wind_speed` | `wind_score` |
| `surface_pressure[hour]` | `pressure` | `pressure_score` |
| `temperature_2m[hour]` | `temperature_2m` | contexte |
| `temperature_850hPa[hour]` | `temperature_850hpa` | `inversion_score` + verdict "high" |
| `temperature_925hPa[hour]` | `temperature_925hpa` | `inversion_score` + verdict "high" |
| `cloud_cover_low[hour]` | `cloud_cover_low` | hard gate + caps + verdict |
| Profil Skew-T (voir ci-dessous) | `cloud_base` | `cloud_base_score` + hard gate |

### Niveaux de pression (profil vertical)

```python
PRESSURE_LEVELS = [925, 850, 800, 700]
# 925 hPa ≈ 800m | 850 hPa ≈ 1500m | 800 hPa ≈ 1950m | 700 hPa ≈ 3000m
```

Pour chaque niveau, Open-Meteo fournit :
`temperature_{p}hPa`, `relative_humidity_{p}hPa`, `geopotential_height_{p}hPa`, `dew_point_{p}hPa`

### Calcul de cloud_base — méthode Skew-T

`cloud_base` n'est pas un champ direct Open-Meteo — il est **déduit** du profil vertical.

```python
CLOUD_RH_THRESHOLD = 88.0        # humidité relative minimale (%)
CLOUD_DEWPOINT_SPREAD_MAX = 2.0  # T - Td maximal (°C) — air saturé

# Scan bottom-up des niveaux de pression
for level in sorted(levels, key=lambda lv: lv.altitude_m):
    if level.relative_humidity >= 88.0 and level.dew_point_spread < 2.0:
        return level.altitude_m  # premier niveau saturé = base des nuages

return 5000  # aucun niveau saturé → ciel clair
```

Pourquoi Skew-T et non `cloud_cover_*` directement : le champ `cloud_cover` par niveau de pression d'Open-Meteo est non fiable (issue GitHub Open-Meteo #416). La méthode RH + T-Td est validée météorologiquement.

---

## 💾 Cache Redis

```
Clé   : weather:{lat}:{lng}:{date}:{hour}
TTL   : 600s (10 minutes)
```

Le `WeatherService` intercepte chaque appel provider avec ce cache :

```
GET /api/v1/score?peak_id=X&date=Y&hour=Z
  └─ WeatherService.get_forecast()
       ├─ Redis HIT  → désérialise WeatherData → calculate_score()
       └─ Redis MISS → OpenMeteoProvider.get_forecast() → stocke en cache → calculate_score()
```

---

## 🔄 Flux complet

```
GET /api/v1/score?peak_id=&date=&hour=
         │
         ▼
  check_quota (dependency)
  ├── Freemium : 1 check/jour (Redis quota:*)
  └── Pro      : illimité
         │
         ▼
  get_peak_by_id()  →  PostgreSQL (table peaks)
         │
         ▼
  WeatherService.get_forecast()
  ├── Redis HIT  → WeatherData
  └── Redis MISS → OpenMeteoProvider → Skew-T → WeatherData
         │
         ▼
  calculate_score(weather, peak_altitude)
  ├── Hard gate 1 : cloud_base >= peak_altitude → none (score 0)
  ├── Hard gate 2 : cloud_cover_low < 45%       → none (score 0)
  ├── 5 composantes pondérées → raw_score
  ├── _apply_score_caps()    → final_score
  └── Verdict : high / medium / low
         │
         ▼
  build_score_presentation()
  ├── fenêtre optimale (autour du lever du soleil)
  ├── stabilité en heures
  ├── code contexte i18n
  └── profil vertical cloud_layer_viz
         │
         ▼
  ScoreResponse (JSON direct, pas de wrapper)
```

---

## 🧪 Exemples concrets

### Cas 1 — Mer de nuage parfaite

Sommet à 2000m, conditions optimales de novembre matin.

| Variable | Valeur |
|---------|--------|
| `cloud_base` | 1650m |
| `cloud_cover_low` | 85% |
| `humidity` | 92% |
| `wind_speed` | 3 km/h |
| `temperature_850hpa` | 4°C |
| `temperature_925hpa` | 1°C |
| `pressure` | 1023 hPa |

Calcul :
```
Hard gates : cloud_base (1650) < peak (2000) ✓ | cloud_cover_low (85%) > 45% ✓

cloud_base_score  = 1.0          (1650 ≤ 2000 - 200 = 1800)
humidity_score    = 0.91         ((92 - 60) / (95 - 60))
wind_score        = 1.0          (3 ≤ 5)
inversion_score   = 0.87         (delta=3°C → (3 - (-3)) / (5 - (-3)))
pressure_score    = 0.87         ((1023 - 1010) / (1025 - 1010))

raw_score = 0.35×1.0 + 0.20×0.91 + 0.15×1.0 + 0.20×0.87 + 0.10×0.87
          = 0.35 + 0.182 + 0.15 + 0.174 + 0.087 = 0.943

final_score = round(min(1.0, 0.943) × 100) = 94

Caps :
  - Inversion OK (T850 > T925) → pas de cap
  - cloud_base (1650) ≤ 2000 - 150 = 1850 → pas de cap
  - cloud_cover_low (85%) ≥ 55% → pas de cap
  - vent (3) < 20 → pas de cap

Verdict "high" ? score=94 ≥ 70 ✓ | inversion ✓ | cloud_base (1650) ≤ 1850 ✓ | cloud_cover (85%) ≥ 55% ✓
→ verdict = "high"
```

**Résultat** : `score=94`, `verdict="high"`

---

### Cas 2 — Hard gate : nuages au-dessus du sommet

Sommet à 1200m, brouillard haute altitude.

| Variable | Valeur |
|---------|--------|
| `cloud_base` | 1400m |
| `cloud_cover_low` | 70% |

```
Hard gate 1 : cloud_base (1400) >= peak_altitude (1200)  → bloquant
→ score=0, verdict="none"
```

**Résultat** : `score=0`, `verdict="none"` — l'observateur serait dans les nuages ou sous eux.

---

### Cas 3 — Hard gate : ciel trop dégagé

Sommet à 2500m, beau temps d'été.

| Variable | Valeur |
|---------|--------|
| `cloud_base` | 3200m (Skew-T: aucun niveau saturé → 5000m) |
| `cloud_cover_low` | 12% |

```
Hard gate 1 : cloud_base (5000) >= peak_altitude (2500)  → bloquant
→ score=0, verdict="none"
```

Même si le gate 1 ne s'était pas déclenché :
```
Hard gate 2 : cloud_cover_low (12%) < 45%  → bloquant
→ score=0, verdict="none"
```

**Résultat** : `score=0`, `verdict="none"` — pas de couche nuageuse basse crédible.

---

### Cas 4 — Score "medium" avec caps

Sommet à 1800m, conditions moyennes.

| Variable | Valeur |
|---------|--------|
| `cloud_base` | 1700m |
| `cloud_cover_low` | 50% |
| `humidity` | 75% |
| `wind_speed` | 22 km/h |
| `temperature_850hpa` | 2°C |
| `temperature_925hpa` | 3°C (pas d'inversion) |
| `pressure` | 1012 hPa |

```
Hard gates : passés ✓

cloud_base_score  = 1.0          (1700 ≤ 1800 - 200 = 1600? non → 1700 > 1600)
                                  → interpolation : 1 - (1700-1600)/(2300-1600) = 0.857
humidity_score    = 0.43         ((75 - 60) / 35)
wind_score        = 0.32         (1 - (22-5)/(30-5))
inversion_score   = 0.0          (delta = 2-3 = -1°C → (-1-(-3))/(5-(-3)) = 0.25)
                                  → max(0, 0.25) = 0.25
pressure_score    = 0.13         ((1012 - 1010) / 15)

raw_score = 0.35×0.857 + 0.20×0.43 + 0.15×0.32 + 0.20×0.25 + 0.10×0.13
          = 0.30 + 0.086 + 0.048 + 0.05 + 0.013 = 0.497 → 50

Caps :
  - T850 (2) ≤ T925 (3) → pas d'inversion → cap = min(39, round(50×0.55)) = min(39,27) = 27
  - cloud_cover_low (50%) < 55% → cap = min(55, round(27×0.82)) = min(55,22) = 22
  - vent (22) ≥ 20 → cap = min(39, round(22×0.60)) = min(39,13) = 13

final_score = 13
```

**Résultat** : `score=13`, `verdict="low"` — caps consécutifs réduisent fortement le score.

---

## 📚 Fichiers de test associés

| Fichier | Ce qui est testé |
|---------|-----------------|
| `tests/test_score.py` | `calculate_score()` — hard gates, composantes, seuils, caps |
| `tests/test_score_components.py` | Chaque `_*_component()` isolément |
| `tests/test_weather.py` | `WeatherService` — cache hit/miss |
| `tests/features/test_feature_score_flow.py` | Flux HTTP complet avec mock provider |
