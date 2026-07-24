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
- `GET /api/v1/peaks/search` — **public depuis story 7.1** (onboarding pré-login), q min_length=2 validé par Pydantic/FastAPI
- `GET /api/v1/peaks/{slug}` — **public depuis story 7.1** (onboarding pré-login), slug passé en path param (ORM only)
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

## 2026-05-15 Story 4-1 — Quota freemium backend (Redis QuotaService)

### WARNING

- **[dependencies.py:122]** `peak_id` lu depuis `request.query_params.get("peak_id", "")` sans validation de longueur ni de format. La chaîne vide est rejetée par le `if not peak_id` immédiatement après, mais une valeur arbitrairement longue (ex: 10 000 caractères) ou contenant des caractères spéciaux (`\n`, `:`, espaces) passe et est insérée comme membre dans le SET Redis, polluant la clé `quota:{user_id}:{date}`. Le `peak_id` vient ensuite de la DB via le routeur FastAPI sur l'endpoint score (validé ORM), mais `check_quota` est une dependency générique qui n'a pas ce contexte. Recommandation : ajouter `max_length=255` et optionnellement un pattern `^[a-zA-Z0-9_-]+$` sur `peak_id` dans la dependency avant l'appel `check_and_increment`.
- **[health.py]** L'endpoint `GET /health` est public (pas d'auth). Il expose l'état de Redis et PostgreSQL (`"ok"` / `"unavailable"`). En prod derrière Caddy, cet endpoint est accessible depuis Internet — un attaquant peut déduire si la DB ou Redis est en panne pour optimiser une tentative d'attaque. Recommandation : soit restreindre par IP dans Caddy (allow interne uniquement), soit ne retourner que `{"status": "ok"|"degraded"}` sans détailler quel service est indisponible.
- **[seed_test_users.py]** Trois UUIDs Supabase réels sont hardcodés dans `app/db/seed_test_users.py` (lignes 31, 37, 43) avec leurs emails associés (`freemium@cloudbreak.app`, `pro@cloudbreak.app`, `test@cloudbreak.app`). Ces UUIDs correspondent à des comptes Supabase existants sur l'environnement de dev. Ils sont commités dans le repo. Si le repo devient public ou si un tiers accède au code, ces comptes sont identifiés. Recommandation : déplacer ces valeurs dans une variable d'environnement `TEST_USER_IDS` ou un fichier `.env.test` non commité ; utiliser des UUIDs fictifs dans le code.

### INFO

- **[dependencies.py:106-109]** Vérification expiry subscription correcte : la condition `subscription.expires_at is not None` précède `subscription.expires_at > datetime.now(...)` dans une chaîne `and` — Python court-circuite, pas de risque d'`AttributeError` sur `None.tzinfo`. Logique correcte.
- **[quota.py:82-87]** `sadd` et `expire` exécutés via `async with self._redis.pipeline() as pipe` suivi de `await pipe.execute()` — atomicité garantie par le pipeline Redis. Pas de race condition TTL.
- **[main.py:35]** L'exception handler `OperationalError` logue `type(exc).__name__` (non `str(exc)`) — le `DATABASE_URL` ne peut pas fuiter dans les logs via cette voie. Correct.
- **[dependencies.py:121]** Date calculée via `datetime.now(UTC).strftime(...)` — `UTC` importé de `datetime` Python 3.11+, pas de `datetime.utcnow()` déprécié. Correct.
- **[quota.py]** Clés Redis correctement préfixées `quota:{user_id}:{date}` — aucune collision possible avec `weather:*` ou `cache:*`. Schéma conforme aux conventions Cloudbreak.
- **[quota.py]** TTL calculé jusqu'à minuit UTC via pipeline Redis — reset automatique correct, pas de fuite mémoire.
- **[dependencies.py]** `user_id` extrait exclusivement du JWT validé (`payload.get("sub")`) — jamais passé en paramètre client sur l'endpoint score. Isolation correcte.
- **[dependencies.py]** `get_user_subscription` utilise `select(Subscription).where(Subscription.user_id == user_id)` — requête SQLAlchemy paramétrée, aucun SQL brut, pas d'injection possible.
- **[main.py]** Exception handler `OperationalError` retourne `{"detail": "Base de données indisponible", "code": "DATABASE_UNAVAILABLE"}` — aucune stack trace, aucun message interne exposé au client.
- **[tests/helpers.py]** `encode_test_jwt` avec `dev-secret-key` hardcodé est isolé dans `tests/helpers.py` — absent de `app/core/security.py`. Aucun endpoint de production ne peut l'importer. Pattern correct.
- **[quota.py:78]** Message de `QuotaExceededException` contient `user_id` et `date`. Ce message est catchéd dans `dependencies.py` et ne remonte pas au client. Sans risque dans l'état actuel — surveiller si le catch est retiré.
- **[score.py]** Deux instances Redis indépendantes : `get_redis` singleton dans `dependencies.py` et `_redis` module-level dans `score.py`. Pas de risque de sécurité mais doublon de connexions Redis en prod — à consolider via `get_redis` dans une prochaine story.

