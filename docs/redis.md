# Redis — Documentation technique

Redis 7 remplit **deux rôles distincts et indépendants** dans Cloudbreak :

| Rôle | Préfixe clé | TTL | Valeur |
|------|-------------|-----|--------|
| Cache météo | `weather:*` | 600s (10 min) | JSON sérialisé `WeatherData` |
| Quota freemium | `quota:*` | Minuit UTC | Compteur entier (INCR) |

---

## 🌤️ Cache météo

**Fichier** : `app/services/weather.py`

### Pourquoi Redis (pas PostgreSQL)

- Données éphémères — inutile de persister en DB
- Lecture microseconde vs requête SQL + HTTP Open-Meteo
- TTL natif — pas besoin de job de nettoyage
- `setex` atomique — pas de race condition en écriture concurrente

### Format de clé

```
weather:{lat}:{lng}:{date}:{hour}

Exemple :
weather:45.8326:6.8652:2026-04-04:9
```

### TTL

```python
CACHE_TTL = 600  # 10 minutes — défini dans weather.py
```

### Ce qui est caché

Un objet `WeatherData` complet sérialisé en JSON :

```python
@dataclass
class WeatherData:
    cloud_base: float           # altitude base nuages (m)
    humidity: float             # humidité relative sol (%)
    wind_speed: float           # vitesse vent (km/h)
    temperature_2m: float       # température 2m (°C)
    temperature_850hpa: float   # température niveau 850 hPa (°C)
    temperature_925hpa: float   # température niveau 925 hPa (°C)
    pressure: float             # pression surface (hPa)
    cloud_cover_low: float      # couverture nuageuse basse (%)
    month: int                  # mois (1-12)
    pressure_levels: list[PressureLevelData]
```

### Flux — cache météo

```
GET /api/v1/score?peak_id=&date=&hour=
         │
         ▼
  WeatherService.get_forecast(lat, lng, date, hour)
         │
         ▼
  Redis GET weather:{lat}:{lng}:{date}:{hour}
         │
    ┌────┴────┐
  HIT         MISS
    │           │
    ▼           ▼
 JSON parse  Open-Meteo API call
    │           │
    │           ▼
    │        Redis SETEX (TTL 600s)
    │           │
    └─────┬─────┘
          ▼
     WeatherData → score.py → réponse
```

### Code clé

```python
# weather.py
cache_key = f"weather:{lat}:{lng}:{date}:{hour}"

cached = await self._redis.get(cache_key)
if cached:
    logger.info("weather_cache_hit", extra={"key": cache_key})
    return _weather_data_from_dict(json.loads(cached))

logger.info("weather_cache_miss", extra={"key": cache_key})
weather = await self._provider.get_forecast(lat=lat, lng=lng, date=date, hour=hour)

await self._redis.setex(cache_key, CACHE_TTL, json.dumps(asdict(weather)))
return weather
```

---

## 🔢 Quota freemium

**Fichiers** : `app/services/quota.py` + `app/core/dependencies.py`

### Principe métier

Un utilisateur freemium peut consulter **1 sommet unique par jour**. Il peut recharger le même sommet autant de fois qu'il veut — seule la première consultation d'un sommet inconnu est comptée. À minuit UTC, le compteur repart à zéro.

Les utilisateurs premium/pro bypassen entièrement le quota — Redis n'est même pas consulté.

---

### L'allégorie du vestiaire de musée

Imagine l'entrée d'un musée gratuit. Chaque visiteur freemium a droit à **1 salle par jour**. À l'entrée, il y a un carnet de visites par visiteur.

- Quand tu entres dans une salle : le gardien note le **nom de la salle** dans ton carnet du jour
- Si tu veux entrer dans une salle que tu as déjà vue : le gardien laisse passer (rechargement)
- Si tu veux une **2ème salle différente** : le gardien bloque — quota dépassé
- À minuit, tous les carnets sont déchirés (TTL Redis)
- Les membres premium ? Ils ont un badge magnétique — le gardien ne regarde même pas leur carnet

```
                    Utilisateur freemium
                           │
                           ▼
              ┌────────────────────────┐
              │   Est-il premium/pro ? │
              └────────┬───────────────┘
                       │
              oui ─────┘──────── non
               │                  │
               ▼                  ▼
           Passe libre      ┌─────────────────────────────────┐
                            │  Redis SET  "quota:user123:      │
                            │             2026-05-14"          │
                            │                                  │
                            │   { "mont-blanc", "vercors" }   │
                            └─────────┬────────────────────────┘
                                      │
                            ┌─────────▼────────────────────────┐
                            │  SCARD (compte les éléments)     │
                            │  ≥ 1 sommet déjà visité ?        │
                            └─────────┬────────────────────────┘
                                      │
                             oui ─────┘───── non
                              │               │
                              ▼               ▼
                           429 QUOTA     SADD + réponse OK
                           EXCEEDED
```

