# Story 10.2 — Provenance du backend

La console ops peut identifier le build du backend via la route publique `GET /version`.

Le contrat, le flux de données et les fichiers modifiés sont décrits dans le [fonctionnement](10-2-version/fonctionnement.md). Le [guide de test](10-2-version/guide-test.md) couvre le build local, les métadonnées renseignées, le tag vide et la première vérification sur Dokploy.

La suite `tests/test_api_version.py` vérifie la route en configuration production, les valeurs locales par défaut, le tag vide et l'absence de secret. Le fichier [version.http](../http/version.http) fournit les requêtes locale et dev.
