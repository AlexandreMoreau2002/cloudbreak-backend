# Story 3.5 — Contrat score de présentation

_Complétée le 2026-03-24 — mis à jour le 2026-03-28 (refacto i18n)_

---

## Ce qui a été ajouté au backend

L’endpoint [`GET /api/v1/score`](/Users/alex/Desktop/dev/cloudbreak/backend/app/api/v1/endpoints/score.py) expose maintenant en plus du score brut :

- `label_code` — code i18n stable pour le libellé du verdict (ex: `"score.label.high"`)
- `context_code` — code i18n stable pour le message contextuel (ex: `"score.context.high.inversion"`)
- `context_params` — paramètres de substitution pour le message (ex: `{"peak": "Mont Blanc"}`)
- `optimal_window_start`
- `optimal_window_end`
- `sunrise`
- `stability_hours`
- `conditions` enrichi avec valeurs affichables
- `cloud_layer_viz`
- `peak_region` pour afficher le contexte géographique du sommet

Les réponses [`GET /api/v1/peaks/search`](/Users/alex/Desktop/dev/cloudbreak/backend/app/api/v1/endpoints/peaks.py),
[`GET /api/v1/peaks/{slug}`](/Users/alex/Desktop/dev/cloudbreak/backend/app/api/v1/endpoints/peaks.py)
et les favoris embarquent aussi maintenant `region` dans les objets peak.

Les schémas Pydantic ont été étendus dans [`score.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/schemas/score.py).

**Le backend ne traduit pas.** Il renvoie des codes i18n stables. La traduction est entièrement gérée côté mobile via `i18n-js` (voir `normalizeScoreResponse()` dans `src/services/mockData/score.ts`).

La logique de présentation a été ajoutée dans [`score.py`](/Users/alex/Desktop/dev/cloudbreak/backend/app/domain/score.py) :

- code libellé verdict (`label_code`)
- code message contextuel (`context_code`) + paramètres (`context_params`)
- estimation stabilité
- estimation lever du soleil
- construction de la fenêtre optimale
- payload de visualisation verticale

### Règle produit à connaître

Le backend ne retourne pas toujours un score "faible mais calculé". Il existe un court-circuit produit avant le calcul complet :

- si `cloud_cover_low < 45%`, la couche basse est jugée trop fragmentée
- le backend retourne directement `verdict = "none"` et `score = 0`
- le message contextuel doit être interprété comme une explication d'absence de scénario, pas comme une simple dégradation de probabilité

Autrement dit :

- `none` peut signifier "pas assez de nuages bas pour parler de mer de nuage"
- `low` signifie "une couche existe, mais les autres conditions restent trop marginales"

Cette distinction est volontaire et doit rester stable dans les contrats backend/mobile.

En complément :

- un verdict `high` n'est plus autorisé sous `55%` de `cloud_cover_low`
- entre `45%` et `54%`, on accepte encore un score si une couche basse crédible existe, mais pas un état franchement favorable

---

## Refactorisation i18n (2026-03-28)

Voir [`docs/story-refacto-i18n-score.md`](/Users/alex/Desktop/dev/cloudbreak/backend/docs/story-refacto-i18n-score.md) pour le détail complet.

**Ce qui a changé :**
- `app/domain/score_i18n.py` supprimé (contenait les traductions FR/EN)
- Champs `label` et `context_message` supprimés du `ScoreResponse`
- Plus de détection `Accept-Language` dans l’endpoint
- `get_score_label_code()` inliné dans `app/domain/score.py`

---

## Validation

- `pytest tests/test_score.py tests/test_api_score.py` passe
- `make validate` passe

## Acceptance Criteria vérifiés

- [x] le backend retourne des codes stables (`label_code`, `context_code`, `context_params`) et non du texte traduit
- [x] la réponse score inclut les champs de présentation 3.5 (`optimal_window_*`, `sunrise`, `stability_hours`, `cloud_layer_viz`, `peak_region`)
- [x] les objets peak exposés par les endpoints recherche/détail/favoris incluent `region`
- [x] la distinction produit `none` vs `low` reste stable avec le hard gate `cloud_cover_low < 45%`
- [x] un verdict `high` n'est pas autorisé sous `55%` de `cloud_cover_low`

---

## Notes

- la stabilité et la fenêtre optimale sont pour l’instant des heuristiques déterministes dérivées du score et des conditions
- ce contrat est suffisant pour la `3.5` mobile, sans introduire une dépendance supplémentaire côté backend
