# Story 3-1 — Algorithme score mer de nuage

## Ce qui a été fait

| Fichier | Rôle |
|---------|------|
| `app/services/weather_providers/base.py` | Structures de données météo (`WeatherData`, `PressureLevelData`) |
| `app/services/weather_providers/open_meteo.py` | Appel API Open-Meteo + calcul de la base des nuages (Skew-T) |
| `app/services/weather.py` | Cache Redis des données météo (TTL 10min) |
| `app/services/score.py` | Algorithme de score mer de nuage |
| `app/api/v1/endpoints/score.py` | Endpoint `GET /api/v1/score` |
| `app/schemas/score.py` | Format de la réponse JSON |
| `app/models/peak.py` | Modèle SQLAlchemy table `peaks` |
| `app/db/seed.py` | Insertion des 10 sommets initiaux |
| `alembic/versions/b90b920dc145_init_peaks.py` | Migration SQL création table `peaks` |
| `tests/test_score.py` | Tests unitaires de l'algorithme |
| `tests/test_weather.py` | Tests du cache Redis |
| `tests/test_open_meteo.py` | Tests du provider Open-Meteo |
| `tests/test_api_score.py` | Tests de l'endpoint HTTP |

---

## Les données sont-elles mockées ou réelles ?

**Dans les tests → tout est mocké.**
Les tests n'appellent jamais Open-Meteo, ne touchent pas Redis, ne lisent pas la DB. Tout est simulé avec des valeurs fixes pour tester la logique isolément.

**En production (Docker lancé) → tout est réel.**
Quand tu appelles `GET /api/v1/score` via le fichier HTTP :
- La DB PostgreSQL est interrogée pour récupérer le sommet (coordonnées, altitude)
- Open-Meteo est appelé en vrai avec les coordonnées GPS du sommet
- Le score est calculé sur des données météo réelles
- Le résultat est mis en cache Redis 10 minutes

---

## Comment ça marche — flux complet

```
Tu appelles GET /api/v1/score?peak_id=...&date=2026-03-22&hour=6
         │
         ▼
1. JWT Supabase validé (ton token de connexion)
         │
         ▼
2. Sommet récupéré en DB (nom, coordonnées GPS, altitude)
   ex: Crêt de la Neige — lat: 46.38, lng: 5.63, altitude: 1720m
         │
         ▼
3. Cache Redis consulté
   clé: weather:46.38:5.63:2026-03-22:6
   → si données déjà en cache (< 10min) : utilisées directement
   → sinon : appel Open-Meteo
         │
         ▼
4. Open-Meteo appelé (si cache miss)
   API gratuite, sans clé, données météo heure par heure
   On récupère pour l'heure 6h du matin :
   - Humidité relative au sol (%)
   - Vitesse du vent (km/h)
   - Pression atmosphérique (hPa)
   - Températures à 4 niveaux d'altitude (925, 850, 800, 700 hPa)
   - Couverture nuageuse basse (%)
         │
         ▼
5. Calcul de la base des nuages (méthode Skew-T)
   On scanne les niveaux d'altitude de bas en haut.
   Dès qu'un niveau est saturé (humidité ≥ 88% ET écart T-Td < 2°C)
   → c'est l'altitude de la base des nuages.
   Si aucun niveau saturé → ciel clair → cloud_base = 5000m
         │
         ▼
6. Calcul du score (voir section suivante)
         │
         ▼
7. Réponse JSON retournée
```

---

## L'algorithme de score — explication métier

### Pourquoi cette refonte

La version initiale de l'algorithme avait deux problèmes identifiés :

1. **Poids arbitraires non calibrés** — les poids (0.35/0.20/0.15/0.20/0.10) n'ont jamais été validés sur des données terrain. Ils donnaient une fausse impression de précision. Ils sont conservés mais présentés honnêtement comme des indicateurs de qualité, pas un score de précision calibré.

2. **Coefficient saisonnier supprimé** — le ×0.75 en été était une mauvaise heuristique. C'est la présence ou absence de nuages bas qui détermine si une mer de nuage est possible, pas le mois de l'année. Si en juillet le ciel est dégagé (`cloud_cover_low < 20%`), la condition bloquante l'attrape correctement. Si en juillet il y a des nuages bas sous le sommet, pourquoi pénaliser ?

### Conditions bloquantes (éliminatoires)

Deux conditions sont vérifiées avant tout calcul. Si l'une est vraie → `score = 0`, `verdict = "none"`, aucun calcul de composantes.

**Condition 1 : cloud_base >= peak_altitude**

Si la base des nuages est au-dessus ou au niveau du sommet, l'observateur est sous les nuages et ne peut pas voir de mer de nuage. Physiquement impossible.

```
cloud_base = 2000m, sommet = 1700m → "none" (nuages au-dessus)
cloud_base = 1700m, sommet = 1700m → "none" (nuages exactement au niveau)
cloud_base = 1699m, sommet = 1700m → calcul normal (nuages 1m sous le sommet)
```

