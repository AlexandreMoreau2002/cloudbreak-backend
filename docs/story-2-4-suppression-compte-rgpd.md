# Story 2-4 — Suppression du Compte et Données Personnelles (RGPD)

## Ce qui a été fait

| Fichier | Rôle |
|---------|------|
| `app/core/config.py` | Ajout de `supabase_service_role_key: str` dans `Settings` |
| `app/core/security.py` | Ajout de `delete_supabase_user()` — appel Supabase Admin API via httpx |
| `app/services/user.py` | Nouveau fichier — `delete_user_data()` : suppression des favoris et abonnements via SQLAlchemy |
| `app/api/v1/endpoints/user.py` | Ajout route `DELETE /api/v1/user/` — orchestre suppression DB + Supabase + log |
| `tests/test_api_user.py` | 3 tests ajoutés : 204 OK, 403 sans auth, vérification appel `delete_user_data` |
| `tests/features/test_feature_delete_account.py` | Nouveau fichier — flux complet : 403 sans auth, 204 flux nominal, ordre de suppression |

## Comment ça fonctionne

### Endpoint `DELETE /api/v1/user/`

1. `get_current_user` valide le JWT et extrait le `user_id`
2. `delete_user_data(user_id, db)` supprime en DB : `user_favorites` puis `subscriptions`
3. `delete_supabase_user(user_id, supabase_url, service_role_key)` appelle `DELETE {SUPABASE_URL}/auth/v1/admin/users/{user_id}` avec la clé service role
4. Log `logger.info("user_deleted", extra={"user_id": user_id})`
5. Retourne `204 No Content`

**Ordre garanti :** données DB supprimées avant le compte Supabase — évite un état incohérent si Supabase échoue.

**Sans auth :** HTTPBearer retourne `403 Forbidden` (comportement connu, cf. story 3.3).

### Supabase Admin API

```
DELETE {SUPABASE_URL}/auth/v1/admin/users/{user_id}
Authorization: Bearer {SUPABASE_SERVICE_ROLE_KEY}
apikey: {SUPABASE_SERVICE_ROLE_KEY}
```

Statuts acceptés : `200` ou `204`. Tout autre statut lève `HTTPException(500)`.

### Tables supprimées

- `user_favorites` — `Favorite.user_id == user_id`
- `subscriptions` — `Subscription.user_id == user_id`
- Tables non encore créées (`predictions`, `terrain_validations`, `events`) ignorées silencieusement.

## Comment tester

### Test unitaire

```bash
cd backend
source .venv/bin/activate
make validate
```

### Test manuel (requête HTTP)

```http
DELETE http://localhost:8001/api/v1/user/
Authorization: Bearer {JWT_VALIDE}
```

Résultat attendu : `204 No Content`, corps vide.

```http
DELETE http://localhost:8001/api/v1/user/
```

Résultat attendu : `403 Forbidden`.

## Acceptance Criteria vérifiés

- [x] AC1 — Modale de confirmation avec message "irréversible" + saisie email (implémenté côté mobile)
- [x] AC2 — `DELETE /api/v1/user` supprime `user_favorites` + `subscriptions` + compte Supabase → 204
- [x] AC3 — Post-suppression : signOut + AsyncStorage.clear + redirection login (AuthContext)
- [x] AC4 — Sans JWT → 403 Forbidden

## Variables d'environnement

```env
SUPABASE_SERVICE_ROLE_KEY=eyJ...  # Supabase Dashboard > Settings > API > service_role
```

À ajouter dans `infra/docker-compose.dev.yml` :
```yaml
- SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY}
```
