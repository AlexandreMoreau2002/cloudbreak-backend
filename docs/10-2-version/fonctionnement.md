# Fonctionnement de la version backend

La route publique `GET /version` permet de retrouver le commit Git du backend qui répond. La console ops peut ainsi vérifier quel build est déployé.

```text
Git et date du build
        |
        | GIT_SHA, BUILT_AT, GIT_TAG (facultatif)
        v
Dockerfile (ARG -> ENV)
        |
        v
Settings  <--- version applicative
        |
        v
GET /version  --->  Réponse JSON à cinq champs
```

| Champ | Signification | Repli |
| --- | --- | --- |
| `service` | Nom du service | Toujours `backend` |
| `sha` | Commit Git du build | `"unknown"` si le SHA est absent ou vide |
| `built_at` | Date du build fournie en ISO 8601 UTC | `null` si la date ou le SHA manque |
| `version` | Version applicative du backend | `1.0.0` par défaut |
| `tag` | Tag `vX.Y.Z` fourni si le commit correspond exactement au tag | `null` si le tag est absent ou vide |

La route renvoie les métadonnées présentes dans l'image ou l'environnement d'exécution. Le build fournit le SHA, la date UTC et, le cas échéant, le tag Git. La réponse se limite aux champs listés et ne nécessite aucun accès à Postgres ou Redis.

## Fichiers

- `Dockerfile` transmet les trois métadonnées du build au conteneur.
- `app/core/config.py` charge ces métadonnées.
- `app/main.py` enregistre la route à la racine du serveur.
- `app/api/v1/endpoints/version.py` et `app/schemas/version.py` construisent la réponse publique.
- `tests/test_api_version.py` couvre le contrat HTTP.
- `http/version.http` contient les requêtes prêtes à exécuter dans VS Code REST Client.
