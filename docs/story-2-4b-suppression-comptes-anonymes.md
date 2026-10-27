# Story 2-4b — Suppression des comptes anonymes (RGPD) et durcissement

## Concept

Toute session authentifiée, y compris anonyme, peut exercer son droit à l'effacement via
`DELETE /api/v1/user` (`get_current_user` au lieu de `get_permanent_user`). La suppression purge
les données en base, les clés de quota Redis, puis le compte Supabase.

## Flux

```
DELETE /api/v1/user  (Bearer JWT, anonyme ou permanent)
   |
   v
get_current_user  -- JWT invalide/absent --> 401 / 403
   |
   v
RateLimitService.check_delete_account  -- > 5 / heure / user --> 429 RATE_LIMIT_EXCEEDED
   |
   v
delete_user_data      users, favoris, validations, predictions,
   |                  events Apple (par original_transaction_id), subscriptions
   v
QuotaService.delete_user_keys   quota:{user_id}:*  (SCAN, best-effort)
   |
   v
delete_supabase_user  DELETE {SUPABASE_URL}/auth/v1/admin/users/{id}
   |    200/204                      -> OK
   |    404 + error_code=user_not_found -> OK (rejeu idempotent)
   |    autre 404 / autre statut     -> 500 INTERNAL_ERROR (+ logger.warning)
   |    timeout                      -> 503 SERVICE_UNAVAILABLE
   v
204 No Content
```

## Fichiers impactés

| Fichier | Rôle |
|---------|------|
| `app/api/v1/endpoints/user.py` | Rate-limit puis orchestration de la suppression |
| `app/services/rate_limit.py` | `check_delete_account` : 5 tentatives / heure / utilisateur |
| `app/core/security.py` | `delete_supabase_user` : 404 accepté seulement avec `user_not_found` |
| `app/services/user.py`, `app/services/quota.py` | Purge DB et clés Redis |
| `tests/test_security.py`, `tests/test_rate_limit.py`, `tests/test_api_user.py`, `tests/features/test_feature_delete_account.py` | Tests |
| `http/user.http` | Requêtes de suppression (nominal, 403, 429) |

## Décisions

- 404 Supabase : un 404 peut venir d'une URL mal configurée ; sans le marqueur
  `error_code == "user_not_found"` on échoue en 500 plutôt que de prétendre avoir supprimé le compte.
  Le log ne contient que le statut HTTP (ni identifiant, ni clé).
- Rate-limit : même mécanique que le push token (clé Redis préfixée, identifiant hashé SHA-256),
  par utilisateur uniquement, fenêtre fixe d'1 h, limite 5. Erreur au format `{"detail", "code"}`.
- Ordre : données DB avant le compte Supabase, pour ne pas laisser de données orphelines si
  Supabase échoue (l'appel peut être rejoué : tout est idempotent).

## Limites connues

- Les events Apple sans `original_transaction_id` ne sont pas rattachables à un utilisateur et ne
  sont pas purgés (ledger d'idempotence, aucune donnée directement identifiante).
- Le JWT est validé localement (`app/core/dependencies.py::get_current_user` : signature, `aud`,
  `iss`, expiration ; aucun appel Supabase ni DB). Après suppression, le token reste donc accepté
  jusqu'à son expiration ; un appel ultérieur avec ce token peut par exemple recréer une ligne via
  le provisioning.
- Les comptes anonymes abandonnés (jamais supprimés par l'utilisateur) restent dans
  `auth.users` : une purge automatique planifiée reste à concevoir.
- Le comportement de l'API Admin Supabase pour les anonymes n'a pas été vérifié sur une instance réelle.
- Pas de rate-limit par IP.