---

### Pourquoi un SET et pas un simple compteur INCR

On aurait pu écrire `INCR quota:user:date` et compter les appels. Mais ça bloquerait l'utilisateur qui **recharge la même page** plusieurs fois.

Avec un SET, `SADD "mont-blanc"` sur un SET qui contient déjà `"mont-blanc"` **ne fait rien** — un SET refuse les doublons par définition. On compte les **sommets uniques consultés**, pas les requêtes.

```
Compteur naïf (INCR)              SET (implémentation réelle)
─────────────────────             ──────────────────────────────
mont-blanc → 1                    { "mont-blanc" }   → taille 1
mont-blanc → 2  ← bloqué !       { "mont-blanc" }   → taille 1  ✓ rechargement OK
vercors    → 3  ← bloqué !       { "mont-blanc",    → taille 2  ✗ 2ème sommet bloqué
                                    "vercors" }
```

---

### Format de clé

```
quota:{user_id}:{date_iso}

Exemple :
quota:ddce4acf-4588-4916-bb8e-8e47de082e7b:2026-05-14
```

La date dans la clé est la date du jour UTC (`datetime.now(UTC).strftime("%Y-%m-%d")`). Changer de jour = nouvelle clé = nouveau cycle automatiquement.

### TTL

Fixé à **86 400 secondes (24h)** via le pipeline Redis. La clé expire au plus tard 24h après sa création. En pratique, une clé créée à 8h00 UTC expire le lendemain à 8h00 UTC — pas exactement à minuit, mais suffisamment proche pour les besoins du produit.

```
Clé créée à 08:00 UTC → expire à 08:00 UTC J+1
Clé créée à 23:55 UTC → expire à 23:55 UTC J+1
→ nouveau sommet = nouvelle clé, reset garanti sur 24h glissantes
```

---

### Atomicité — le pipeline Redis

Les deux opérations (`SADD` + `EXPIRE`) sont envoyées dans un **pipeline** : un seul aller-retour réseau, exécuté d'un bloc côté Redis.

Sans pipeline, deux requêtes simultanées du même user pourraient toutes les deux lire la taille 0, toutes les deux faire SADD, et toutes les deux passer. Avec le pipeline, l'une est nécessairement traitée après l'autre.

```
Sans pipeline                          Avec pipeline
──────────────────────────────         ───────────────────────────────
Req A : SADD → retourne 1 (nouveau)    Req A : [SADD + EXPIRE] ──→ bloc atomique
Req B : SADD → retourne 1 (nouveau)    Req B : [SADD + EXPIRE] ──→ bloc atomique
→ les deux voient taille 1 → passent  → Req B voit taille 2 → bloquée
```

```python
# quota.py — pipeline atomique
async with redis.pipeline() as pipe:
    pipe.sadd(key, peak_id)
    pipe.expire(key, 86400)
    results = await pipe.execute()
# results[0] = 1 si nouveau peak, 0 si déjà présent
```

---

### Flux complet — quota freemium

```
GET /api/v1/score?peak_id=mont-blanc&date=2026-05-14&hour=8
Authorization: Bearer <jwt_freemium>
         │
         ▼
  check_quota() — dependencies.py
         │
         ├── 1. decode JWT → user_id
         ├── 2. SELECT subscription (PostgreSQL) → None (freemium)
         ├── 3. today = "2026-05-14"
         │
         ▼
  QuotaService.check_and_increment(user_id, today, peak_id)
         │
         ├── SADD quota:uid:2026-05-14 "mont-blanc"  → 1 (nouveau)
         ├── EXPIRE 86400
         │
         ├── SCARD quota:uid:2026-05-14  → 1
         │
    ┌────┴────┐
  ≤ 1         > 1
    │           │
    ▼           ▼
  OK ✓       QuotaExceededException
               → HTTP 429
               {"detail": "Quota journalier atteint",
                "code": "QUOTA_EXCEEDED"}
```

**Rechargement du même sommet (même jour) :**
```
SADD quota:uid:2026-05-14 "mont-blanc"  → 0 (déjà présent, SET refuse le doublon)
SCARD → 1  → OK ✓ (pas re-facturé)
```

**2ème sommet différent (même jour) :**
```
SADD quota:uid:2026-05-14 "vercors"  → 1 (nouveau)
SCARD → 2  → QuotaExceededException → 429
```

**Lendemain, même sommet :**
```
today = "2026-05-15" → nouvelle clé quota:uid:2026-05-15
SADD → 1  → OK ✓ (cycle réinitialisé)
```

---

### Code clé

