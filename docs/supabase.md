# Architecture Auth — Délégation à Supabase

## Pourquoi déléguer l'authentification à Supabase ?

### Ce qu'on aurait dû implémenter sans Supabase

Gérer l'auth soi-même sur un MVP solo, c'est implémenter correctement :

- Hashage des mots de passe (bcrypt / argon2)
- Génération et rotation des JWT (access token + refresh token)
- Gestion des sessions et de leur expiration
- "Mot de passe oublié" (email transactionnel)
- Protection brute-force sur `/login` (rate limiting)
- Confirmation d'email à l'inscription
- OAuth tiers (Google, Apple Sign-In) si besoin plus tard

C'est des semaines de travail, et c'est le genre de code où une erreur = faille de sécurité. Supabase couvre tout ça correctement, gratuitement, et de façon maintenue.

**Verdict pour un solo dev sur un MVP iOS : déléguer est le bon choix.** La seule vraie contrainte est la dépendance à un service tiers — si Supabase ferme ou devient prohibitif, il faudra migrer. Risque acceptable au stade actuel.

---

## Séparation des responsabilités

L'architecture repose sur une séparation nette entre deux systèmes :

```
Supabase                              Backend PostgreSQL
──────────────────────────            ──────────────────────────────
Table : auth.users                    Table : subscriptions
  - id (UUID)                           - user_id  (= UUID Supabase)
  - email                               - plan ("freemium"|"premium"|"pro")
  - password_hash                       - expires_at
  - session tokens                      - status
  - refresh tokens

→ "Qui es-tu ?"                       → "Qu'as-tu le droit de faire ?"
```

**Supabase est le videur** — il vérifie l'identité et émet un JWT signé.

**PostgreSQL est le registre des abonnés** — il stocke ce que l'utilisateur a le droit de faire, en fonction de ce qu'il a payé.

Les deux ne se parlent pas directement. Le `user_id` (UUID Supabase) fait le lien : il est embarqué dans le JWT et utilisé comme clé étrangère dans toutes les tables métier.

---

## Flux complet d'une requête authentifiée

```
Mobile (iOS)               Backend FastAPI              PostgreSQL
     │                          │                           │
     │  POST /auth/signin        │                           │
     │  ──────────────────────▶  │ (géré par Supabase SDK)  │
     │  ◀── JWT (access_token) ──│                           │
     │                          │                           │
     │  GET /api/v1/score        │                           │
     │  Bearer: <jwt> ─────────▶│                           │
     │                          │ 1. decode_supabase_jwt()  │
     │                          │    vérifie signature JWKS │
     │                          │    → user_id = "ddce4acf" │
     │                          │                           │
     │                          │ 2. SELECT * FROM          │
     │                          │    subscriptions          │
     │                          │    WHERE user_id =        │
     │                          │    "ddce4acf" ───────────▶│
     │                          │    ◀── plan="premium" ────│
     │                          │                           │
     │                          │ 3. bypass quota Redis ✓   │
     │                          │    → calcul score...      │
     │  ◀── ScoreResponse ───── │                           │
```

### Étape 1 — Validation JWT locale (sans appel réseau)

Le backend ne contacte **jamais Supabase** pour valider un token. Il possède les clés publiques JWKS de Supabase (dans `.env` → `SUPABASE_JWT_JWKS`) et valide la signature localement.

```python
# app/core/security.py
payload = decode_supabase_jwt(token, settings.supabase_jwt_jwks)
# → lève ValueError si token invalide ou expiré
```

Avantage : zéro latence réseau sur chaque requête, zéro dépendance Supabase en runtime.

### Étape 2 — Résolution du plan (freemium / premium)

Supabase ne sait pas qu'un utilisateur est premium. Il sait juste que c'est lui. C'est le backend qui sait ce qu'il a payé, en lisant `subscriptions` dans PostgreSQL — table écrite par le backend lors de la validation StoreKit 2.

```python
# app/core/dependencies.py
subscription = await get_user_subscription(user_id, db)
if (
    subscription
    and subscription.plan in ("premium", "pro")
    and subscription.expires_at is not None
    and subscription.expires_at > datetime.now(subscription.expires_at.tzinfo)
):
    return user  # premium → bypass quota
```

---

## Pourquoi ne pas stocker le plan dans Supabase ?

On pourrait mettre `plan: "premium"` dans les `user_metadata` Supabase et l'embarquer dans le JWT. Ça éviterait le SELECT sur `subscriptions`. Mais :

| Raison | Explication |
|--------|-------------|
| **Sécurité** | Les `user_metadata` Supabase sont accessibles et modifiables côté client SDK — un utilisateur pourrait tenter de les altérer |
| **Source de vérité** | PostgreSQL est la source de vérité pour tout ce qui est business. Supabase est le portier d'entrée, pas le registre métier |
| **Flexibilité** | Si on change d'auth provider demain (Auth0, custom), le système de subscription ne bouge pas |
| **Auditabilité** | Les changements de plan sont tracés dans notre DB avec `expires_at`, `status`, timestamps — pas dans les metadata Supabase |

---

## Ce que Supabase fait vs ce que le backend fait

| Responsabilité | Supabase | Backend FastAPI |
|----------------|----------|-----------------|
| Inscription / connexion | ✓ | — |
| Hashage mot de passe | ✓ | — |
| Émission JWT | ✓ | — |
| Refresh token | ✓ | — |
| Confirmation email | ✓ | — |
| Validation JWT (signature) | — | ✓ (`security.py`) |
| Extraction `user_id` | — | ✓ (`dependencies.py`) |
| Plan freemium / premium | — | ✓ (`subscriptions`) |
| Quota Redis | — | ✓ (`quota.py`) |
| Données métier (peaks, scores) | — | ✓ |

---

## Fichiers clés

```
backend/
  app/core/security.py          # decode_supabase_jwt() — validation JWT locale
  app/core/dependencies.py      # get_current_user(), check_quota()
  app/models/subscription.py    # modèle SQLAlchemy table subscriptions

mobile/
  src/services/supabaseClient.ts  # initialisation SDK Supabase
  src/contexts/AuthContext.tsx    # signIn, signUp, signOut, session
```

---

## Variables d'environnement

```bash
# Backend .env
SUPABASE_JWT_JWKS={"keys":[...]}   # clés publiques pour valider les JWT localement

# Mobile .env
EXPO_PUBLIC_SUPABASE_URL=https://yggehvcwxiqrkhsoxrxe.supabase.co
EXPO_PUBLIC_SUPABASE_ANON_KEY=...  # clé publique — OK d'être exposée côté client
```

La `ANON_KEY` Supabase est conçue pour être publique (Row Level Security côté Supabase protège les données). Le secret réel (`service_role_key`) n'est **jamais** utilisé côté backend FastAPI — la validation JWT locale suffit.
