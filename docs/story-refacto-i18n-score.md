# Refactorisation — i18n score déplacé côté mobile

_Complétée le 2026-03-28_

---

## Ce qui a été fait

| Fichier | Changement |
|---------|-----------|
| `app/domain/score_i18n.py` | Supprimé — contenait les traductions FR/EN (`get_score_label()`, `get_score_context_message()`) |
| `app/domain/score.py` | Produit `label_code` et délègue le choix du contexte au domain layer sans traduire |
| `app/domain/score_context.py` | Génère `context_code` et `context_params` côté backend |
| `app/schemas/score.py` | Champs `label` (str) et `context_message` (str) supprimés du `ScoreResponse` |
| `app/api/v1/endpoints/score.py` | Suppression de la détection `Accept-Language` et des appels de traduction |

---

## Pourquoi

**Principe** : le backend gère les données, le front gère le texte.

Avant cette refacto, le backend :
1. Détectait la langue via l'en-tête HTTP `Accept-Language`
2. Appelait des fonctions de traduction en Python
3. Renvoyait `label` et `context_message` en langue naturelle

Ce design posait plusieurs problèmes :
- Ajouter une langue = modifier le backend et redéployer
- Impossible de changer un libellé sans déploiement serveur
- La logique de présentation (texte à afficher) appartient au front, pas au back
- Le backend testait des chaînes localisées fragiles aux reformulations

Après cette refacto, le backend renvoie uniquement des **codes stables** :
- `label_code` — code i18n pour le libellé du verdict
- `context_code` — code i18n pour le message contextuel
- `context_params` — paramètres de substitution (ex: `{"peak": "Mont Blanc"}`)

Le mobile traduit avec `i18n-js` en utilisant les fichiers `src/locales/fr.ts` et `src/locales/en.ts`.

---

## Comment ça fonctionne maintenant — flux complet

```
GET /api/v1/score
  → { score, verdict, label_code, context_code, context_params, ... }

fetchScore() dans src/services/api/score.ts
  → appelle l'API
  → passe la réponse à normalizeScoreResponse()

normalizeScoreResponse() dans src/services/mockData/score.ts
  → label = i18n.t(label_code)
  → context_message = i18n.t(context_code, context_params)
  → retourne { score, verdict, label, context_message, ... }

useScore / useWeekData
  → consomment la réponse normalisée

ScoreCard(contextMessage)
  → affiche le texte traduit
```

Les clés i18n sont sous les espaces de noms `score.label.*` et `score.context.*.*`
dans `src/locales/fr.ts` et `src/locales/en.ts`.

---

## Comment tester

**Vérifier que l'API retourne des codes, pas du texte :**

```bash
# Lancer le backend
make dev

# Appeler l'endpoint score (remplacer le token et le peak_id)
curl -s -H "Authorization: Bearer <jwt>" \
  "http://localhost:8000/api/v1/score?peak_id=<id>&date=<date>&hour=6" | jq '{label_code, context_code, context_params}'
```

Résultat attendu — des codes, pas de texte :
```json
{
  "label_code": "score.label.high",
  "context_code": "score.context.high.inversion",
  "context_params": { "peak": "Crêt de la Neige" }
}
```

Résultat incorrect (ancien comportement) :
```json
{
  "label": "Très probable",
  "context_message": "Inversion thermique marquée sur Crêt de la Neige."
}
```

**Vérifier que les champs `label` et `context_message` n'existent plus dans la réponse API :**

```bash
curl -s -H "Authorization: Bearer <jwt>" \
  "http://localhost:8000/api/v1/score?peak_id=<id>&date=<date>&hour=6" | jq 'has("label"), has("context_message")'
# Doit retourner : false, false
```

**Vérifier l'en-tête `Accept-Language` est ignoré :**

```bash
curl -s -H "Authorization: Bearer <jwt>" \
     -H "Accept-Language: en" \
  "http://localhost:8000/api/v1/score?peak_id=<id>&date=<date>&hour=6" | jq '{label_code, context_code}'
# Même codes qu'en fr — l'en-tête n'a aucun effet
```

**Vérifier la traduction côté mobile :**

Dans le simulateur, sélectionner un sommet et observer que la `ScoreCard` affiche un texte en langue naturelle (ex: "Très probable") et non un code i18n brut.

**Tests automatiques backend :**

```bash
make validate
```

## Acceptance Criteria vérifiés

- [x] l'API score ne dépend plus de `Accept-Language`
- [x] les champs texte traduits (`label`, `context_message`) ne sortent plus du backend
- [x] le backend retourne uniquement des codes et paramètres stables consommables par le mobile
- [x] la logique métier du score reste testable sans assertions sur des chaînes localisées
