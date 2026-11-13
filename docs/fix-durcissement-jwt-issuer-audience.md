# Fix — Durcissement JWT : vérification issuer/audience

## Ce qui a été fait

`decode_supabase_jwt()` (`app/core/security.py`) ne vérifiait ni `aud` (audience) ni `iss`
(issuer) du JWT Supabase — seule la signature ECC P-256 était validée. Un token valide émis
pour un autre contexte (autre projet Supabase partageant la même paire de clés, scénario
improbable mais pas structurellement empêché) aurait été accepté.

## Pourquoi

Défense en profondeur : la vérification de signature seule ne garantit pas que le token a
été émis pour CE projet Supabase précis. `aud`/`iss` sont les mécanismes standards JWT pour
ça.

## Comment ça fonctionne

- `decode_supabase_jwt(token, jwks_json, supabase_url)` — nouveau paramètre `supabase_url`
- `jwt.decode(..., audience="authenticated", options={"require_aud": True})` — `"authenticated"`
  est la valeur `aud` standard émise par Supabase Auth pour toute session (y compris anonyme).
  `require_aud` est nécessaire : sans lui, python-jose ne rejette pas un token sans claim `aud`
  du tout, il ne le valide que si le claim est présent.
- Après décodage réussi, vérification manuelle `payload.get("iss") == f"{supabase_url.rstrip('/')}/auth/v1"`
  — lève `ValueError` (même famille d'erreur que les autres rejets du module) sinon.
- `app/core/dependencies.py:53` passe `settings.supabase_url` à l'appel.
- Logs debug (`logger.debug`, silencieux en prod) : `jwt_decode_ok` après succès, avec `sub`
  et `iss` ; `jwt_issuer_mismatch` en cas de rejet, avec l'issuer attendu et l'issuer reçu.
- `supabase_url.rstrip('/')` avant de construire l'issuer attendu : tolère une valeur de
  config avec ou sans slash final sans casser la comparaison.

## Comment tester

```bash
cd backend && source .venv/bin/activate
pytest tests/test_security.py -v
make validate
```

Cas couverts : token valide (aud/iss corrects), aud incorrect, iss incorrect, iss absent,
aud absent, supabase_url avec trailing slash.

## Fichiers impactés

- `app/core/security.py` — logique de vérification
- `app/core/dependencies.py` — passage du paramètre
- `tests/test_security.py` — couverture des cas de rejet
