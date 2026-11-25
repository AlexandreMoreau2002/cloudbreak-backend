# Story 2-1 — Authentification Supabase (Backend)

## Ce qui a été fait

| Fichier | Rôle |
|---------|------|
| `app/core/security.py` | Validation JWT ECC P-256 via python-jose + clé publique JWKS |
| `app/core/dependencies.py` | Dependency FastAPI `get_current_user` — injecte l'utilisateur authentifié |
| `app/api/v1/endpoints/user.py` | Endpoint `GET /api/v1/user/me` — retourne `id` + `email` |
| `app/core/config.py` | Ajout `supabase_jwt_jwks`, `supabase_publishable_key`, `supabase_db_password` |
| `http/supabase-auth.http` | Requêtes REST Client — créer un compte et récupérer un JWT Supabase |
| `http/auth.http` | Requêtes REST Client — tester `/api/v1/user/me` avec/sans JWT |
| `.env` | Ajout `SUPABASE_JWT_JWKS`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_DB_PASSWORD` |
| `tests/test_security.py` | Tests validation JWT — token valide, invalide, expiré (100% coverage) |
| `tests/test_dependencies.py` | Tests `get_current_user` — 200, 401, 403 |
| `tests/test_db_session.py` | Tests session DB |
| `tests/test_main.py` | Test lifespan FastAPI |

## Comment ça fonctionne

### Validation JWT locale

Supabase signe les JWT avec une clé privée **ECC P-256**. Le backend valide les tokens avec la clé publique correspondante (JWKS), sans aucun appel réseau vers Supabase.

```
Mobile → supabase.auth.signInWithPassword() → JWT Supabase
JWT → Authorization: Bearer {token} → FastAPI
FastAPI → security.py → valide signature avec JWKS → payload
payload → get_current_user → {"id": "...", "email": "..."}
```

### Dependency FastAPI

`get_current_user` est injectée via `Depends()` sur chaque route protégée. Elle :
1. Extrait le Bearer token
2. Valide la signature ECC via `decode_supabase_jwt`
3. Vérifie la présence du claim `sub`
4. Retourne `{"id": sub, "email": email}`

### Supabase — configuration dev

- **Confirm email désactivé** : Authentication → Providers → Email → "Confirm email" → OFF
- À réactiver avant la release 1.0.0

## Comment tester

### Prérequis
- Backend Docker lancé : `docker compose -f docker-compose.dev.yml up -d`
- `.vscode/settings.json` configuré avec `supabaseUrl`, `supabaseKey`, `jwt`
- Environnement REST Client sur `local`

### Tests automatisés
```bash
source .venv/bin/activate
pytest --cov=app --cov-report=term-missing  # 12 tests, 100% coverage
```

### Tests manuels REST Client
1. **Créer un compte** — requête 1 dans `http/supabase-auth.http`
2. **Récupérer le JWT** — requête 2, copier `access_token` dans `settings.json > jwt`
3. **Tester l'endpoint protégé** — requête 1 dans `http/auth.http` → 200 avec `id` + `email`
4. **Sans token** → 403
5. **Token invalide** → 401

## Acceptance Criteria vérifiés

- [x] `GET /api/v1/user/me` avec JWT valide → 200 `{"id": "...", "email": "..."}`
- [x] `GET /api/v1/user/me` sans token → 403
- [x] `GET /api/v1/user/me` token invalide → 401
- [x] Validation JWT locale (zéro appel réseau Supabase)
- [x] `.vscode/settings.json` non commité (dans `.gitignore`)
- [x] 100% test coverage
- [x] 0 erreur ruff / mypy
