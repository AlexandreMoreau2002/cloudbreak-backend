# Security — cloudbreak-backend

Document de référence sécurité. À mettre à jour à chaque story qui touche auth, réseau, données ou dépendances.

---

## État actuel (story 1-2 — squelette)

### Ports exposés

| Port | Service | Exposé où | Risque |
|------|---------|-----------|--------|
| 8001 | FastAPI (dev) | localhost uniquement | ✅ Aucun |
| 5432 | PostgreSQL | localhost uniquement | ✅ Aucun |
| 6379 | Redis | localhost uniquement | ✅ Aucun |

> En prod : seul Caddy expose les ports 80/443. L'API, PostgreSQL et Redis ne sont **jamais** exposés directement à internet — ils communiquent via le réseau Docker interne.

---

## Secrets & variables d'environnement

- Les secrets sont dans `.env` — **jamais commité** (dans `.gitignore`)
- `.env.example` fourni sans valeurs sensibles — commité comme template
- En prod : variables injectées via Docker Compose, stockées sur le VPS uniquement
- **À ne jamais faire** : hardcoder une clé dans le code, même en dev

### Secrets à rotation régulière

| Secret | Fréquence rotation recommandée |
|--------|-------------------------------|
| `WEATHER_API_KEY` | Si leak détecté |
| `SUPABASE_KEY` | Si leak détecté |
| `POSTHOG_API_KEY` | Si leak détecté |
| Clé SSH VPS | Tous les 12 mois |

---

## Authentification

**État actuel** : pas encore implémentée (epic 2).

**Cible** :
- JWT Supabase validé **localement** côté backend via clé publique
- Zéro appel réseau Supabase par requête (pas de roundtrip auth à chaque call)
- Dependency FastAPI `get_current_user` injectée sur chaque route protégée
- `/health` est la seule route publique sans auth

---

## Transport & chiffrement

| Contexte | Statut |
|----------|--------|
| Dev local | HTTP (localhost) — acceptable |
| Prod | HTTPS TLS automatique via Caddy + Let's Encrypt |
| DB → API | Réseau Docker interne (non chiffré mais isolé) |
| Redis → API | Réseau Docker interne (non chiffré mais isolé) |

---

## Données utilisateur & RGPD

- Hébergement Supabase région **EU (Frankfurt)** — pas de transfert hors UE
- Endpoint `DELETE /api/v1/user` prévu dès le MVP (droit à l'effacement)
- Géolocalisation : consentement explicite requis, refus sans blocage de l'app
- Paiements : StoreKit 2 uniquement — **aucun numéro de carte stocké côté backend**

---

## Dépendances

### Audit des dépendances

```bash
# Vérifier les vulnérabilités connues
pip-audit  # à installer : pip install pip-audit
```

À lancer avant chaque release. Les dépendances actuelles (story 1-2) :

| Package | Version | Notes |
|---------|---------|-------|
| fastapi | 0.115.0 | Stable |
| sqlalchemy | 2.0.36 | Stable |
| pydantic | 2.10.0 | Stable |
| python-jose | 3.3.0 | Pour JWT — surveiller les CVE |
| asyncpg | 0.30.0 | Stable |

---

## Surface d'attaque actuelle

### Ce qui existe
- `GET /health` — endpoint public, pas de donnée sensible, pas de risque

### Ce qui n'existe pas encore
- Pas de rate limiting (à implémenter epic 3 ou avant prod)
- Pas de validation JWT (epic 2)
- Pas de quota enforcement (epic 4)

---

## Checklist avant mise en prod

- [ ] Variables `.env` renseignées sur le VPS (jamais en clair dans le code)
- [ ] PostgreSQL et Redis non exposés (ports non mappés dans `docker-compose.yml` prod)
- [ ] Caddy HTTPS opérationnel (Let's Encrypt)
- [ ] Rate limiting activé sur les endpoints publics
- [ ] JWT validation opérationnelle sur toutes les routes protégées
- [ ] `DEBUG=False` / `ENVIRONMENT=production`
- [ ] Logs ne contiennent aucun secret ou donnée personnelle
- [ ] `pip-audit` passé sans vulnérabilité critique
- [ ] Accès SSH VPS par clé uniquement (password auth désactivé)
- [ ] Firewall VPS : seuls ports 22, 80, 443 ouverts
