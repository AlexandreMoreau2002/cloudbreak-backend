# Security — cloudbreak-backend

Document de référence sécurité. À mettre à jour à chaque story qui touche auth, réseau, données ou dépendances.

---

## État actuel (story 1-2 — squelette)

### Ports exposés

| Port | Service | Exposé où | Risque |
|------|---------|-----------|--------|
| 8001 | FastAPI (dev) | localhost uniquement | ✅ Aucun |
| 5432 | PostgreSQL | localhost uniquement | ✅ Aucun |
| 6379 | Redis | localhost uniquement | ✅ Aucun |

> En prod : seul Caddy expose les ports 80/443. L'API, PostgreSQL et Redis ne sont **jamais** exposés directement à internet — ils communiquent via le réseau Docker interne.

---

## Secrets & variables d'environnement

- Les secrets sont dans `.env` — **jamais commité** (dans `.gitignore`)
- `.env.example` fourni sans valeurs sensibles — commité comme template
- En prod : variables injectées via Docker Compose, stockées sur le VPS uniquement
- **À ne jamais faire** : hardcoder une clé dans le code, même en dev

### Secrets à rotation régulière

| Secret | Fréquence rotation recommandée |
|--------|-------------------------------|
| `WEATHER_API_KEY` | Si leak détecté |
| `SUPABASE_KEY` | Si leak détecté |
| `POSTHOG_API_KEY` | Si leak détecté |
| Clé SSH VPS | Tous les 12 mois |

---

## Authentification

**État actuel** : implémentée (story 2-1).

- JWT Supabase validé **localement** via clé publique ECC P-256 (JWKS)
- Zéro appel réseau Supabase par requête
- Dependency FastAPI `get_current_user` injectée sur chaque route protégée
- `/health` est la seule route publique sans auth

### Configuration Supabase — dev vs prod

| Paramètre | Dev | Prod |
|-----------|-----|------|
| Confirm email | **désactivé** | **activé** |

> La confirmation email est désactivée en dev pour fluidifier les tests. À réactiver dans le dashboard Supabase avant la release 1.0.0 : Authentication → Providers → Email → "Confirm email" → ON.

---

## Transport & chiffrement

| Contexte | Statut |
|----------|--------|
| Dev local | HTTP (localhost) — acceptable |
| Prod | HTTPS TLS automatique via Caddy + Let's Encrypt |
| DB → API | Réseau Docker interne (non chiffré mais isolé) |
| Redis → API | Réseau Docker interne (non chiffré mais isolé) |

---

## Données utilisateur & RGPD