```python
# dependencies.py — check_quota (simplifié)
subscription = await get_user_subscription(user_id, db)
if (
    subscription
    and subscription.plan in ("premium", "pro")
    and subscription.expires_at is not None
    and subscription.expires_at > datetime.now(subscription.expires_at.tzinfo)
):
    return user  # bypass quota — premium/pro

today = datetime.now(UTC).strftime("%Y-%m-%d")
quota_service = QuotaService(redis)

try:
    await quota_service.check_and_increment(user_id, today, peak_id)
except QuotaExceededException:
    raise HTTPException(status_code=429, detail={
        "detail": "Quota journalier atteint",
        "code": ErrorCode.QUOTA_EXCEEDED,
    })
```

```python
# quota.py — check_and_increment
key = f"quota:{user_id}:{date}"

async with self._redis.pipeline() as pipe:
    pipe.sadd(key, peak_id)
    pipe.expire(key, 86400)
    results = await pipe.execute()

count = await self._redis.scard(key)
if count > self._daily_limit:
    raise QuotaExceededException(user_id=user_id, date=date)
```

---

## ⚙️ Configuration

### Variable d'environnement

```
REDIS_URL=redis://redis:6379
```

Définie dans `app/core/config.py` (pydantic-settings) :

```python
redis_url: str = "redis://localhost:6379"  # fallback local
```

### Client Redis (singleton)

```python
# dependencies.py
_redis: Redis | None = None

async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis
```

`decode_responses=False` — les valeurs restent en bytes, compatibles avec `json.loads`.

### Docker dev vs prod

| Paramètre | Dev (`docker-compose.dev.yml`) | Prod (`docker-compose.yml`) |
|-----------|-------------------------------|----------------------------|
| Image | `redis:7-alpine` | `redis:7-alpine` |
| Container | `cloudbreak-redis` | `cloudbreak-redis` |
| Port exposé | `6379:6379` (accès local) | non exposé (réseau interne) |
| Persistance | non (volume éphémère) | non (données jetables) |
| REDIS_URL | `redis://redis:6379` | `redis://redis:6379` |

En dev, le port 6379 est exposé sur l'hôte → accès direct via `redis-cli` sans exec Docker.

---

## 🔍 Debug — commandes utiles

### Inspecter les clés

```bash
# Toutes les clés (dev uniquement — KEYS est bloquant)
docker exec cloudbreak-redis redis-cli KEYS "*"

# Clés météo uniquement
docker exec cloudbreak-redis redis-cli KEYS "weather:*"

# Clés quota uniquement
docker exec cloudbreak-redis redis-cli KEYS "quota:*"
```

### Lire une valeur

```bash
# Cache météo (JSON brut)
docker exec cloudbreak-redis redis-cli GET "weather:45.8326:6.8652:2026-04-04:9"

# Quota (compteur entier)
docker exec cloudbreak-redis redis-cli GET "quota:ddce4acf-4588-4916-bb8e-8e47de082e7b:2026-04-04"
```

### Vérifier le TTL

```bash
# TTL en secondes (-1 = pas d'expiration, -2 = clé inexistante)
docker exec cloudbreak-redis redis-cli TTL "quota:ddce4acf-4588-4916-bb8e-8e47de082e7b:2026-04-04"
docker exec cloudbreak-redis redis-cli TTL "weather:45.8326:6.8652:2026-04-04:9"
```

### Manipuler les données de test

```bash
# Réinitialiser le quota d'un user (pour retester AC1)
docker exec cloudbreak-redis redis-cli DEL "quota:ddce4acf-4588-4916-bb8e-8e47de082e7b:2026-04-04"

# Forcer un cache miss météo
docker exec cloudbreak-redis redis-cli DEL "weather:45.8326:6.8652:2026-04-04:9"

# Vider tout Redis (dev seulement ⚠️)
docker exec cloudbreak-redis redis-cli FLUSHDB
```

### Surveiller les commandes en temps réel

```bash
# Mode monitor — affiche toutes les commandes reçues par Redis
docker exec cloudbreak-redis redis-cli MONITOR
```

### Statistiques

```bash
# Info générale (mémoire, connexions, stats)
docker exec cloudbreak-redis redis-cli INFO

# Mémoire uniquement
docker exec cloudbreak-redis redis-cli INFO memory

# Nombre de clés en DB 0
docker exec cloudbreak-redis redis-cli DBSIZE
```

### Logs Redis

Redis 7-alpine ne loggue quasiment rien par défaut (mode silencieux). Pour activer les logs verbeux :

```bash
# Activer en live
docker exec cloudbreak-redis redis-cli CONFIG SET loglevel verbose

# Voir les logs du container
docker logs cloudbreak-redis -f
```

---

## 📋 Résumé des clés

| Clé | Exemple | TTL | Opérations |
|-----|---------|-----|------------|
| `weather:{lat}:{lng}:{date}:{hour}` | `weather:45.83:6.86:2026-04-04:9` | 600s | GET, SETEX |
| `quota:{user_id}:{date}` | `quota:ddce4acf...:2026-05-14` | 86400s (24h glissantes) | SADD, SCARD, EXPIRE (pipeline) |
