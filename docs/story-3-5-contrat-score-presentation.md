# Story 3.5 — Contrat score de présentation

_Complétée le 2026-03-24_

---

## Ce qui a été ajouté au backend

L'endpoint [`GET /api/v1/score`](/Users/alex/Desktop/dev/cloudbreak/backend/app/api/v1/endpoints/score.py) expose maintenant en plus du score brut :

- `label`
- `optimal_window_start`
- `optimal_window_end`
- `sunrise`
- `stability_hours`
- `conditions` enrichi avec valeurs affichables
- `cloud_layer_viz`

Les schémas Pydantic ont été étendus dans [`score.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/schemas/score.py).

La logique de présentation a été ajoutée dans [`score.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/domain/score.py) :

- libellé verdict
- estimation stabilité
- estimation lever du soleil
- construction de la fenêtre optimale
- payload de visualisation verticale

---

## Validation

- `pytest tests/test_score.py tests/test_api_score.py` passe
- `make validate` passe

---

## Notes

- la stabilité et la fenêtre optimale sont pour l’instant des heuristiques déterministes dérivées du score et des conditions
- ce contrat est suffisant pour la `3.5` mobile, sans introduire une dépendance supplémentaire côté backend
