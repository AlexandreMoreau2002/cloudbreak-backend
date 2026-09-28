# Quota invité — Installation ID et rate-limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empêcher qu’une session anonyme recréée réinitialise le quota freemium et ralentir les rafales invitées.

**Architecture:** Le mobile conserve un UUID v4 opaque dans le Keychain et `apiFetch` l’envoie dans un header. Pour les invités free, FastAPI limite l’IP dans Redis puis contrôle le même quota quotidien sur le hash de l’installation, avant le quota existant par `user_id`. Permanent free et Premium/Pro ne changent pas.

**Tech Stack:** Expo SDK 55, expo-secure-store, expo-crypto, TypeScript/Jest, FastAPI, Uvicorn, Redis asyncio, pytest/httpx.

**Spec:** `backend/docs/superpowers/specs/2026-09-28-quota-invite-rate-limit-design.md`

## Global Constraints

- Pas d’App Attest, DeviceCheck, fingerprint matériel, table SQL ou endpoint supplémentaire.
- Invité : `X-Cloudbreak-Installation-Id` UUID v4 obligatoire ; `400 INSTALLATION_ID_INVALID` sans quota consommé.
- Rate-limit invité score : 60 requêtes par IP/fenêtre fixe 60 s ; `429 RATE_LIMIT_EXCEEDED`.
- Clé : `quota:installation:{sha256(installation_id)}:{date}` ; pas d’UUID/IP brut en Redis ou logs.
- Le quota installation précède `user_id`; même sommet, toutes heures, reste déverrouillé.
- Premium/Pro bypassent ; permanent free garde le quota actuel et n’a pas besoin du header.
- Dockerfile production : `--proxy-headers --forwarded-allow-ips=*`; prod uniquement derrière Traefik interne, développement inchangé.
- Imports escalier, TDD, aucun `print()`. Ne modifier `TODO.md` et `sprint-status.yaml` qu’après les PRs en préservant le diff utilisateur actuel.

## Review Focus

- Header absent/vide, UUID non-v4 : erreur 400 sans clé Redis — Task 2.
- Même installation avec deux UUID invités : second sommet 429 sans consommer le nouveau quota user — Task 2.
- Vue semaine : appels 1-60/min acceptés, 61e rate-limit — Tasks 1-2.
- IP : `Request.client` normalisé par Uvicorn ; ne pas lire `X-Forwarded-For` — Task 2.
- SecureStore vide/valide/en erreur : créer, réutiliser, ou ne pas appeler `fetch` — Task 3.

---

## Structure

| Fichier | Rôle |
|---|---|
| `app/services/quota.py` | SET quotidien utilisateur et installation. |
| `app/services/rate_limit.py` | Compteur Redis IP isolé du quota métier. |
| `app/core/dependencies.py`, `errors.py`, `Dockerfile` | Validation, ordre, codes API, proxy production. |
| `tests/test_quota.py`, `test_rate_limit.py`, `test_dependencies.py`, `tests/features/test_quota_flow.py` | Tests unitaires, dependency et HTTP. |
| `mobile/src/services/installationId.ts`, `fetchService.ts` + tests | UUID Keychain et header centralisé. |
| `http/score-quota.http`, `docs/quota-invite-rate-limit/*`, `docs/security.md`, `docs/product-audit.md` | Tests manuels et documentation. |

### Task 0: Créer la checklist Notion avant le code

**Files:** créer la sous-page Notion de `Cloudbreak - mer de nuage` (`325964bd-a185-8035-8585-ff14ef1f76c6`) : `✅ Tests story 4.1 — Quota invité étage 1`.

- [ ] **Step 1: Vérifier branches et modifications étrangères**

Run: `rtk git -C backend status --short && rtk git -C mobile status --short && rtk git status --short`

Expected: branches `feature/quota-invite-rate-limit`; diff utilisateur `TODO.md` intact.

- [ ] **Step 2: Créer la checklist**

Ajouter impact mobile/backend, checkboxes `make validate`/ `npm run validate`, cas header absent/invalide, session recréée, 60/61 appels, Premium et tableau zone/tests/état. Conserver le lien.

### Task 1: Ajouter les primitives Redis

**Files:** modifier `backend/app/services/quota.py`, `backend/tests/test_quota.py`; créer `backend/app/services/rate_limit.py`, `backend/tests/test_rate_limit.py`.

**Interfaces:** produire `QuotaService.check_and_increment_installation(installation_hash: str, date: str, peak_id: str) -> None`, `RateLimitService.check_anonymous_score(client_ip: str) -> None`, `RateLimitExceededException`.