---

## 2026-05-16 Story 2-4 — Suppression compte et données personnelles (RGPD)

### INFO

- **[security.py]** `delete_supabase_user()` utilise la clé `service_role_key` uniquement côté backend — jamais exposée dans les réponses API ni dans les logs
- **[security.py]** Appel Supabase Admin API via `httpx.AsyncClient` — connexion HTTPS, pas de persistance du client (nouvelle connexion par appel). Acceptable en MVP.
- **[user.py]** Suppression DB ordonnée : `user_favorites` puis `subscriptions` avant suppression du compte Supabase — évite un état où le compte Supabase est supprimé mais les données locales persistent
- **[endpoints/user.py]** `user_id` extrait exclusivement du JWT validé (`current_user["id"]`) — jamais passé en paramètre client. Isolation correcte.
- **[endpoints/user.py]** Route protégée par `get_current_user` (HTTPBearer) — retourne 403 sans header `Authorization`

### WARNING

- **[security.py]** `delete_supabase_user()` ne logue pas le statut Supabase en cas de succès (200 ou 204) — si Supabase renvoie 200 avec un body d'erreur non standard, l'erreur est silencieuse. Recommandation : logger le status code en DEBUG même en cas de succès.
- **[config.py]** `supabase_service_role_key: str = ""` — valeur par défaut vide string. En dev sans cette variable, l'appel Supabase échouera avec 401 mais retournera une `HTTPException(500)` opaque. Recommandation : valider que la clé est non-vide au démarrage (validator Pydantic) en environment `production`.
- **[endpoints/user.py]** Pas de vérification que l'utilisateur a bien un abonnement ou des données avant suppression — un utilisateur peut appeler l'endpoint plusieurs fois sans effet de bord (idempotent), ce qui est correct, mais chaque appel déclenche une tentative de suppression Supabase potentiellement inutile après la première.

### Secrets ajoutés

| Secret | Fichier | Exposé client | Rotation |
|--------|---------|---------------|---------|
| `SUPABASE_SERVICE_ROLE_KEY` | `.env` backend + `docker-compose.dev.yml` | Jamais | Si leak détecté |

---

## 2026-05-16 Story 2-4 — Suppression compte et données personnelles RGPD

### WARNING

