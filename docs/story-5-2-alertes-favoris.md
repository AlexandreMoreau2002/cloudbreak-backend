# Story 5.2 — Alertes push favoris (Premium, backend)

## Objectif

Un job planifié envoie, une fois par sommet et par jour cible, un push « Conditions idéales prévues demain 6h sur [sommet] — 87% 🟢 » aux abonnés Premium dont un favori passe en verdict `high`.

```text
cron (soir, 1x/jour)
  -> POST /internal/notifications/run-favorites  (header X-Cron-Secret)
       -> verrou Redis lock:favorite-alerts
       -> fetch_candidates (SQL : Premium actif + notif_favorites + token valide)
       -> score de chaque sommet distinct (météo en parallèle, 5 max)
       -> verdict "high" ? -> clé notif:fav:* (SET NX, 36 h) -> send_push_to_user
```

## Critères d'acceptation

- Alerte quand le verdict du lendemain 6h d'un favori est `high`, message localisé fr/en.
- Une seule alerte par utilisateur, sommet et jour cible (déduplication).
- Préférence « Alertes favoris » (`notif_favorites`) respectée ; utilisateur gratuit exclu.
- Endpoint interne inaccessible sans secret valide.

## Décisions

- Alerte régionale reportée en V2 (hors périmètre).
- `high` = verdict complet de `app/domain/score*.py` (score >= 70 ET inversion, base nuageuse, couverture basse), pas un simple seuil de score. `domain/score*.py` n'est pas modifié.
- Date cible = demain en Europe/Paris, heure 6. Le cron tourne le soir, avant minuit Paris.
- Déduplication : clé `notif:fav:{user}:{peak}:{date}` posée en `SET NX EX 36h` avant l'envoi, relâchée si l'envoi échoue ou lève.
- Verrou anti-chevauchement `lock:favorite-alerts` (jeton unique, TTL 600 s, libération compare-et-supprime) ; sinon `skipped_locked = 1`.
- Langue : `users.locale` (`fr` | `en`, nullable, repli `fr`), envoyée avec le token par `POST /api/v1/user/push-token`.
- Secret `INTERNAL_CRON_SECRET` d'au moins 32 caractères, sinon 503 (voir `docs/security.md`).
- Plafonds : 500 alertes par exécution, 2000 couples candidats, 5 appels météo simultanés.

## Fichiers

- `app/domain/favorite_alerts.py` : règles pures (date cible, verdict, messages, clé de déduplication)
- `app/services/favorite_alerts.py` : candidats, scoring, déduplication, envoi, verrou
- `app/api/v1/endpoints/internal_notifications.py` : endpoint cron
- `app/core/dependencies.py` : `require_cron_secret` ; `app/core/config.py`, `app/core/errors.py`, `.env.example`
- `alembic/versions/b7c8d9e0f1a2_add_user_locale.py`, `app/models/user.py`, `app/schemas/user.py`, `app/services/user.py`
- Tests : `tests/test_domain_favorite_alerts.py`, `tests/test_services_favorite_alerts.py`, `tests/test_api_internal_notifications.py`, `tests/features/test_feature_favorite_alerts_flow.py`
- HTTP : `http/internal-notifications.http`, `http/user-push-token.http`

## Reste à faire

Câblage du cron (une fois par soir), lecture des receipts Expo, et côté mobile l'envoi de la langue avec le token et le tap sur l'alerte.
