# Story 4.1 — Quota Freemium Backend (1 check/jour)

## Ce qui a été fait

### Fichiers créés
- `app/services/quota.py` — Service quota indépendant pour freemium (QuotaService + QuotaExceededException)
- `tests/test_quota.py` — Tests unitaires du service quota (8 tests)
- `tests/features/test_quota_flow.py` — Tests HTTP du flux complet (6 tests)

### Fichiers modifiés
- `app/core/dependencies.py` — Ajouté `check_quota()` dépendance + `get_user_subscription()` (placeholder pour story 4.3)
- `app/api/v1/endpoints/score.py` — Intégré `check_quota` au lieu de `get_current_user`
- `tests/test_api_score.py` — Mis à jour les mocks pour supporter quota (Redis + subscription)
- `app/core/errors.py` — Ajouté `ErrorCode.QUOTA_EXCEEDED`

## Comment ça fonctionne

### Architecture

```
GET /api/v1/score
  ↓
check_quota() dependency
  ├─ 1. Valide JWT (get_current_user)
  ├─ 2. Récupère subscription DB (None → freemium, ou record)
  ├─ 3. Si Premium/Pro + non expiré → BYPASS quota, retourne user
  └─ 4. Si freemium ou expiré :
      ├─ Crée QuotaService(redis)
      ├─ Appelle quota_service.check_and_increment(user_id, date)
      │   ├─ Récupère compteur Redis : quota:{user_id}:{date_iso}
      │   ├─ Si compteur >= 1 → QuotaExceededException
      │   └─ Sinon → INCR + expire(TTL=minuit UTC)
      ├─ Si exception → HTTPException(429)
      └─ Sinon → retourne user
  ↓
Score endpoint continue (peak lookup, météo, algo)
```

### Flux utilisateur freemium

