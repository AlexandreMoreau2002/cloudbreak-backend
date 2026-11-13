# Story 1.7 — Taxonomie & Instrumentation Events PostHog (Stub) — Backend

## Ce qui a été fait

- `app/services/analytics.py` (nouveau) — stub `track(event, user_id, properties)`, log DEBUG uniquement, aucun appel réseau.
- `track()` câblé à 6 points métier existants :
  - `score_calculated` — `app/api/v1/endpoints/score.py` (après calcul du score)
  - `quota_bypassed` / `quota_exceeded` — `app/core/dependencies.py` (`check_quota`)
  - `favorite_added` / `favorite_removed` — `app/api/v1/endpoints/favorites.py`
  - `account_deleted` — `app/api/v1/endpoints/user.py`

## Comment ça fonctionne

Le stub ne fait que loguer en DEBUG (`logger.debug("analytics_event", extra={...})`). Aucune donnée ne quitte le serveur. Quand le vrai SDK PostHog sera branché (story 1.5, post-MVP), seul le corps de `track()` change — aucun appelant à modifier.

## Comment tester

```bash
source .venv/bin/activate
make validate   # ruff + mypy + pytest --cov, 100% attendu
```

Activer `LOG_LEVEL=DEBUG` dans `docker-compose.dev.yml` puis observer les logs `analytics_event` en conditions réelles (score consulté, quota atteint, favori ajouté/retiré, compte supprimé).

## Acceptance Criteria vérifiés

- [x] `score_calculated` avec `peak_id`, `verdict`, `score`
- [x] `quota_bypassed` avec `plan`
- [x] `quota_exceeded` avec `peak_id`, `plan`
- [x] `favorite_added` / `favorite_removed` avec `peak_id`
- [x] `account_deleted`
- [x] Favoris et endpoints existants inchangés (comportement HTTP identique, seul un log ajouté)
