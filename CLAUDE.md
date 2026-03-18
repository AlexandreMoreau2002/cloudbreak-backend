# CLAUDE.md — Backend

## Workflow de développement

Après chaque modification, lancer dans l'ordre :

```bash
ruff check .                              # 0 erreur lint
ruff format .                             # formatage auto
mypy app/                                 # 0 erreur typage
pytest --cov=app --cov-report=term-missing  # tous les tests passent, coverage 100%
```

**Règles :**
- Le coverage doit rester à **100%** — tout nouveau fichier source a son fichier de test dans `tests/`
- 0 erreur ruff et 0 erreur mypy avant de commiter
- L'infra locale doit tourner pour les tests d'intégration : `docker compose -f ../infra/docker-compose.dev.yml up -d`
