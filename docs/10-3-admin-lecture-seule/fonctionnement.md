# Admin lecture seule

La route `GET /api/v1/admin/overview` ne donne que des compteurs et des états techniques.

```text
JWT admin + allowlist -> overview -> SQL + Redis -> réponse agrégée
cron VPS -> X-Cron-Secret -> heartbeats/métriques -> SQL/Redis
```

Chaque lecture autorisée laisse une trace d'audit sans email, jeton ni autre donnée personnelle.
