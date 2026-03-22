# Story 3.3 — Recherche de Sommet & Favoris (Backend)

## Ce qui a été fait

### Fichiers créés
| Fichier | Rôle |
|---------|------|
| `app/schemas/peak.py` | Schémas Pydantic `PeakSearchResult` (id, name, slug, altitude) et `PeakResponse` (+ lat, lng) |
| `app/schemas/favorite.py` | Schémas Pydantic `FavoriteCreate` (peak_id) et `FavoriteResponse` (id, peak_id, peak, created_at) |
| `app/models/favorite.py` | Modèle SQLAlchemy `Favorite` — table `user_favorites` (UUID PK, user_id, peak_id FK, created_at) |
| `app/api/v1/endpoints/peaks.py` | 5 endpoints : search, detail, add_favorite, remove_favorite, list_favorites |
| `alembic/versions/d7e8f9a0b1c2_create_user_favorites.py` | Migration : table `user_favorites` + index `user_id` + contrainte unique `(user_id, peak_id)` |
| `tests/test_api_peaks.py` | 6 tests : search 200 / liste vide / 422 / 401, detail 200 / 404 |
| `tests/test_api_favorites.py` | 8 tests : add 201 / doublon 409 / peak 404 / 401, remove 204 / 404, list 200 / 401 |

### Fichiers modifiés
| Fichier | Modification |
|---------|-------------|
| `app/main.py` | Ajout `include_router(peaks_router)` |
| `app/core/errors.py` | Ajout `ALREADY_EXISTS` error code |
| `app/models/__init__.py` | Export `Favorite` et `Peak` pour Alembic autogenerate |
| `alembic/env.py` | Import `app.models` pour que Alembic détecte les modèles |

## Comment ça fonctionne

### Recherche peaks
- `GET /api/v1/peaks/search?q=<min 2 chars>` → ILIKE `%q%` sur `peaks.name`, ordre alphabétique, limite 20
- Utilise l'index `idx_peaks_name` créé en story 3.2
- Retourne `PeakSearchResult[]` (id, name, slug, altitude) — léger pour autocomplete

### Détail peak
- `GET /api/v1/peaks/{slug}` → lookup par slug (index unique)
- Retourne `PeakResponse` complet (+ lat, lng pour affichage carte)

### Favoris
- `POST /api/v1/user/favorites` (body: `{"peak_id": "..."}`) → vérifie peak existant + doublon → 201
- `DELETE /api/v1/user/favorites/{peak_id}` → 204 ou 404
- `GET /api/v1/user/favorites` → JOIN `user_favorites` + `peaks`, trié par `created_at DESC`
- `user_id` extrait du JWT (string Supabase) — pas de table `users` ORM nécessaire
- Contrainte unique `(user_id, peak_id)` en DB — doublon → 409 ALREADY_EXISTS

## Comment tester

### Pré-requis
```bash
make dev          # démarrer api + db + redis
make migrate      # appliquer la migration user_favorites
```

### Requêtes manuelles
```bash
JWT="<token Supabase>"

# Recherche
curl -H "Authorization: Bearer $JWT" \
  "http://localhost:8000/api/v1/peaks/search?q=mont"

# Détail
curl -H "Authorization: Bearer $JWT" \
  "http://localhost:8000/api/v1/peaks/mont-blanc"

# Ajouter favori (obtenir un peak_id via search d'abord)
curl -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"peak_id":"<id>"}' "http://localhost:8000/api/v1/user/favorites"

# Lister favoris
curl -H "Authorization: Bearer $JWT" \
  "http://localhost:8000/api/v1/user/favorites"

# Supprimer favori
curl -X DELETE -H "Authorization: Bearer $JWT" \
  "http://localhost:8000/api/v1/user/favorites/<peak_id>"
```

### Tests automatiques
```bash
make validate    # 92 tests, 100% coverage
```

## Acceptance Criteria vérifiés

- [x] **AC1** : `q` minimum 2 chars → 422 si < 2 (validation Pydantic `min_length=2`)
- [x] **AC2** : Recherche retourne au max 20 résultats ILIKE sur le nom
- [x] **AC3** : Détail par slug → 404 PEAK_NOT_FOUND si inexistant
- [x] **AC4** : Ajout favori → 201 avec peak info jointe
- [x] **AC5** : Doublon → 409 ALREADY_EXISTS
- [x] **AC6** : Suppression → 204 ou 404 NOT_FOUND
- [x] **AC7** : Listage → 200 avec peak info (JOIN SQL)
- [x] **AC8** : Tous les endpoints → 403 sans JWT
