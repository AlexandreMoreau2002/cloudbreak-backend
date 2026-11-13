# Trusted Proxy and Missing Client IP Fixups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the rate-limit IP trust-boundary bypass and reject anonymous score requests whose peer IP is unavailable.

**Architecture:** Dokploy routes the backend only through Traefik on the Docker Swarm overlay
`dokploy-network` (`10.0.1.0/24`), verified read-only on the VPS on 2026-09-29. Uvicorn will
therefore process forwarded headers only from that CIDR. The quota dependency will stop before Redis
when Starlette provides no peer address, returning the established direct API error contract.

**Tech Stack:** Docker, Uvicorn, FastAPI, pytest, Redis mocks.

**Spec:** `docs/superpowers/specs/2026-09-28-quota-invite-rate-limit-design.md`

## Global Constraints

- Work only on the existing `feature/quota-invite-rate-limit` backend branch and PR #20.
- Do not change mobile or existing quota mechanics.
- Keep the API error body direct: `{"detail": "...", "code": "..."}`.
- Do not use `--forwarded-allow-ips=*`; trust only `10.0.1.0/24`.
- Do not merge the PR.

## Review Focus

- A public peer cannot inject `X-Forwarded-For`, because it is outside the Uvicorn trusted CIDR.
- A legitimate Traefik peer in `10.0.1.0/24` still provides its forwarded client IP.
- `request.client is None` returns a deterministic error without rate-limit or quota Redis access.
- Existing anonymous requests with a peer IP keep their rate-limit and quota order.
- The HTTP guide documents the new observable missing-IP rejection.

### Task 1: Restrict forwarded-header trust in the production image

**Files:**
- Modify: `Dockerfile:12`
- Modify: `docs/security.md:432-484`

**Interfaces:**
- Consumes: Dokploy Traefik overlay `dokploy-network` with subnet `10.0.1.0/24`.
- Produces: Uvicorn accepts `X-Forwarded-For` only when the immediate peer belongs to that subnet.

- [ ] **Step 1: Record the verified deployment facts in the security audit**

Document that VPS inspection found: only `dokploy-traefik` publishes ports 80/443, backend service
`app-reboot-primary-circuit-vmgb6t` has no published port, and the dynamic Traefik service forwards
to port 8000 on `dokploy-network` (`10.0.1.0/24`). Mark the wildcard warning resolved with a
deployment caveat: re-check the CIDR whenever Dokploy recreates this overlay network.

- [ ] **Step 2: Replace the wildcard in the Uvicorn command**

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=10.0.1.0/24"]
```

- [ ] **Step 3: Verify the image configuration is exact**

Run: `rg -n -- '--forwarded-allow-ips|dokploy-network|10\.0\.1\.0/24' Dockerfile docs/security.md`

Expected: no wildcard; Dockerfile and audit cite `10.0.1.0/24`.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docs/security.md
git commit -m "fix(proxy): restrict trusted forwarded peers"
```

### Task 2: Reject anonymous requests without a peer IP

**Files:**
- Modify: `app/core/dependencies.py:190-211`
- Modify: `app/core/errors.py`
- Modify: `tests/test_dependencies.py`
- Modify: `http/score-quota.http`

**Interfaces:**
- Consumes: `Request.client: Address | None` and `ApiError(status_code, detail, code)`.
- Produces: `CLIENT_IP_UNAVAILABLE` as a direct `503` response before `RateLimitService` or
  `QuotaService` is called.

- [ ] **Step 1: Write the failing unit test**

Use an anonymous user with valid installation UUID, `request.client = None`, and mocked Redis.
Assert `ApiError.status_code == 503`, `ApiError.code == "CLIENT_IP_UNAVAILABLE"`, and that
`redis.eval` was not awaited.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `.venv/bin/pytest tests/test_dependencies.py -k client_ip_unavailable -q`

Expected: FAIL because the current implementation falls back to the shared `"unknown"` bucket.

- [ ] **Step 3: Add the error code and minimal guard**

```python
if request.client is None:
    raise ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Adresse IP client indisponible",
        ErrorCode.CLIENT_IP_UNAVAILABLE,
    )
client_ip = request.client.host
```

- [ ] **Step 4: Add an HTTP-client note**

Add a non-executable limitation case explaining that REST Client normally supplies a peer address;
the `503 CLIENT_IP_UNAVAILABLE` branch is covered by the automated ASGI test.

- [ ] **Step 5: Run focused and complete validation**

Run: `source .venv/bin/activate && make validate`

Expected: Ruff, formatting, mypy, and all pytest tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/core/dependencies.py app/core/errors.py tests/test_dependencies.py http/score-quota.http
git commit -m "fix(quota): reject anonymous requests without client ip"
```

### Task 3: Final security review and update the existing PR

**Files:**
- Review: final diff of PR #20 only

- [ ] **Step 1: Run the `cloudbreak-security` review**

Review the final Dockerfile, IP guard, test, and security documentation. Confirm the trusted CIDR
matches the read-only VPS evidence and that the new `503` cannot consume Redis quota.

- [ ] **Step 2: Push the existing branch**

Run: `git push origin feature/quota-invite-rate-limit`

Expected: PR #20 updates; no new PR and no merge.

## Self-Review

- Scope is limited to the two reported issues: proxy trust boundary and unavailable peer IP.
- The verified CIDR, direct error body, test behavior, HTTP note, security audit, validation, and
  final security review each have an owning step.
- No placeholder or unverified network value is present.
