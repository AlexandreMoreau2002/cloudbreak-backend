# Story 5.1 — Infrastructure push (backend)

## Objectif

L'app envoie le token Expo Push de l'appareil au backend, qui le stocke sur le compte
(`users.push_token`). Un service `notifications.py` sait envoyer un push via l'API Expo
et marque les tokens morts comme invalides. Les alertes elles-mêmes viennent dans les
stories suivantes.

```text
App (expoPushToken) -- POST /api/v1/user/push-token --> users.push_token
                                                              |
Job d'alertes (plus tard) -> send_push_to_user -> exp.host -> APNs -> iPhone
```

## Critères d'acceptation

- `POST /api/v1/user/push-token` enregistre le token (204) ; format `ExponentPushToken[x]` /
  `ExpoPushToken[x]` non vide, 255 caractères max, sinon 422.
- `DELETE /api/v1/user/push-token` retire le token (204), appelé à la déconnexion.
- Compte anonyme : 403 `ACCOUNT_REQUIRED` ; sans `Authorization` : 403.
- Le token n'est jamais renvoyé par l'API ni loggué.
- `send_push_to_user` ne lève jamais ; `DeviceNotRegistered` passe `push_token_valid` à false ;
  un nouvel enregistrement le remet à true.
- La suppression de compte supprime la ligne `users`, donc le token.

## Fichiers

- `app/models/user.py` : colonnes `push_token` (indexée) et `push_token_valid`
- `alembic/versions/a5b1c2d3e4f5_add_user_push_token.py` : migration + index `ix_users_push_token`
- `app/schemas/user.py` : `PushTokenUpdate`
- `app/services/user.py` : `set_push_token`, `clear_push_token`
- `app/api/v1/endpoints/user.py` : routes `POST`/`DELETE /push-token`
- `app/services/notifications.py` : `send_push_to_user`
- `http/user-push-token.http`, `docs/security.md`
- Tests : `test_migration_add_user_push_token.py`, `test_schemas_user.py`, `test_services_user.py`,
  `test_api_user.py`, `test_services_notifications.py`, `features/test_feature_push_token_flow.py`

## Décisions

- **Comptes permanents uniquement** : `users` ne contient que des comptes permanents
  (`get_permanent_user`). Le token n'est enregistré qu'après création de compte (écart avec la
  spec initiale qui autorisait les anonymes).
- **Un seul appareil par compte** : un token par utilisateur.
- **Index sur `push_token`** : l'enregistrement fait un `UPDATE ... WHERE push_token = ?` pour
  purger le token chez les autres comptes ; sans index, full scan.
- **Purge du token partagé** : si le même token est enregistré par un autre compte (téléphone
  partagé), il est retiré de l'ancien propriétaire.
- **Commit volontaire sur `DeviceNotRegistered`** : l'invalidation survit à un rollback de l'appelant.
- **Aucun rate limiting pour l'instant** : à traiter avant la release 1.0.0 (voir `security.md`).
