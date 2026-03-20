# CLAUDE.md — Backend

Règles spécifiques au sous-repo `cloudbreak-backend`.
Les règles globales (architecture, git flow, modèle de données) sont dans le `CLAUDE.md` racine.

---

## Commandes

```bash
source .venv/bin/activate   # toujours activer le venv avant make

make help        # affiche toutes les commandes
make dev         # lance api + db + redis (Docker, hot reload)
make down        # arrête les containers
make logs        # suit les logs en temps réel
make validate    # ruff + mypy + pytest --cov — obligatoire avant commit
make migrate     # applique les migrations Alembic
make migration   # génère une nouvelle migration
make seed        # insère les données initiales
make test        # pytest avec coverage
make lint        # ruff check
make format      # ruff format
make typecheck   # mypy
```

> Ne jamais lancer `uvicorn` directement — passer par `make dev` (Docker).
> `make migration` et `make seed` nécessitent le venv activé.

---

## Règles de code

**Ne jamais faire :**
- `print()` — utiliser `logger.info/debug/error` uniquement
- SQL brut — uniquement SQLAlchemy ORM
- Secrets dans le code — uniquement via variables d'environnement
- Réponse avec wrapper `{"status": "ok", "data": ...}` — réponses directes

**Toujours faire :**
- Imports en escalier (longueur croissante, externes puis internes)
- Erreurs API : `{"detail": "...", "code": "ERROR_CODE"}`
- Clés Redis préfixées : `weather:*`, `quota:*`, `cache:*`
- Logs JSON structurés : `logger.info("event", extra={...})`
- Dates ISO 8601 UTC

---

## Mode debug

Logs debug placés aux points clés — silencieux en prod, activables à la demande :

```python
logger.debug("score_detail", extra={"cloud_base": cb, "peak_alt": alt, "score": s})
logger.debug("cache_result", extra={"key": key, "hit": hit})
logger.debug("open_meteo_raw", extra={"status": r.status_code, "data": data})
```

Activer en dev :
```bash
# Dans docker-compose.dev.yml > environment :
LOG_LEVEL=DEBUG
```

---

## Tests — règles

- **100% coverage obligatoire** — tout nouveau fichier source a son `test_*.py`
- 1 fichier de test par fichier source dans `tests/`
- Tests de feature dans `tests/features/`
- `make validate` doit passer sans erreur avant chaque commit

---

## Documentation — règles

Après chaque story ou modification notable, mettre à jour :

| Document | Quand |
|----------|-------|
| `docs/story-{epic}-{num}-{slug}.md` | Chaque story — obligatoire |
| `docs/product-audit.md` | Après chaque story complétée |
| `docs/security.md` | Si la story touche auth, data, API, secrets, ports |
| `README.md` | Si installation, commandes, ou structure changent |

---

## Agents à utiliser

Après chaque story implémentée, lancer **systématiquement** :
- `cloudbreak-dev-reviewer` — vérifie patterns, ACs, doc
- `cloudbreak-security` — si la story touche auth / data / API / secrets

---

## Migrations Alembic — points d'attention

- Toujours importer les modèles dans `alembic/env.py` pour que l'autogenerate les détecte
- `PYTHONPATH=.` requis pour que alembic trouve le module `app`
- `script.py.mako` doit être présent dans `alembic/`
- Supprimer la révision en DB (`DELETE FROM alembic_version`) si migration vide régénérée
