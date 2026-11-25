# Story 7.1 — Recherche et détail des sommets publics (Backend)

## Ce qui a été fait

### Fichiers modifiés
| Fichier | Modification |
|---------|-------------|
| `app/api/v1/endpoints/peaks.py` | Retrait de `Depends(get_current_user)` sur `GET /peaks/search` et `GET /peaks/{slug}` — imports `get_current_user` et `Any` supprimés, docstring module mise à jour |
| `tests/test_api_peaks.py` | Fixture `auth_override` supprimée (plus nécessaire) — les tests nominaux s'exécutent désormais sans header Authorization et documentent le caractère public dans leurs docstrings |
| `http/peaks.http` | Réécrit et détaillé : tous les cas (nominal, 422 q court, 422 q absent, liste vide, accents, détail 200, détail 404) avec résultat attendu commenté pour chaque requête — plus aucune variable jwt |
| `docs/security.md` | Surface d'attaque mise à jour + section datée story 7-1 (analyse du passage en public) |
| `docs/product-audit.md` | Section "Ce qui est fonctionnel" : peaks search/detail notés publics |

## Pourquoi

L'onboarding mobile de la story 7.1 permet à l'utilisateur de chercher et choisir
son sommet **avant de créer un compte** (pré-login). Le flux mobile appelle donc
`GET /peaks/search` et `GET /peaks/{slug}` sans JWT — ces endpoints devaient
cesser d'exiger l'authentification.

Pourquoi c'est sûr :
- Les données `Peak` sont **publiques par nature** (OSM : nom, slug, altitude, lat/lng, région)
- Aucune donnée utilisateur ni PII exposée — pas de lien vers `users`, `favorites` ou `predictions`
- Énumération non sensible : les slugs de sommets sont déjà publics sur OpenStreetMap
- Les endpoints favoris (`POST/DELETE/GET /api/v1/user/favorites`) **restent protégés par JWT**
- Le rate-limiting global (checklist prod) reste la protection anti-abus — inchangé par cette story

## Comment ça fonctionne

Avant : `HTTPBearer` (via `Depends(get_current_user)`) renvoyait 403 sans header
`Authorization`. Après : la dépendance est simplement retirée des deux endpoints
de lecture — plus aucune vérification d'auth, le reste du comportement est
inchangé (ILIKE limite 20, 422 si `q` < 2 chars, 404 `PEAK_NOT_FOUND` si slug
inconnu).

```
Mobile onboarding (pré-login, sans JWT)
  ↓ GET /api/v1/peaks/search?q=...
peaks.py — search_peaks(q, db)          ← plus de current_user
  ↓ SQLAlchemy ORM (bind parameters)
PostgreSQL — table peaks (données OSM publiques)
```

## Comment tester

### Tests automatiques
```bash
cd backend
source .venv/bin/activate
make validate    # ruff + mypy + pytest --cov — 203 tests, 100% coverage
```

### Tests manuels
```bash
make dev         # démarrer api + db + redis
make seed        # si la DB est vide
```

Puis dérouler `http/peaks.http` (VS Code REST Client) — chaque requête a son
résultat attendu en commentaire. Vérifications rapides en curl (noter l'absence
de header Authorization) :

```bash
# Recherche publique → 200 + liste
curl "http://localhost:8000/api/v1/peaks/search?q=mont"

# Détail public → 200 + objet complet
curl "http://localhost:8000/api/v1/peaks/mont-ventoux"

# Slug inconnu → 404 PEAK_NOT_FOUND
curl "http://localhost:8000/api/v1/peaks/slug-qui-nexiste-pas"

# Les favoris restent protégés → 403 sans JWT
curl "http://localhost:8000/api/v1/user/favorites"
```

## Acceptance Criteria vérifiés

- [x] **AC1** : `GET /api/v1/peaks/search` accessible sans JWT → 200 (plus de 403)
- [x] **AC2** : `GET /api/v1/peaks/{slug}` accessible sans JWT → 200 / 404 selon le slug
- [x] **AC3** : validations inchangées — `q` < 2 chars → 422, slug inconnu → 404 `PEAK_NOT_FOUND`
- [x] **AC4** : les endpoints favoris (`/api/v1/user/favorites`) restent protégés → 403 sans JWT