- [ ] **Step 1: Écrire les tests rouges**

```python
await QuotaService(mock_redis).check_and_increment_installation("a" * 64, "2026-09-28", "peak-1")
mock_redis._pipe.sadd.assert_called_once_with("quota:installation:" + "a" * 64 + ":2026-09-28", "peak-1")

mock_redis.incr.return_value = 61
with pytest.raises(RateLimitExceededException):
    await RateLimitService(mock_redis).check_anonymous_score("198.51.100.8")
```

- [ ] **Step 2: Vérifier l’échec**

Run: `pytest tests/test_quota.py tests/test_rate_limit.py -q`

Expected: FAIL, interfaces inexistantes.

- [ ] **Step 3: Implémenter le minimum**

```python
async def check_and_increment_installation(self, installation_hash: str, date: str, peak_id: str) -> None:
    await self._check_and_increment(f"quota:installation:{installation_hash}:{date}", peak_id)

async def check_anonymous_score(self, client_ip: str) -> None:
    key = f"rate_limit:anonymous_score:{sha256(client_ip.encode()).hexdigest()}:{current_window()}"
    count = await self._redis.incr(key)
    if count == 1:
        await self._redis.expire(key, 60)
    if count > 60:
        raise RateLimitExceededException()
```

Factoriser le SET/TTL jusqu’à minuit en gardant `check_and_increment(user_id, date, peak_id)` compatible.

- [ ] **Step 4: Couvrir et vérifier**

Ajouter même peak, installations distinctes, TTL minuit, TTL du premier INCR, 1-60 acceptés et clé sans IP brute. Run: `pytest tests/test_quota.py tests/test_rate_limit.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/quota.py app/services/rate_limit.py tests/test_quota.py tests/test_rate_limit.py
git commit -m "feat(quota): add installation and IP limits"
```

### Task 2: Protéger la dependency score

**Files:** modifier `backend/app/core/errors.py`, `backend/app/core/dependencies.py`, `backend/Dockerfile`, `backend/tests/test_dependencies.py`, `backend/tests/features/test_quota_flow.py`.

**Interfaces:** consommer Task 1 ; `check_quota()` retourne le contexte actuel ou une erreur API stable.

- [ ] **Step 1: Écrire les tests rouges**

```python
response = await client.get("/api/v1/score")
assert response.status_code == 400
assert response.json()["code"] == "INSTALLATION_ID_INVALID"

first = await score_for("guest-a", INSTALLATION_ID, "peak-1")
second = await score_for("guest-b", INSTALLATION_ID, "peak-2")
assert first.status_code == 200
assert second.json()["detail"]["code"] == "QUOTA_EXCEEDED"
```

- [ ] **Step 2: Vérifier l’échec**

Run: `pytest tests/test_dependencies.py tests/features/test_quota_flow.py -q`

Expected: FAIL, invité sans header encore autorisé.

- [ ] **Step 3: Implémenter validation, ordre et proxy**

```python
if user.get("is_anonymous") is True:
    installation_uuid = parse_uuid4_or_raise(request.headers.get("X-Cloudbreak-Installation-Id"))
    client_ip = request.client.host if request.client else "unknown"
    await RateLimitService(redis).check_anonymous_score(client_ip)
    await quota_service.check_and_increment_installation(
        sha256(str(installation_uuid).encode()).hexdigest(), today, peak_id
    )
await quota_service.check_and_increment(str(user_id), today, peak_id)
```

Ajouter les deux `ErrorCode`, mapper rate-limit vers 429, logger uniquement hash/plan/peak et modifier le seul Dockerfile production.

- [ ] **Step 4: Vérifier les non-régressions**

Tester header vide, UUID v1, 60/61 avec `ASGITransport(..., client=("198.51.100.8", 123))`, autre guest même installation, même peak/autre heure, permanent free sans header, Premium/Pro sans header. Run: `pytest tests/test_dependencies.py tests/features/test_quota_flow.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/errors.py app/core/dependencies.py Dockerfile tests/test_dependencies.py tests/features/test_quota_flow.py
git commit -m "feat(score): protect anonymous quota by installation"
```

### Task 3: Émettre l’identifiant Keychain mobile

**Files:** créer `mobile/src/services/installationId.ts`, `installationId.test.ts`; modifier `mobile/src/services/fetchService.ts`, `fetchService.test.ts`.

**Interfaces:** produire `getInstallationId(): Promise<string>`; `apiFetch` l’appelle uniquement avec un token.

- [ ] **Step 1: Écrire les tests rouges**

