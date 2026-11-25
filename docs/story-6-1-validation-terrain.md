# Story 6.1 — Validation Terrain (Confirmation/Infirmation)

_Complétée le 2026-07-24_

---

## Ce qui a été fait

- [`app/models/prediction.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/models/prediction.py) — modèle `Prediction` : `id` (UUID), `peak_id` (FK `peaks`), `user_id`, `date`, `hour`, `score`, `verdict`, `cloud_base`, `created_at`. Une ligne par calcul de score réussi.
- migration Alembic — création de la table `predictions`.
- [`app/api/v1/endpoints/score.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/api/v1/endpoints/score.py) — persistance **best-effort** d'une `Prediction` à chaque `GET /api/v1/score` réussi, et exposition de `prediction_id` dans la réponse. Si la persistance échoue (exception DB), un `prediction_id` éphémère (UUID non persisté) est renvoyé quand même — une validation terrain qui le référencerait échouera proprement en 404 plutôt que de faire échouer tout l'endpoint score.
- [`app/models/terrain_validation.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/models/terrain_validation.py) — modèle `TerrainValidation` : `id` (UUID), `prediction_id` (FK `predictions`, `ondelete=CASCADE`), `user_id`, `result` (bool), `photo_url` (nullable, toujours `null` pour l'instant), `lat`/`lng` (nullable), `validated_at`.
- migration Alembic — création de la table `terrain_validations`.
- [`app/api/v1/endpoints/validations.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/api/v1/endpoints/validations.py) — endpoint `POST /api/v1/validations` : auth JWT requise, vérifie l'existence de la `Prediction` référencée (404 sinon), crée la `TerrainValidation`, logge `terrain_validated` et trace l'event analytics `terrain_validated`.
- [`app/schemas/validation.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/schemas/validation.py) — `TerrainValidationCreate` (`prediction_id`, `result`, `lat`/`lng` optionnels) et `TerrainValidationResponse` (réponse directe, pas de wrapper).
- test de feature — flux complet `GET /api/v1/score` → `POST /api/v1/validations`.
- [`http/validations.http`](/Users/alex/Desktop/dev/cloudbreak/backend/http/validations.http) — requêtes nominales (confirmation/infirmation) + sans JWT + payload invalide + `prediction_id` inconnu.

## Comment ça fonctionne

- Chaque appel réussi à `GET /api/v1/score` enregistre désormais une `Prediction` en base, en plus de calculer et retourner le score. C'est une écriture **best-effort** : si elle échoue, l'endpoint score continue de répondre normalement (l'utilisateur ne doit jamais être bloqué par un souci de traçabilité), mais le `prediction_id` renvoyé dans ce cas ne correspond à aucune ligne réelle — une tentative de validation terrain avec cet ID échouera en `404`.
- `POST /api/v1/validations` référence cette `Prediction` par son `id` : le client (mobile) envoie `{prediction_id, result, lat?, lng?}`, le backend vérifie que la prédiction existe puis crée la ligne `terrain_validations`. La réponse est directe (pas de wrapper `{"status": "ok", ...}`), conformément aux conventions du projet.
- `lat`/`lng` sont optionnels : si l'utilisateur refuse la géolocalisation côté mobile, la validation est quand même acceptée sans coordonnées.
- **Ce qui n'est PAS dans le scope de la 6.1 backend** :
  - **Pas de photo** — la colonne `photo_url` existe déjà dans le modèle et la migration (pour éviter une migration supplémentaire plus tard) mais reste toujours `null` : l'upload et le calcul du taux de précision associé sont prévus story 6.2.
  - **Pas de déclenchement par notification push** — l'Epic 5 (notifications) est bloqué (pas de compte Apple Developer pour les certificats APNs). La story 6.1 backend fournit uniquement l'endpoint `POST /api/v1/validations` ; le déclenchement de la `ValidationBottomSheet` (manuel depuis l'écran de prévision, ou via géolocalisation foreground sans notification) est entièrement côté mobile.

## Comment tester

- `backend/http/validations.http` — tous les cas (nominal confirmation/infirmation, sans JWT, `prediction_id` inconnu, payload invalide).
- `make validate` — 100% coverage.

## Acceptance Criteria vérifiés

Copiées verbatim depuis `_bmad-output/planning-artifacts/epics.md` (Story 6.1) :

> **Given** `ValidationBottomSheet` affiché (depuis notification GPS ou depuis l'écran de prévision)
> **When** l'utilisateur appuie sur "Oui — mer de nuage visible ✅"
> **Then** `POST /api/v1/validations` est appelé avec `{prediction_id, result: true, lat, lng, validated_at}`
> **And** la réponse est `201 Created`
> **And** un message de remerciement s'affiche : "Merci ! Ta validation aide à affiner les prévisions 🙏"

- [x] Couvert côté backend : `POST /api/v1/validations` accepte `{prediction_id, result, lat, lng}`, retourne `201 Created` avec le body créé (`validated_at` généré serveur). Voir [`validations.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/api/v1/endpoints/validations.py).
- [ ] **Non couvert par la 6.1 backend** : le déclenchement depuis une notification GPS. Epic 5 (notifications push) est bloqué faute de compte Apple Developer pour les certificats APNs — décision de scope validée explicitement par l'utilisateur pendant le brainstorming de cette story. Seul le chemin manuel (bouton sur l'écran de prévision) + géolocalisation foreground est couvert, et c'est un sujet mobile, pas backend.
- [ ] Le message de remerciement est un affichage mobile — hors scope backend.

> **Given** l'utilisateur appuie sur "Non — pas de mer de nuage ❌"
> **When** la requête est envoyée
> **Then** `result: false` est enregistré avec le même format

- [x] Couvert : `result: bool` accepté tel quel, aucune branche spéciale entre `true`/`false` dans `validations.py`.

> **Given** la table `terrain_validations`
> **When** la migration est appliquée
> **Then** elle contient : `id`, `prediction_id`, `user_id`, `result` (bool), `photo_url` (nullable), `lat`, `lng`, `validated_at`

- [x] Couvert : voir [`terrain_validation.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/models/terrain_validation.py) et la migration associée — toutes les colonnes listées sont présentes avec les bons types.

> **Given** un appel sans JWT valide
> **When** `POST /api/v1/validations` est appelé
> **Then** le backend retourne `401 Unauthorized`

- [x] Couvert fonctionnellement (accès refusé sans JWT) mais **avec un écart de code HTTP à noter** : comme pour tous les autres endpoints protégés du projet, `HTTPBearer` (FastAPI) retourne `403 Forbidden` quand le header `Authorization` est absent, pas `401`. C'est le comportement déjà en place partout ailleurs dans le backend (voir `docs/story-3-3-*.md` / mémoire projet) — pas une régression propre à la 6.1, mais l'AC telle qu'écrite dans `epics.md` mentionne `401`. Testé dans `http/validations.http` (cas "❌ Sans JWT").
