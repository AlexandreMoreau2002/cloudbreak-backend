# Testing Guide — Cloudbreak Backend

✅ **Approche** : **Vrais UUIDs Supabase en DB** + **vrais JWTs Supabase** pour les tests.

---

## 🎯 Vue d'ensemble

Tester le quota freemium avec des comptes prédéfinis en base de données.

**Workflow rapide:**
```bash
make dev              # Lancer Docker (API + DB + Redis)
make migrate          # Appliquer migrations
make seed             # Insérer les sommets
make seed-test        # Insérer les users de test ← c'est là!
# Tester avec REST Client ou pytest
```

---

## 📋 Comptes de test (en DB)

Créés automatiquement par `make seed-test` :

| Email | Plan | Accès | UUID Supabase |
|-------|------|-------|-----------------|
| **freemium@cloudbreak.app** | free | 1 check/jour | `ddce4acf-4588-4916-bb8e-8e47de082e7b` |
| **pro@cloudbreak.app** | pro | illimité | `d19f15c6-ab8c-4eee-89a2-cc3c2342a3a5` |
| **test@cloudbreak.app** | pro | illimité | `6f12c6e6-5478-4301-8494-83ab039c53aa` |

---

## 🔐 Authentification — JWT Supabase réel

**Tous les appels API exigent un JWT Supabase valide** (en dev et en prod).

### Récupérer les JWTs (REST Client)

```bash
# Ouvrir le fichier de test d'auth
code docs/user_plan.http

# Exécuter les 3 requests pour récupérer les JWTs depuis Supabase
# Les JWTs sont stockés dans les variables REST Client
```

Les 3 requests font un POST à Supabase auth API avec les credentials (email + password).

### Utiliser les JWTs dans REST Client

Les JWTs générés par `user_plan.http` sont disponibles dans les variables :
- `jwtFreemium`
- `jwtPro`
- `jwtTest`

Utiliser dans `docs/score_plan.http` :
```http
Authorization: Bearer {{jwtFreemium}}
```

### Tests pytest

Les tests utilisent `app.dependency_overrides[get_current_user]` pour mocker l'authentification. Pas besoin de JWT réel.

```bash
pytest tests/features/test_quota_flow.py -v
```

---

## 🧪 Tester avec REST Client (VS Code)

### Installer l'extension

```
VS Code → Extensions → "REST Client" by Huachao Mao
```

### Ouvrir le fichier de test

```bash
code docs/score_plan.http
```

### Utiliser le header de dev

Dans le fichier, utiliser le header `X-Dev-User-ID` avec l'UUID réel du user Supabase :

```http
# ✅ Correct (en dev, avec SKIP_JWT_VALIDATION=true)
X-Dev-User-ID: ddce4acf-4588-4916-bb8e-8e47de082e7b

# ❌ Pas besoin de Authorization header en dev
```

**Les 3 UUIDs à utiliser :**
- Freemium : `ddce4acf-4588-4916-bb8e-8e47de082e7b`
- Pro : `d19f15c6-ab8c-4eee-89a2-cc3c2342a3a5`
- Test : `6f12c6e6-5478-4301-8494-83ab039c53aa`

### Cliquer "Send Request"

REST Client exécute automatiquement les tests définis en bas de chaque bloc.

---

## 🧪 Tester avec pytest (automatisé)

### Tous les tests

```bash
make test   # Ou : pytest --cov=app
```

### Juste les tests quota

```bash
pytest tests/features/test_quota_flow.py -v
```

### Avec un user spécifique

```bash
# Les fixtures utilisent les users de test en DB automatiquement
pytest tests/features/test_quota_flow.py::test_quota_score_endpoint_first_call_returns_200 -v
```

---

## 🔍 Inspecter les données

### Redis — Clés quota

