# Story 2.5 — Provisioning du compte permanent

Le backend conserve l’identité dans Supabase `auth.users` et le profil applicatif dans sa
base PostgreSQL `users`. La ligne applicative n’est créée qu’après conversion vers un compte
permanent, jamais pour une session anonyme.

## Contrat

- `POST /api/v1/user/provision` exige un JWT permanent et est idempotent. L’UUID vient
  exclusivement de la claim `sub`; le body est vide. Un JWT anonyme reçoit `403` avec le code
  `ACCOUNT_REQUIRED`.
- `PATCH /api/v1/user/survey` accepte uniquement `acquisition_source`, `practice`,
  `newsletter_opt_in` et `skipped`. La première réponse (ou le skip) est conservée ; les appels
  suivants sont sans effet.
- `GET /api/v1/user/me` expose `is_anonymous`, `provisioned`, `survey_completed_at` et
  `survey_skipped_at`.

Les écritures utilisent un insert PostgreSQL `ON CONFLICT DO NOTHING`, puis relisent la ligne,
ce qui rend le get-or-create sûr lors d’appels simultanés. Aucun e-mail, mot de passe ou JSON de
`user_metadata` n’est dupliqué.

## Migration et suppression

Appliquer la migration Alembic `f2a3b4c5d6e7_create_users`. La suppression RGPD efface la ligne
`users` et les données métier avant l’appel Admin Supabase qui supprime `auth.users`.

## Test manuel

Utiliser [`http/user-provisioning.http`](../http/user-provisioning.http) avec un JWT injecté par
variable d’environnement. Vérifier deux provisions successifs, le refus d’un JWT anonyme, une
réponse et un skip, puis `GET /me` et la suppression. Ne jamais inscrire de token dans ce fichier.
