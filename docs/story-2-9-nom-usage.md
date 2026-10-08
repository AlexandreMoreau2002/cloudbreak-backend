# Story 2.9 — Nom d’usage côté serveur

## Idée

Le compte garde un nom facultatif que la personne choisit elle-même. Le nom appartient au
profil Cloudbreak, pas au compte Apple ni à l’adresse e-mail. Il reste dans la base du backend
et revient dans les réponses de profil. Un compte temporaire ne peut pas l’écrire.

## Fonctionnement

```text
iPhone Profil → PATCH authentifié → validation FastAPI → PostgreSQL display_name
      ↑                                                        │
      └────────────── profil renvoyé / carte mise à jour ──────┘
```

`PATCH /api/v1/user/display-name` reçoit `display_name`, une chaîne de 1 à 25 caractères,
ou `null` pour effacer le nom. Le serveur retire les espaces au début et à la fin, refuse les
champs supplémentaires et n’accepte que les comptes permanents authentifiés. La réponse est le
profil actualisé. `GET /api/v1/user/me` expose aussi le nom ; pour un compte anonyme, le nom est
`null`.

La suppression du compte efface la ligne `users` et donc le nom d’usage. Le champ n’est pas
ajouté aux logs ou aux événements analytics.

## Fichiers concernés

- `app/models/user.py` et `alembic/versions/fb27705a94f7_add_user_display_name.py` : colonne
  nullable, limitée à 25 caractères, et migration.
- `app/schemas/user.py` : validation, nettoyage des espaces et contrat de réponse.
- `app/api/v1/endpoints/user.py` : route authentifiée et retour du profil.
- `app/services/user.py` : écriture du nom et suppression avec le profil utilisateur.
- `tests/test_api_user.py`, `tests/test_services_user.py` et
  `tests/test_migration_add_user_display_name.py` : couverture API, service et migration.
- `http/user.http` : appels REST Client pour lecture, écriture, effacement et erreurs.
- `docs/security.md` : traitement et cycle de vie de cette donnée personnelle.

## Vérification

Les appels prêts à lancer sont dans [`http/user.http`](../http/user.http). Le guide iPhone local
se trouve dans [`story-2-9-nom-usage/guide-test.md`](story-2-9-nom-usage/guide-test.md).
