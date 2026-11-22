# Tester la version backend

## Prérequis

- Docker et Docker Compose pour tester le backend local.
- Un fichier `.env` de développement dans le sous-module backend. Si le fichier est absent, le créer depuis `.env.example`.
- VS Code REST Client ou `curl`.

## 1. Build local sans métadonnées

1. Ouvrir le fichier `.env` local et retirer ou commenter les éventuelles entrées `GIT_SHA`, `BUILT_AT` et `GIT_TAG`.
2. Lancer `make dev`. Si le service API existait déjà, appliquer les réglages avec `docker compose -f docker-compose.dev.yml up -d --force-recreate api`.
3. Exécuter la requête locale dans [version.http](../../http/version.http), ou `curl -i http://localhost:8000/version`.
4. Vérifier HTTP 200 et les valeurs `service="backend"`, `sha="unknown"`, `built_at=null`, `tag=null` et la valeur de `version` du backend.
5. Exécuter `curl -i http://localhost:8000/api/v1/version` et vérifier HTTP 404.

## 2. Métadonnées injectées

1. Ajouter des valeurs de test dans le fichier `.env` local.

   ```dotenv
   GIT_SHA=9f3c2ab
   BUILT_AT=2026-11-22T10:15:00Z
   GIT_TAG=v1.0.0
   ```

2. Recréer le service API avec `docker compose -f docker-compose.dev.yml up -d --force-recreate api` et rejouer la requête locale.
3. Vérifier que le SHA, la date de build et le tag correspondent aux valeurs de test et que la réponse contient exactement les cinq champs du contrat.
4. Vider `GIT_TAG`, recréer le service et vérifier que `tag` vaut `null` avec le même SHA et la même date.
5. Vider `GIT_SHA` en gardant la date renseignée, recréer le service puis vérifier `sha="unknown"` et `built_at=null`.
6. Rétablir les valeurs du fichier `.env` et recréer le service API.

## 3. Premier déploiement dev

1. Interroger `GET /version` avec la requête dev dans [version.http](../../http/version.http).
2. Comparer le SHA au commit du déploiement, la date à l'heure du build en UTC, et le tag à un éventuel tag exact du commit.
3. Si Dokploy ne fournit pas ces métadonnées, renseigner `GIT_SHA`, `BUILT_AT` et `GIT_TAG` dans les build args de l'application puis reconstruire l'image et vérifier la réponse. Sur un commit sans tag, laisser `GIT_TAG` vide.

## Checklist

- [ ] HTTP 200 sans jeton sur `/version` et HTTP 404 sur `/api/v1/version`.
- [ ] Exactement cinq champs, métadonnées renseignées attendues et aucun secret.
- [ ] Valeurs de repli vérifiées sans build args et avec un tag vide.
- [ ] Métadonnées de l'image vérifiées lors du premier déploiement dev.