- Hébergement Supabase région **EU (Frankfurt)** — pas de transfert hors UE
- Endpoint `DELETE /api/v1/user` prévu dès le MVP (droit à l'effacement)
- Géolocalisation : consentement explicite requis, refus sans blocage de l'app
- Paiements : StoreKit 2 uniquement — **aucun numéro de carte stocké côté backend**

---

## Dépendances

### Audit des dépendances

```bash
# Vérifier les vulnérabilités connues
pip-audit  # à installer : pip install pip-audit
```

À lancer avant chaque release. Les dépendances actuelles (story 1-2) :

| Package | Version | Notes |
|---------|---------|-------|
| fastapi | 0.115.0 | Stable |
| sqlalchemy | 2.0.36 | Stable |
| pydantic | 2.10.0 | Stable |
| python-jose | 3.3.0 | Pour JWT — surveiller les CVE |
| asyncpg | 0.30.0 | Stable |

---

## Surface d'attaque actuelle

### Ce qui existe
- `GET /health` — endpoint public, pas de donnée sensible, pas de risque
- `GET /api/v1/peaks/search` — auth JWT requise, q min_length=2 validé par Pydantic/FastAPI
- `GET /api/v1/peaks/{slug}` — auth JWT requise, slug passé en path param (ORM only)
- `POST /api/v1/user/favorites` — auth JWT requise, user_id extrait du JWT uniquement
- `DELETE /api/v1/user/favorites/{peak_id}` — auth JWT requise, isolation par user_id JWT
- `GET /api/v1/user/favorites` — auth JWT requise, isolation par user_id JWT

- `GET /api/v1/score` — auth JWT requise + quota Redis (check_quota dependency), `peak_id`/`date`/`hour` validés par Pydantic/Query

### Ce qui n'existe pas encore
- Pas de rate limiting (à implémenter avant prod)
- Pas de limite sur le nombre de favoris par utilisateur (à prévoir avant prod)

---

## 2026-03-22 Story 3-3 — Recherche de Sommet & Favoris

### INFO
- **[peaks.py]** Isolation correcte des favoris : `user_id` extrait de `current_user["id"]` (JWT) sur les trois endpoints favoris — jamais passé en paramètre client
- **[peaks.py]** Toutes les requêtes passent par SQLAlchemy ORM (`select(Peak).where(...)`, `select(Favorite).where(...)`) — aucun SQL brut, risque d'injection SQL nul
- **[peaks.py]** Paramètre `q` de recherche contraint à `min_length=2` via `Annotated[str, Query(min_length=...)]` — rejeté 422 si trop court
- **[peaks.py]** Paramètre `q` interpolé via `Peak.name.ilike(f"%{q}%")` — le `%` est un wildcard SQL valide mais la valeur est passée comme paramètre SQLAlchemy lié (bind parameter), pas concaténée dans le SQL brut — pas d'injection possible
- **[favorite.py]** Contrainte `UniqueConstraint("user_id", "peak_id", name="uq_user_peak")` définie au niveau DB — doublon impossible même en cas de race condition applicative
- **[favorite.py]** `ondelete="CASCADE"` sur `peak_id` FK — suppression d'un sommet nettoie les favoris associés, pas d'orphelins
- **[peaks.py]** Auth JWT vérifiée sur tous les endpoints (y compris `/peaks/search` et `/peaks/{slug}`) via `Depends(get_current_user)`
- **[peaks.py]** Logs `logger.info` sur les mutations (add/remove) et `logger.debug` sur les lectures — aucune donnée sensible loggée (pas de token, pas d'email)
- **[schemas/favorite.py]** `FavoriteCreate` contient uniquement `peak_id: str` — pas de `user_id` accepté depuis le client

### WARNING
- **[favorite.py]** `user_id` est de type `String` (non UUID) dans le modèle `Favorite`, alors que l'ID Supabase est un UUID. Le type est cohérent avec `Peak.id` (String) mais une contrainte de format UUID côté schéma Pydantic (`FavoriteCreate`) serait plus stricte — recommandation : ajouter une validation `UUID` sur `peak_id` dans `FavoriteCreate` pour rejeter 422 les IDs malformés avant la requête DB
- **[peaks.py]** Pas de limite sur le nombre de favoris par utilisateur — un utilisateur pourrait créer un très grand nombre de favoris, entraînant des requêtes `SELECT` lourdes sur `GET /user/favorites` — à limiter (ex: 200 favoris max) avant prod
- **[peaks.py]** `DELETE /api/v1/user/favorites/{peak_id}` accepte un `peak_id` de type `str` en path param sans validation de format — un attaquant authentifié peut envoyer des valeurs arbitraires longues ; SQLAlchemy les gère correctement mais une validation `min_length`/`max_length` ou pattern UUID serait défensive

---

## 2026-03-23 Story 3-4 — Ecran Principal ScoreCard

### WARNING
- **[fetchService.ts:51]** `apiFetch` propage `body?.detail` de l'API comme message d'erreur brut dans le `Error` thrown. Ce message remonte dans `useScore` (ligne 33) et est stocké verbatim dans `scoreState.error`. L'ecran `index.tsx` filtre correctement avant affichage (lignes 59-62), mais le message brut reste accessible dans l'objet d'etat — tout futur consommateur qui rendrait directement `scoreState.error` pourrait exposer des details internes du backend (ex: message Pydantic, code d'erreur interne). Recommandation : sanitiser a la sortie de `useScore` plutot qu'au niveau de chaque ecran consommateur — remplacer le message brut par une cle i18n generique avant de le stocker dans le state `error`.

### INFO
- **[useScore.ts:22]** Token JWT logue uniquement comme booleen (`token: !!token`) en mode DEBUG — la valeur brute n'est jamais loggee. Pattern correct.
- **[fetchService.ts:36]** URL complete loggee en mode DEBUG mais le token est dans le header `Authorization`, jamais dans l'URL ni dans les logs. Pas de fuite possible.
- **[devConfig.ts:13]** `DEBUG = __DEV__ && true` — `__DEV__` est `false` en build de production Expo/Metro, tous les `console.debug` sont morts en prod. Comportement verifie.
- **[SelectedPeakContext.tsx]** Context stocke uniquement en memoire React state (id, name, slug, lat, lng, altitude) — pas d'AsyncStorage, pas de SecureStore, pas de persistence. Aucune donnee sensible dans ce context.
- **[index.tsx:18]** Token extrait de `session?.access_token` issu du SDK Supabase — le SDK gere son propre stockage securise, le token n'est pas manipule directement par l'app. Correct.
- **[index.tsx:59-62]** Messages d'erreur filtres via cle i18n avant affichage (`home.serviceUnavailable` / `home.errorGeneric`) — le message brut de l'API n'est jamais rendu dans l'UI sur cet ecran.
- **[ScoreCard.tsx]** Composant purement presentationnel — affiche uniquement `peak_name`, `peak_altitude`, `score`, `verdict` (donnees non-sensibles). Aucune logique auth, aucun acces token.
- **[api/score.ts:23]** `peak_id` passe comme query param valide par le backend via SQLAlchemy ORM — pas d'injection possible.

---

---

## 2026-05-14 Story 4-1 — Quota freemium backend (Redis QuotaService)

### CRITIQUE

- **[dependencies.py:107]** Comparaison timezone-aware vs timezone-naive possible sur `expires_at` : `datetime.now(subscription.expires_at.tzinfo)` crashe avec `AttributeError` si `expires_at` est `None` (colonne nullable). Un utilisateur freemium sans ligne `subscriptions` ne passe jamais dans ce bloc (car `subscription` est `None`), mais un utilisateur avec une ligne `subscriptions` dont `expires_at` est `None` (plan `free` en DB) déclencherait un 500 non géré. Correction : `if subscription and subscription.plan in ("premium", "pro") and subscription.expires_at is not None and subscription.expires_at > datetime.now(subscription.expires_at.tzinfo)`.
- **[dependencies.py:122]** `peak_id` lu depuis `request.query_params.get("peak_id", "")` sans aucune validation. Un client malveillant peut envoyer un `peak_id` vide (`""`) ou arbitrairement long : la clé Redis devient `quota:{user_id}:{date}` avec un membre vide dans le SET, ce qui déverrouille un slot de quota sans sommet réel — contournement partiel du quota. Un second appel avec le vrai `peak_id` consomme un deuxième slot et déclenche QUOTA_EXCEEDED alors que l'utilisateur n'a pas réellement consulté deux sommets. Correction : valider `peak_id` non vide et de format UUID avant d'appeler `check_and_increment` ; retourner 422 si invalide.

### WARNING

- **[main.py:35]** L'exception handler `OperationalError` logue `str(exc)` dans le champ `error` : `logger.error(..., extra={"error": str(exc)})`. En prod, les messages SQLAlchemy peuvent contenir le `DATABASE_URL` complet (avec mot de passe) si la connexion échoue. Le log est structuré (JSON) et ne remonte pas au client (réponse 503 sans détail technique), mais le secret peut être persisté dans les logs du VPS. Recommandation : logguer `type(exc).__name__` uniquement, ou masquer le `DATABASE_URL` dans les settings avant logging.
- **[quota.py:82-85]** Race condition mineure entre `sadd` et `expire` : si le process est tué entre les deux instructions, la clé Redis n'a pas de TTL et ne sera jamais purgée (fuite mémoire Redis). Recommandation : utiliser un pipeline Redis atomique `pipe.sadd(...); pipe.expire(...); await pipe.execute()`.
- **[dependencies.py:118]** `datetime.utcnow()` déprécié en Python 3.12 (warning `DeprecationWarning`). Remplacer par `datetime.now(timezone.utc).strftime("%Y-%m-%d")` pour cohérence et compatibilité future.
- **[health.py]** L'endpoint `GET /health` est public (pas d'auth). Il expose l'état de Redis et PostgreSQL (`"ok"` / `"unavailable"`). En prod derrière Caddy, cet endpoint est accessible depuis Internet — un attaquant peut déduire si la DB ou Redis est en panne pour choisir le bon moment d'attaque. Recommandation : soit protéger par IP (Caddy allow only internal), soit retourner uniquement `{"status": "ok"|"degraded"}` sans détailler quel service est indisponible.

