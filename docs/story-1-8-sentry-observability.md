# Story 1.8 — Sentry backend

## Résultat

Le backend FastAPI peut signaler ses exceptions non gérées au projet Sentry `cloudbreak-backend` lorsque `SENTRY_DSN` est fourni dans Dokploy. Sans DSN, l'initialisation est un no-op : l'API démarre et aucun événement n'est envoyé.

## Périmètre

- `sentry-sdk[fastapi]` est initialisé avant la création de l'application.
- Le SDK reçoit l'environnement et la version de l'API.
- Aucun endpoint de test ni mécanisme de debug accessible publiquement n'a été ajouté.
- Better Stack conserve le contrôle d'uptime `/health` ; Sentry ne le remplace pas.

## Données et sécurité

Le mode est volontairement limité aux erreurs. Le filtre retire requêtes, utilisateurs, breadcrumbs, extras, messages et valeurs d'exception. Les corps de requête, variables locales, logs, profiling, sessions, tracing et propagation de trace HTTP sont désactivés. Les contextes de trace entrants sont retirés avant la sérialisation pour empêcher la fuite de valeurs `baggage` contrôlées par un appelant.

## Validation effectuée

- Tests ciblés avec le SDK réel, transport Sentry en mémoire et transport HTTPX en mémoire : aucune valeur synthétique (e-mail, jeton, `sentry-trace` ou `baggage`) ne se retrouve dans une enveloppe d'erreur ni dans une requête sortante.
- `make validate` : 708 tests passent ; cinq warnings existants restent signalés dans la sortie.
- Revue sécurité finale approuvée après deux corrections de confidentialité.

## Suite de déploiement

Poser `SENTRY_DSN` dans l'environnement Dokploy de développement, redéployer, puis vérifier un événement contrôlé hors production publique. Ne jamais inscrire le DSN dans Git, un ticket ou les logs.
