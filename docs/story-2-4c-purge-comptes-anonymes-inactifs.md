# Story 2-4c — Purge automatique des comptes anonymes inactifs (RGPD)

Spec : `docs/superpowers/specs/2026-10-27-purge-anonymous-accounts-design.md` (racine, non versionné).
Fonctionnement détaillé : `docs/purge-anonymous-accounts/fonctionnement.md`.
Requêtes : `http/maintenance.http`.

## Concept

Les données d'une session anonyme perdue (`predictions`, `terrain_validations`,
`user_favorites`) ne peuvent plus être supprimées par l'utilisateur. Un cron quotidien appelle
`POST /internal/maintenance/purge-anonymous` qui efface les identifiants anonymes inactifs depuis
`ANON_RETENTION_DAYS` jours (30), en réutilisant les briques de la story 2.4b.

## Critères d'acceptation

- [x] Endpoint `POST /internal/maintenance/purge-anonymous` protégé par `require_cron_secret` :
      sans secret / mauvais secret / JWT seul → 403 `INTERNAL_AUTH_FAILED` ; secret absent ou
      < 32 car. → 503 `INTERNAL_JOBS_DISABLED`.
- [x] `SUPABASE_URL` ou `SUPABASE_SERVICE_ROLE_KEY` absent → 503 `SERVICE_UNAVAILABLE`, aucun traitement.
- [x] Candidats sélectionnés en une requête ORM : union des trois tables d'activité, dernière
      activité < now − rétention, aucune ligne `users`, les plus anciens d'abord, `LIMIT ANON_PURGE_MAX_PER_RUN`.
- [x] Suppression uniquement si Supabase renvoie `is_anonymous is True` ; un compte permanent n'est
      jamais supprimé (`skipped_not_anonymous`).
- [x] 404 `user_not_found` → purge des données locales et clés quota seulement.
- [x] Toute autre réponse Supabase (réseau, 5xx, 404 sans marqueur, corps invalide) → `errors`, rien supprimé.
- [x] `?dry_run=true` : mêmes décisions, aucune suppression.
- [x] Un échec sur un candidat n'arrête pas les suivants.
- [x] Ordre Supabase → local : un échec Supabase ne supprime rien (rejoué au passage suivant) ;
      un échec local après Supabase est terminé au passage suivant (404 `user_not_found` → local seul).
- [x] Verrou Redis `lock:anon-purge` (jeton unique, TTL 300 s, libération compare-et-supprime) sur
      la purge réelle : si déjà pris → 200, compteurs à 0 et `skipped_locked: 1`. Le dry_run ne le prend pas.
- [x] Réponse et logs : compteurs uniquement (`candidates`, `purged`, `skipped_not_anonymous`,
      `errors`, `dry_run`, `skipped_locked`), jamais d'identifiant.
- [x] Config `ANON_RETENTION_DAYS=30`, `ANON_PURGE_MAX_PER_RUN=200` (+ `.env.example`).

## Fichiers impactés

| Fichier | Rôle |
|---------|------|
| `app/api/v1/endpoints/internal_maintenance.py` | Route interne |
| `app/services/anonymous_purge.py` | Sélection + purge |
| `app/core/security.py` | `get_supabase_user`, `SupabaseAdminError` |
| `app/core/config.py`, `.env.example`, `README.md` | Variables |
| `app/main.py` | Router |
| `tests/test_anonymous_purge.py`, `tests/test_security.py`, `tests/test_api_internal_maintenance.py`, `tests/test_config.py`, `tests/features/test_feature_purge_anonymous_flow.py` | Tests |
| `http/maintenance.http` | REST Client |

## Reste à faire hors backend

- Cron VPS `cloudbreak-purge-anonymous.sh` (calqué sur `cloudbreak-run-favorites.sh`, header lu
  depuis un fichier, 04:00 Europe/Paris), d'abord en `dry_run` sur dev.
- `docs/infra-serveur.md` racine, `TODO.md`, `docs/versions.md` après merge.
- Politique de confidentialité (ops) : citer la durée de 30 jours.