- **[security.py:45-46]** `httpx.AsyncClient().delete()` appelé sans timeout explicite. Si l'API Admin Supabase est lente ou bloque, la coroutine FastAPI peut rester suspendue indéfiniment, épuisant le pool de workers Gunicorn. Recommandation : `httpx.AsyncClient(timeout=10.0)` — 10s est largement suffisant pour un appel Admin Supabase, et la gestion du `TimeoutException` doit lever une `HTTPException(503)` ou `500` avec le code `INTERNAL_ERROR` existant.
- **[security.py:47]** En cas d'échec Supabase (`response.status_code not in (200, 204)`), les données DB ont déjà été supprimées (`delete_user_data` est appelé en premier dans `user.py:31`). L'utilisateur se retrouve dans un état incohérent : données locales effacées, compte Supabase toujours actif. Le JWT reste valide jusqu'à expiration, permettant des appels API sans données associées. Recommandation : soit inverser l'ordre (supprimer Supabase en premier, puis DB sur succès), soit implémenter un soft-delete DB avec nettoyage asynchrone en cas d'échec Supabase.
- **[config.py:15]** `supabase_service_role_key: str = ""` — valeur par défaut vide sans validation au démarrage. Si la variable est absente du `.env`, la clé sera une chaîne vide ; `delete_supabase_user` appellera l'API Admin avec `Authorization: Bearer ` vide, recevra un 401 Supabase, et retournera une `HTTPException(500)`. L'app démarre sans avertissement malgré une clé critique manquante. Recommandation : valider au startup (`lifespan`) que `settings.supabase_service_role_key` est non-vide, sinon logger un `CRITICAL` et refuser les requêtes de suppression.
- **[.env.example]** `SUPABASE_SERVICE_ROLE_KEY` absent du fichier `.env.example`. Un développeur qui clone le repo ne saura pas que cette variable est requise pour `DELETE /api/v1/user`. Recommandation : ajouter `SUPABASE_SERVICE_ROLE_KEY=` au `.env.example` avec un commentaire `# Service role — jamais exposé côté client`.

### INFO

- **[user.py:30]** `user_id = str(current_user["id"])` — `current_user` est le retour direct de `get_current_user` qui extrait `sub` du JWT validé localement. Aucune possibilité d'IDOR : un utilisateur authentifié ne peut supprimer que son propre compte. Isolation correcte.
- **[security.py:40]** URL Admin Supabase construite avec `f"{supabase_url}/auth/v1/admin/users/{user_id}"` — `user_id` est le `sub` extrait du JWT validé, pas un paramètre client. Pas de path traversal possible.
- **[security.py:41-44]** `service_role_key` utilisé uniquement dans les headers HTTP côté serveur — jamais sérialisé dans les logs, jamais retourné dans une réponse. Aucune fuite côté client.
- **[user.py:33]** `logger.info("user_deleted", extra={"user_id": user_id})` — seul l'UUID (non sensible en soi) est loggé. Pas d'email, pas de token, pas de données personnelles dans ce log.
- **[AuthContext.tsx:79-80]** Après suppression backend réussie, `supabase.auth.signOut()` est appelé côté mobile pour invalider la session locale, puis `AsyncStorage.clear()` efface l'intégralité du stockage AsyncStorage. Scope correct : AsyncStorage est isolé par app sur iOS, donc l'effacement est complet pour Cloudbreak. Aucune donnée résiduelle dans le cache local.
- **[DeleteAccountModal.tsx:19]** Vérification email côté client uniquement (`emailInput.trim() === userEmail`) — cette vérification est une UX de protection contre la suppression accidentelle, pas un contrôle de sécurité. L'autorisation réelle est assurée par le JWT côté backend. C'est l'architecture correcte : le client peut contourner ce check (jailbreak), mais cela n'aboutit qu'à supprimer son propre compte, ce qui est l'opération demandée.
- **[user.py:23-24]** Suppressions via `delete(Favorite).where(...)` et `delete(Subscription).where(...)` — SQLAlchemy paramétré, aucun SQL brut, pas d'injection. `user_id` provient du JWT, pas d'un paramètre de requête.
- **[user.py:16-18]** Le commentaire documente explicitement que `predictions`, `terrain_validations` et `events` sont ignorées silencieusement car les tables n'existent pas encore. À revoir avant release 1.0.0 pour garantir la complétude RGPD lorsque ces tables seront créées.

---

## 2026-07-19 Story 7-1 — Recherche et détail des sommets rendus publics

### Contexte
L'onboarding mobile (story 7.1) doit permettre à un utilisateur de chercher et choisir un sommet **avant connexion** (pré-login). `GET /api/v1/peaks/search` et `GET /api/v1/peaks/{slug}` ne peuvent donc plus exiger de JWT.

