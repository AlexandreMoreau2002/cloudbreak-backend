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

### Ce qui n'existe pas encore
- Pas de rate limiting (à implémenter epic 3 ou avant prod)
- Pas de quota enforcement (epic 4)
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
