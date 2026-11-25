# Story 2.2 — Préférences de notifications

## Ce qui a été fait

- 3 nouvelles colonnes sur `users` : `notif_favorites`, `notif_regional`, `notif_terrain`
  (`Boolean`, `nullable=False`, défaut `true`) — migration `b7e2d4f6a9c1`
- Schéma `NotificationPreferencesUpdate` (`app/schemas/user.py`) — update partiel, les 3 champs
  optionnels
- Service `update_user_notification_preferences` (`app/services/user.py`) — ne modifie que les
  champs explicitement envoyés (`model_dump(exclude_unset=True)`)
- Endpoint `PATCH /api/v1/user/notifications` (`app/api/v1/endpoints/user.py`) — même garde que
  `/preferences` (403 `ACCOUNT_REQUIRED` pour une session anonyme)
- `GET /api/v1/user/me` expose désormais `notif_favorites`/`notif_regional`/`notif_terrain`
  (défaut `true` si le profil n'est pas encore provisionné)

## Comment ça fonctionne

Chaque préférence est indépendante. Le mobile envoie un payload partiel (`{"notif_favorites":
false}`) à chaque bascule de toggle — le backend ne touche que ce champ, les deux autres restent
inchangés en base.

## Comment tester

Voir `http/user-notifications.http`. Cas à vérifier manuellement : update d'une seule préférence,
update des 3 en un appel, payload vide, sans token, session anonyme.

## Acceptance Criteria vérifiés (epics.md Story 2.2)

- [x] Les 3 colonnes existent avec le bon défaut (`true`)
- [x] Une préférence désactivée est sauvegardée via `PATCH /api/v1/user/notifications`
- [x] `GET /me` reflète l'état à jour