### INFO

- **[quota.py]** Clés Redis correctement préfixées `quota:{user_id}:{date}` — aucune collision possible avec `weather:*` ou `cache:*`. Schéma conforme aux conventions Cloudbreak.
- **[quota.py]** TTL calculé jusqu'à minuit UTC et appliqué via `expire()` — reset automatique correct sans fuite mémoire (sous réserve de la race condition ci-dessus).
- **[dependencies.py]** `user_id` extrait exclusivement du JWT validé (`payload.get("sub")`) — jamais passé en paramètre client sur l'endpoint score. Isolation correcte.
- **[dependencies.py]** `get_user_subscription` utilise `select(Subscription).where(Subscription.user_id == user_id)` — requête SQLAlchemy paramétrée, aucun SQL brut, pas d'injection possible.
- **[main.py]** Exception handler `OperationalError` retourne `{"detail": "Base de données indisponible", "code": "DATABASE_UNAVAILABLE"}` — aucune stack trace, aucun message interne exposé au client.
- **[security.py:26-44]** `encode_test_jwt` avec `dev-secret-key` hardcodé présent dans le code de production (`app/core/security.py`). La fonction est marquée `DEV/TEST ONLY` et n'est importée que dans les tests — aucun endpoint ne l'expose. Risque résiduel : si un développeur l'importe par erreur dans une route, le token serait signé avec HS256 et une clé connue. Recommandation : déplacer cette fonction dans `tests/conftest.py` ou un module `tests/helpers.py` pour l'isoler du code de production.
- **[quota.py:78]** Message de `QuotaExceededException` contient `user_id` et `date` : `f"Daily quota exceeded for {user_id} on {date}"`. Ce message ne remonte pas au client (catch dans `dependencies.py`), mais il est potentiellement loggué si une exception non catchée remontait. Actuellement sans risque — surveiller si le catch est retiré.
- **[score.py]** Deux instances Redis créées indépendamment : une dans `dependencies.py` (`get_redis` singleton) et une dans `score.py` (`_redis` module-level). Pas de risque de sécurité mais doublon de connexions Redis en prod — à consolider via la dependency `get_redis`.

---

## Checklist avant mise en prod

- [ ] Variables `.env` renseignées sur le VPS (jamais en clair dans le code)
- [ ] PostgreSQL et Redis non exposés (ports non mappés dans `docker-compose.yml` prod)
- [ ] Caddy HTTPS opérationnel (Let's Encrypt)
- [ ] Rate limiting activé sur les endpoints publics
- [x] JWT validation opérationnelle sur toutes les routes protégées
- [ ] Confirm email réactivé dans Supabase (avant release 1.0.0)
- [ ] `DEBUG=False` / `ENVIRONMENT=production`
- [ ] Logs ne contiennent aucun secret ou donnée personnelle
- [ ] `pip-audit` passé sans vulnérabilité critique
- [ ] Accès SSH VPS par clé uniquement (password auth désactivé)
- [ ] Firewall VPS : seuls ports 22, 80, 443 ouverts