### INFO
- **[peaks.py]** `Depends(get_current_user)` retiré des deux endpoints — plus aucune dépendance d'auth sur `search_peaks` et `get_peak`
- **[peaks.py]** Aucune donnée utilisateur exposée par ces endpoints : `Peak` contient uniquement des données OSM publiques (nom, slug, altitude, coordonnées, région) — pas de PII, pas de lien vers `users`/`favorites`/`predictions`
- **[peaks.py]** Énumération non sensible : parcourir les slugs de sommets ne révèle rien de confidentiel (données déjà publiques sur OpenStreetMap/IGN)
- **[peaks.py]** `POST/DELETE/GET /api/v1/user/favorites` restent protégés par JWT — seuls les endpoints de lecture pure (recherche + détail) sont ouverts
- Rate limiting global (à implémenter avant prod, cf. checklist) reste la seule protection anti-abus sur ces routes désormais publiques — pas de dégradation supplémentaire du risque puisqu'aucun rate limiting n'existait déjà pour les routes authentifiées

### WARNING
- **[peaks.py]** Ces endpoints étant maintenant appelables sans compte, un attaquant peut scripter des appels `GET /peaks/search` en boucle sans coût d'authentification préalable — renforce l'importance du rate limiting global (checklist prod) qui n'est toujours pas implémenté

---

## 2026-07-21 Story 1-7 — Taxonomie & instrumentation events (backend)

### Contexte
Nouveau module `app/services/analytics.py` (`track()`) : stub `logger.debug` uniquement, aucun appel réseau (PostHog sera branché derrière cette interface plus tard). Appelé depuis `score.py` (`score_calculated`), `core/dependencies.py` (`quota_bypassed`/`quota_exceeded`), `favorites.py` (`favorite_added`/`removed`), `user.py` (`account_deleted`).

### INFO
- **[app/services/analytics.py]** Stub sans réseau confirmé — aucune fuite possible tant que PostHog n'est pas branché ; `user_id` loggé est bien l'UUID Supabase (`sub` du JWT), jamais l'email ni le token
- **[score.py:111-115]** Properties `peak_id`/`verdict`/`score` — aucune donnée sensible
- **[core/dependencies.py:119,136]** Properties `plan`/`peak_id` — aucune donnée sensible
- **[favorites.py:74,114]** Properties `peak_id` uniquement
- **[user.py:35]** `account_deleted` tracké sans property — cohérent avec RGPD (pas de donnée résiduelle après suppression)
- Aucune duplication détectée avec les events mobile pour une même action (ex : mobile trace l'intention `delete_account_initiated`, le backend trace l'issue `account_deleted` — un seul propriétaire par étape du flux)

### WARNING
- **[app/services/analytics.py]** Le stub logue `user_id` en clair au niveau DEBUG — s'assurer que `LOG_LEVEL=DEBUG` ne soit jamais actif en prod (déjà couvert par la checklist "Logs ne contiennent aucun secret ou donnée personnelle" plus bas, mais à re-vérifier explicitement quand PostHog sera branché : ne pas envoyer `user_id` brut à PostHog sans le passer par un identifiant anonymisé/hashé si l'usage prévu est de l'analytics agrégée)

---

## 2026-07-24 Story 6-1 — Validation Terrain (Confirmation/Infirmation)

### Contexte
Nouveau flux : `GET /api/v1/score` persiste désormais une `Prediction` (best-effort) à chaque calcul, et `POST /api/v1/validations` permet à l'utilisateur de confirmer/infirmer une prédiction depuis le terrain, avec `lat`/`lng` optionnels.