```typescript
await expect(getInstallationId()).resolves.toBe('550e8400-e29b-41d4-a716-446655440000')
expect(setItemAsync).not.toHaveBeenCalled()

await apiFetch('/api/v1/score', 'token-123')
expect(global.fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
  headers: expect.objectContaining({ 'X-Cloudbreak-Installation-Id': INSTALLATION_ID }),
}))
```

- [ ] **Step 2: Vérifier l’échec**

Run: `npm test -- installationId.test.ts fetchService.test.ts --runInBand`

Expected: FAIL, service/header absents.

- [ ] **Step 3: Implémenter sans fuite**

```typescript
const INSTALLATION_ID_KEY = 'cloudbreak.installation-id.v1'
export async function getInstallationId(): Promise<string> {
  const current = await SecureStore.getItemAsync(INSTALLATION_ID_KEY)
  if (current && UUID_V4_PATTERN.test(current)) return current
  const created = Crypto.randomUUID()
  await SecureStore.setItemAsync(INSTALLATION_ID_KEY, created)
  return created
}
```

Ajouter le header avant `fetch`, jamais dans `console.debug`, et ne changer aucune requête sans token.

- [ ] **Step 4: Couvrir et vérifier**

Tester Keychain vide, valeur invalide remplacée, rejet SecureStore/Crypto avant `fetch`, token null sans header, conservation Authorization/Content-Type. Run: `npm test -- installationId.test.ts fetchService.test.ts --runInBand`. Expected: PASS.

- [ ] **Step 5: Commit mobile**

```bash
git add src/services/installationId.ts src/services/installationId.test.ts src/services/fetchService.ts src/services/fetchService.test.ts
git commit -m "feat(api): send stable installation identifier"
```

### Task 4: Documenter et tester manuellement

**Files:** modifier `backend/http/score-quota.http`, `backend/docs/security.md`, `backend/docs/product-audit.md`; créer `backend/docs/quota-invite-rate-limit/fonctionnement.md`, `guide-test.md`.

- [ ] **Step 1: Étendre le fichier HTTP**

Ajouter `@installationId` et `@otherInstallationId` : invité valide 200; même installation/nouveau JWT/nouveau peak 429 quota; absent/invalide 400; 61e 429 rate-limit; date invalide 422; Premium/Pro 200 sans header.

- [ ] **Step 2: Écrire les livrables**

`fonctionnement.md` explique simplement le flux avec schéma ASCII/fichiers. `guide-test.md` contient prérequis, pas-à-pas, limites/checklist et reset Redis ciblé (pas de `FLUSHDB` partagé).

- [ ] **Step 3: Mettre à jour sécurité/audit et vérifier**

Dans `security.md`, marquer P0 mitigée, limites (client modifié/IP) et App Attest futur; dans audit, comportement livré. Run: `rg -n 'INSTALLATION_ID_INVALID|RATE_LIMIT_EXCEEDED|quota:installation' http/score-quota.http docs/quota-invite-rate-limit docs/security.md`. Expected: scénarios/codes présents.

- [ ] **Step 4: Commit**

```bash
git add http/score-quota.http docs/quota-invite-rate-limit docs/security.md docs/product-audit.md
git commit -m "docs(quota): add guest abuse test guide"
```

### Task 5: Valider, revoir et ouvrir les PRs sans merge

**Files:** vérifier backend/mobile; modifier après PR `TODO.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml`.

- [ ] **Step 1: Lancer les validations complètes**

Run: `source .venv/bin/activate && make validate` dans backend, puis `npm run validate` dans mobile.

Expected: Ruff, mypy, pytest, TypeScript, ESLint, Jest et export iOS verts.

- [ ] **Step 2: Faire les revues obligatoires**

Lancer `stairs-import-fixer`, `cloudbreak-dev-reviewer`, `cloudbreak-security`; corriger les constats fondés et relancer les validations. L’audit traite confidentialité UUID, proxy, contournements et erreurs.

- [ ] **Step 3: Pousser et ouvrir les deux PRs vers develop**

Vérifier `git log --format='%B' develop..HEAD` dans chaque submodule, pousser les branches, ouvrir les PRs avec contexte P0/tests/limites/lien Notion. Ne jamais lancer `gh pr merge`.

- [ ] **Step 4: Mettre à jour le suivi après PR**

Mettre TODO point 2 « en review » avec liens sans écraser son diff; ajouter exactement `4-1a-quota-invite-rate-limit-installation: review` sous Epic 4 dans sprint-status; commit racine séparé sans `Co-Authored-By`.