```bash
# Voir les clés quota actuelles
docker exec cloudbreak-redis redis-cli KEYS "quota:*"

# Voir le compteur d'un user
docker exec cloudbreak-redis redis-cli GET quota:user-freemium-001:2026-04-01

# Voir le TTL (temps avant expiration)
docker exec cloudbreak-redis redis-cli TTL quota:user-freemium-001:2026-04-01

# Vider le quota (pour retester)
docker exec cloudbreak-redis redis-cli DEL quota:user-freemium-001:2026-04-01
```

### PostgreSQL — Subscriptions

```bash
# Voir les users de test en DB
docker exec cloudbreak-postgres psql -U postgres -d cloudbreak -c \
  "SELECT user_id, plan, expires_at FROM subscriptions;"

# Supprimer un user
docker exec cloudbreak-postgres psql -U postgres -d cloudbreak -c \
  "DELETE FROM subscriptions WHERE user_id = 'user-freemium-001';"
```

---

## 🔄 Gérer les données de test

### Insérer les users de test

```bash
make seed-test
```

Output:
```
seed_test_user user_id=user-freemium-001 email=freemium@cloudbreak.fr plan=free
seed_test_user user_id=user-pro-001 email=pro@cloudbreak.fr plan=pro
seed_test_user user_id=user-admin-001 email=admin@cloudbreak.fr plan=pro
seed_test_users_completed count=3
```

### Supprimer les users de test

```bash
make unseed-test
```

### Reset complète (danger ⚠️)

```bash
# Supprime TOUTES les tables, les recréé, re-seed les peaks
make reset-db
```

---

## 🚀 Workflow complet — local

```bash
# Terminal 1: Infra
cd backend
make dev              # Docker up
make migrate          # Migrations
make seed             # Peaks data
make seed-test        # Users test (🔑 important!)

# Terminal 2: Logs
make logs

# Terminal 3: Tests
# Ouvrir VS Code
code docs/score_plan.http
# Modifier les tokens, cliquer "Send Request"

# Ou run pytest
pytest tests/features/test_quota_flow.py -v
```

Arrêter:
```bash
make unseed-test      # Optionnel : supprimer les users
make down             # Docker down
```

---

## 📊 Acceptance Criteria vérifiés

| AC | Test | Commande |
|----|------|----------|
| AC1 | Freemium 1er check → 200 OK | REST Client : `AC1: Freemium user — 1er check` |
| AC2 | Freemium 2e check → 429 | REST Client : `AC2: Freemium user — 2e check` |
| AC3 | Premium/Pro → illimité | REST Client : `AC3: Premium user` |
| AC4 | Jour suivant → reset | REST Client : `AC4: Freemium reset` |

Ou pytest :
```bash
pytest tests/features/test_quota_flow.py -v
```

---

## ❓ FAQ

**Q: Comment je connais les vrais user_ids Supabase?**
A: Les `user-*-001` sont fictifs mais en base de données. Pour Supabase réel, utiliser les UUIDs que Supabase génère (récupérables via console).

**Q: Je dois créer des users dans Supabase?**
A: Non. En dev, les user_ids fictifs suffisent. La validation JWT se fait avec une clé Supabase réelle (stockée en `SUPABASE_JWT_JWKS`), mais les user_ids peuvent être n'importe quoi.

**Q: Les données de test persistent après `make down`?**
A: Non, Docker supprime les volumes. Relancer `make dev && make seed-test` pour recréer.

**Q: Comment tester avec Supabase réel (production)?**
A: Voir `.env` → `SUPABASE_URL` et `SUPABASE_KEY`. En dev local, utiliser des tokens test générés localement.

**Q: Je veux ajouter un nouveau user de test?**
A: Éditer `app/db/seed_test_users.py` → ajouter à `TEST_USERS` dict → `make unseed-test && make seed-test`.

---

## 📚 Fichiers clés

- `docs/score_plan.http` — Tests REST Client (AC1-4)
- `tests/features/test_quota_flow.py` — Tests pytest (AC1-4)
- `app/db/seed_test_users.py` — Créer/supprimer users de test
- `app/models/subscription.py` — Modèle DB (minimal en 4.1)
- `Makefile` — Commandes `seed-test`, `unseed-test`, `reset-db`
