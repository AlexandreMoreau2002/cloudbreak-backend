# Story 2.5 — Provisioning du compte permanent

## État

Contrat implémenté sur `feature/parcours-compte-2-5-2-6-2-8`, en **review** avec gate de
configuration. Les tests backend mockent la session/JWT et la base ; ils ne prouvent pas un
signup Supabase réel, la conversion Anonymous Auth ni la réception OTP.

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

## Test manuel et cas limites

Utiliser [`http/user-provisioning.http`](../http/user-provisioning.http) avec un JWT injecté par
variable d’environnement. Vérifier deux provisions successifs (même profil), un JWT anonyme
(`403 ACCOUNT_REQUIRED`), un JWT absent/invalide (`401`), une réponse complète, une réponse
partielle, un skip puis `GET /me`. Vérifier qu'un second PATCH après réponse ou skip est sans
effet, qu'un champ inconnu ou une valeur d'enum invalide est rejeté (`422`) et que la concurrence
ne crée pas deux lignes. Tester enfin la suppression RGPD (données locales puis `auth.users`).
Ne jamais inscrire de token dans ce fichier.

## Dépendances de configuration

La migration `f2a3b4c5d6e7_create_users` doit être appliquée sur l'environnement ciblé. Les
variables Supabase/JWKS et la `service_role` key sont injectées par secret ; elles ne figurent
ni dans la documentation, ni dans les logs, ni dans le fichier HTTP. La levée de la gate exige
une preuve mobile de l'UUID conservé avant/après conversion et une preuve backend de la ligne
`users` correspondante.