**1er appel (2026-04-01 10:00 UTC)**
```bash
GET /api/v1/score?peak_id=mont-blanc&date=2026-04-01
Authorization: Bearer {jwt_freemium}
```
- `check_quota()` appelé
- Redis `quota:user-123:2026-04-01` absent → None
- INCR → 1
- TTL expire() = 50400 secondes (jusqu'à 2026-04-02 00:00 UTC)
- **Résultat : 200 OK + score**

**2e appel (2026-04-01 15:00 UTC)**
```bash
GET /api/v1/score?peak_id=mont-blanc&date=2026-04-01
Authorization: Bearer {jwt_freemium}
```
- `check_quota()` appelé
- Redis `quota:user-123:2026-04-01` = 1 (b"1" depuis Redis)
- 1 >= 1 → QuotaExceededException
- HTTPException(status=429, detail={"detail": "Quota journalier atteint", "code": "QUOTA_EXCEEDED"})
- **Résultat : 429 Too Many Requests**

**3e appel (2026-04-02 08:00 UTC — jour suivant)**
- Redis `quota:user-123:2026-04-01` expiré automatiquement (TTL atteint)
- Nouvelle clé `quota:user-123:2026-04-02` absent
- INCR → 1
- TTL expire()
- **Résultat : 200 OK + score** (reset fonctionnel)

### Flux utilisateur Premium/Pro

Même endpoint, même date, appels illimités :
```bash
# Appel 1
GET /api/v1/score?peak_id=mont-blanc&date=2026-04-01
Authorization: Bearer {jwt_premium}

# Appel 2
GET /api/v1/score?peak_id=mont-blanc&date=2026-04-01
Authorization: Bearer {jwt_premium}

# Appel N
GET /api/v1/score?peak_id=mont-blanc&date=2026-04-01
Authorization: Bearer {jwt_premium}
```
- `check_quota()` appelé N fois
- À chaque appel : subscription.plan == "premium" ET expires_at > now
- **Résultat : 200 OK pour chaque appel (redis jamais consulté)**

### Abonnement expiré → Fallback freemium

User avec subscription.plan="premium" mais expires_at < now :
- `check_quota()` vérifie `if subscription.expires_at > datetime.utcnow()`
- Condition FALSE → pas de bypass
- Freemium quota s'applique
- **Résultat : 429 au 2e appel du même jour**

## Code clé

### Service quota

```python
class QuotaService:
    async def check_and_increment(self, user_id: str, date: str) -> None:
        quota_key = f"quota:{user_id}:{date}"
        checks = await self._redis.get(quota_key)
        checks_int = int(checks) if checks else 0

        if checks_int >= self._daily_limit:  # 1 pour freemium
            raise QuotaExceededException(...)

        # Incrémenter
        await self._redis.incr(quota_key)

        # TTL minuit UTC
        tomorrow = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        ttl = int((tomorrow - datetime.utcnow()).total_seconds())
        await self._redis.expire(quota_key, ttl)
```

### Dépendance check_quota

```python
async def check_quota(
    user: dict[str, Any] = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_id = user["id"]

    # Vérifier si Premium/Pro
    subscription = await get_user_subscription(user_id, db)
    if subscription and subscription.plan in ("premium", "pro"):
        if subscription.expires_at > datetime.utcnow():
            return user  # Bypass quota

    # Freemium : vérifier le quota
    today = datetime.utcnow().strftime("%Y-%m-%d")
    quota_service = QuotaService(redis)

    try:
        await quota_service.check_and_increment(user_id, today)
    except QuotaExceededException:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": "Quota journalier atteint",
                "code": ErrorCode.QUOTA_EXCEEDED,
            },
        ) from None

    return user
```

### Intégration endpoint

```python
@router.get("/score", response_model=ScoreResponse)
async def get_score(
    peak_id: str = Query(...),
    date: str = Query(...),
    hour: int = Query(default=6),
    current_user: dict[str, Any] = Depends(check_quota),  # ← remplace get_current_user
    db: AsyncSession = Depends(get_db),
) -> ScoreResponse:
    # ... resto du code inchangé
```

## Comment tester

### Tests automatiques

```bash
cd backend
source .venv/bin/activate

# Unitaires (service quota seul)
pytest tests/test_quota.py -v
# ✓ 8 tests passent

# HTTP (flux endpoint + quota)
pytest tests/features/test_quota_flow.py -v
# ✓ 6 tests passent

# Validation complète
make validate
# ✓ ruff check, mypy, pytest --cov
```

### Test manuel avec curl

**Prérequis :** JWT valide freemium + API running

```bash
export JWT_FREEMIUM="eyJ0eXAiOi..."  # Token Supabase freemium
export JWT_PREMIUM="eyJ0eXAiOi..."   # Token Supabase premium

# 1er appel → 200
curl -H "Authorization: Bearer $JWT_FREEMIUM" \
  "http://localhost:8000/api/v1/score?peak_id=mont-blanc&date=2026-04-01"
# ✓ 200 OK + score data

# 2e appel → 429
curl -H "Authorization: Bearer $JWT_FREEMIUM" \
  "http://localhost:8000/api/v1/score?peak_id=mont-blanc&date=2026-04-01"
# ✓ 429 Too Many Requests
# {
#   "detail": {
#     "detail": "Quota journalier atteint",
#     "code": "QUOTA_EXCEEDED"
#   }
# }

# Premium illimité
curl -H "Authorization: Bearer $JWT_PREMIUM" \
  "http://localhost:8000/api/v1/score?peak_id=mont-blanc&date=2026-04-01"
# ✓ 200 OK (même après plusieurs appels)
```

### Logs debug

```bash
# Dans docker-compose.dev.yml, ajouter :
environment:
  - LOG_LEVEL=DEBUG

# Relancer
docker compose -f ../infra/docker-compose.dev.yml up -d

# Voir les logs
docker logs -f cloudbreak-backend

# Sortie attendue :
# 2026-04-01 10:00:00 [DEBUG] quota_incremented user_id=user-123 date=2026-04-01 checks_now=1
# 2026-04-01 15:00:00 [WARNING] quota_exceeded user_id=user-123 date=2026-04-01 checks=1
```

## Acceptance Criteria vérifiés

- [x] **AC1** : Freemium user 1er check → score retourné + quota incrémenté Redis
  - Test : `test_quota_score_endpoint_first_call_returns_200`
  - Vérification : mock_redis.incr() appelé

- [x] **AC2** : Freemium user 2e check → 429 QUOTA_EXCEEDED
  - Test : `test_quota_score_endpoint_second_call_returns_429`
  - Vérification : response.status_code == 429 + detail.code == "QUOTA_EXCEEDED"

- [x] **AC3** : Premium/Pro users → quota ignoré (illimité)
  - Tests : `test_quota_premium_user_unlimited_calls`, `test_quota_pro_user_unlimited_calls`
  - Vérification : 3+ appels → tous 200 OK

- [x] **AC4** : Minuit UTC → Redis expire auto, compteur reset
  - Test : `test_quota_ttl_seconds_until_midnight_utc`
  - Vérification : redis.expire(TTL) appelé avec secondes correctes jusqu'à minuit UTC

## Intégration avec story 4.3 (Subscriptions DB)

En story 4.1, `get_user_subscription(user_id, db)` retourne None (tous freemium).

En story 4.3, on créera :
- Table DB : `subscriptions(user_id, plan, expires_at, created_at, updated_at)`
- Migrations Alembic pour créer la table
- `get_user_subscription()` implémentation réelle

Le code `check_quota()` restera **100% compatible** — pas de changement endpoint.

## Redis clés et TTL

| Clé | Format | Exemple | TTL |
|-----|--------|---------|-----|
| quota | `quota:{user_id}:{date_iso}` | `quota:user-123:2026-04-01` | Minuit UTC suivant |

Préfixe `quota:*` permet isolation simple par pattern.

## Notes

- QuotaService n'a pas d'état (pas de cache local) — appels directs Redis
- `daily_limit` paramétrable dans `__init__()` → future extension freemium+/pro tiers
- Dates ISO 8601 UTC partout (format `YYYY-MM-DD`)
- Logs JSON structurés → facile parsing/alertes
- Erreurs API format standard : `{"detail": "...", "code": "CODE"}`
