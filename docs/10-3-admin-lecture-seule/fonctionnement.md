# Admin lecture seule

La route `GET /api/v1/admin/overview` ne donne que des compteurs et des états techniques.

Les comptes viennent exclusivement de la table `users` : les utilisateurs anonymes, qui ne sont
pas provisionnés dans cette table, ne sont pas comptés. Les deltas à 7 jours sont des créations
sur les sept derniers jours (`created_at >= J-7`), pas une reconstitution d'état historique.

```text
JWT admin + allowlist -> overview -> SQL + Redis -> réponse agrégée
cron VPS -> X-Cron-Secret -> heartbeats/métriques -> SQL/Redis
```

La série 90 jours contient uniquement les comptes de la table `users` et les checks. Un compte
supprimé ou purgé disparaît donc des valeurs recalculées. Chaque lecture laisse une trace d'audit
sans email, jeton ni autre donnée personnelle.
