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
| `sha` | Commit Git du build, de 7 à 40 caractères hexadécimaux | `"unknown"` si le SHA est absent ou invalide |
| `built_at` | Date du build au format ISO 8601, convertie en UTC avec suffixe `Z` | `null` si la date est absente, invalide ou sans fuseau, ou si le SHA est absent ou invalide |
| `version` | Version applicative du backend | `1.0.0` par défaut |
| `tag` | Tag de release au format `vX.Y.Z` | `null` si le tag ou le SHA est absent ou invalide |

Le build fournit le SHA et la date UTC et renseigne le tag uniquement s'il pointe exactement sur le commit déployé. La route vérifie le format des métadonnées. La réponse se limite aux champs listés et ne nécessite aucun accès à Postgres ou Redis.

## Fichiers

- `Dockerfile` transmet les trois métadonnées du build au conteneur.
- `app/core/config.py` charge ces métadonnées.
- `app/main.py` enregistre la route à la racine du serveur.
- `app/api/v1/endpoints/version.py` et `app/schemas/version.py` construisent la réponse publique.
- `tests/test_api_version.py` couvre le contrat HTTP.
- `http/version.http` contient les requêtes prêtes à exécuter dans VS Code REST Client.