### INFO
- **[terrain_validation.py]** Première fois que le backend persiste une **géolocalisation réelle** de l'utilisateur (`lat`/`lng` en `Float`, nullable). Jusqu'ici le projet ne lisait que le *statut de permission* de géolocalisation côté mobile (`docs/security.md` App Privacy — "Localisation précise... opt-in"), jamais de coordonnées effectives stockées où que ce soit. `lat`/`lng` restent optionnels côté schéma (`TerrainValidationCreate`) : un utilisateur qui refuse la permission peut valider sans coordonnées.
- **[prediction.py / terrain_validation.py]** `user_id` stocké en `String` (pas de type UUID contraint) — cohérent avec le pattern déjà en place sur `favorites`/`subscriptions` (voir WARNING story 3-3 plus haut sur `Favorite.user_id`), pas une nouvelle divergence introduite par cette story.
- **[validations.py]** `user_id` extrait exclusivement de `current_user["id"]` (JWT validé) — jamais passé en paramètre client. Isolation correcte, même pattern que les endpoints précédents.
- **[validations.py]** Requête `select(Prediction).where(Prediction.id == body.prediction_id)` — SQLAlchemy ORM paramétré, pas de SQL brut, pas d'injection possible.
- **[score.py]** La persistance de `Prediction` est enveloppée dans un `try/except` : un échec DB n'empêche pas l'endpoint score de répondre (best-effort), et ne fuite pas de détail interne au client — seul `logger.error("prediction_persist_failed", ...)` est loggé côté serveur.
- Aucun nouveau secret ni variable d'environnement introduit par cette story.

### WARNING
- **[validations.py]** N'importe quel utilisateur authentifié peut confirmer/infirmer **n'importe quel `prediction_id`** existant, y compris une prédiction créée par un autre utilisateur (pas de vérification `Prediction.user_id == current_user_id`). Le risque est limité (pas de données sensibles exposées, `prediction_id` est un UUID non énumérable), mais un attaquant en possession d'un `prediction_id` d'un tiers (ex: partagé par erreur) pourrait polluer ses statistiques de validation terrain. À évaluer avant recalibration de l'algo sur ces données (story future) — la légitimité du couple `(prediction_id, user_id)` n'est pas garantie.
- **[terrain_validation.py]** `photo_url` existe déjà en colonne (`nullable`) mais est toujours forcé à `null` côté endpoint — non exploitable en l'état, mais **story 6.2** (upload photo) devra faire l'objet d'une revue sécurité dédiée : validation du type de fichier, limite de taille, contrôle d'accès au stockage (éviter qu'un `photo_url` pointe vers une ressource accessible sans auth ou qu'un utilisateur puisse écraser/lire la photo d'un autre), et scan éventuel de contenu.
- **[user.py]** Le commentaire RGPD signalé en 2026-05-16 (story 2-4) sur `predictions`/`terrain_validations` ignorées silencieusement lors de `DELETE /api/v1/user` reste d'actualité **et devient concret maintenant que ces tables existent réellement** : la suppression de compte ne nettoie toujours pas `predictions` ni `terrain_validations` — à corriger avant release 1.0.0 pour la complétude RGPD.

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

---

## App Privacy Apple — données déclarées (App Store Connect)

Story 4.4 (AC6) — checklist à reporter dans **App Store Connect → App Privacy** avant soumission. Chaque SDK intégré dans l'app doit être déclaré avec les données exactes qu'il collecte.

### Checklist App Privacy — données déclarées

| Donnée | SDK | Usage | Lié à l'identité ? |
|--------|-----|-------|-------------------|
| Email | Supabase | Auth | Oui |
| Identifiant utilisateur | Supabase | Fonctionnalité app | Oui |
| Données d'utilisation | PostHog | Analytics | Non (anonymisé) |
| Localisation précise | expo-location | Fonctionnalité opt-in | Non |
| Crashs | Expo | Debugging | Non |

### Points de vigilance spécifiques Cloudbreak

1. **PostHog** — déclarer "données d'utilisation" pour "analytics", pas pour ciblage publicitaire
2. **Supabase** — déclarer "email" et "identifiant utilisateur" liés à l'identité
3. **expo-location** — déclarer "localisation précise" avec usage "fonctionnalité app" et opt-in explicite
4. **Pas de pub, pas de tracking tiers** → section "Tracking" App Store Connect = vide

> ⚠️ **Déclarer honnêtement** — une fausse déclaration App Privacy est une cause de bannissement Apple.