**Condition 2 : cloud_cover_low < 20%**

Si la couverture nuageuse basse est inférieure à 20%, le ciel est trop dégagé pour former une mer de nuage. Pas assez de nuages bas présents.

```
cloud_cover_low = 5%  → "none" (ciel dégagé)
cloud_cover_low = 19% → "none" (insuffisant)
cloud_cover_low = 20% → calcul normal (seuil atteint)
```

### Score conditionnel (si conditions non bloquantes)

Si aucune condition bloquante n'est levée, on calcule 5 indicateurs météo, chacun noté de 0.0 à 1.0. On les combine avec des poids pour obtenir un score de 0 à 100%.

```
score = 0.35 × cloud_base
      + 0.20 × humidité
      + 0.15 × vent
      + 0.20 × inversion thermique
      + 0.10 × pression
```

Pas de coefficient saisonnier, pas de bonus/malus cloud_cover_low — la condition bloquante cloud_cover_low remplace la logique bonus/malus.

### Les 5 composantes

**1. Cloud base (poids 35%) — la plus importante**

C'est l'altitude à laquelle les nuages commencent.
Pour voir une mer de nuage depuis un sommet à 1720m :
- cloud_base ≤ 1520m (200m sous le sommet) → score 1.0 — idéal
- cloud_base entre 1520m et 2220m → score linéaire décroissant
- cloud_base ≥ 2220m (500m au-dessus) → score 0.0 (mais la condition bloquante 1 aura déjà stoppé le calcul)

**2. Humidité (poids 20%)**

Humidité relative au sol (à 2m).
- ≥ 95% → score 1.0 (air quasi saturé, nuages denses)
- ≤ 60% → score 0.0 (air trop sec pour former des nuages)
- Entre les deux → interpolation linéaire

**3. Vent (poids 15%)**

Vent fort = les nuages se dissipent ou ne se forment pas.
- ≤ 5 km/h → score 1.0 (calme parfait)
- ≥ 30 km/h → score 0.0 (trop de vent)
- Entre les deux → interpolation linéaire

**4. Inversion thermique (poids 20%)**

C'est le phénomène météo clé de la mer de nuage.
Normalement, la température baisse avec l'altitude.
Lors d'une inversion, il fait plus chaud en altitude qu'en bas = l'air froid
et humide reste piégé dans les vallées sous une "couverture" d'air chaud.
C'est exactement ce qui crée les mers de nuage.

On mesure : T(850 hPa, ≈1500m) - T(925 hPa, ≈800m)
- Différence ≥ +5°C → inversion marquée → score 1.0
- Différence ≤ -3°C → gradient normal → score 0.0

**5. Pression (poids 10%)**

Haute pression = anticyclone = temps stable = conditions favorables.
- ≥ 1025 hPa → score 1.0
- ≤ 1010 hPa → score 0.0

### Verdicts

| Score | Verdict | Signification |
|-------|---------|---------------|
| conditions bloquantes | `none` | Mer de nuage impossible — nuages trop hauts ou ciel dégagé |
| ≥ 70% | `high` | Mer de nuage très probable |
| 40-69% | `medium` | Mer de nuage possible |
| < 40% | `low` | Peu probable |

Le verdict `"none"` est distinct de `"low"` : `"low"` signifie que les conditions de base sont réunies mais de qualité insuffisante, tandis que `"none"` signifie que la mer de nuage est physiquement exclue.

---

## Comment tester manuellement

```bash
# 1. Démarrer l'infra
make dev

# 2. Ouvrir http/supabase-auth.http dans VS Code
#    → Send Request sur "Se connecter"
#    → Copier access_token dans la réponse
#    → Coller dans .vscode/settings.json > "jwt": "..."

# 3. Ouvrir http/score.http
#    → Send Request sur n'importe quelle requête
```

**Dates valides : aujourd'hui + 16 jours max** (limite Open-Meteo).

Exemples de réponses attendues :
- Sommet 1500m, cloud_base 5000m (ciel clair) → `verdict: "none"` (condition bloquante 1)
- Sommet 1500m, cloud_base 800m, cloud_cover_low 5% → `verdict: "none"` (condition bloquante 2)
- Sommet 1500m, cloud_base 800m, cloud_cover_low 80%, bonnes conditions → `verdict: "high"`

---

## Limites connues de l'algorithme

- **Les poids sont indicatifs** — non calibrés sur des données terrain réelles.
  Un score de 72% ("high") est une estimation, pas une prédiction précise.
  À valider sur le terrain avec les retours utilisateurs.

- **Open-Meteo = 16 jours max** — pas de prévision long terme.

- **Résolution spatiale** — Open-Meteo a une résolution de ~1-5km.
  Pour de petits sommets isolés, les données peuvent être imprécises.

- **Pas de données historiques** — on ne peut pas savoir si le même jour
  l'année dernière avait une mer de nuage.
