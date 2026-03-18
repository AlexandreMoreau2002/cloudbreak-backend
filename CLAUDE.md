# CLAUDE.md — Backend

## Workflow de développement

**Toujours lancer `make validate` avant de commiter.** Cette commande valide tout d'un coup :

```bash
make validate
# enchaîne : ruff check → ruff format --check → mypy → pytest --cov
```

Ne jamais commiter si `make validate` échoue.

**Règles :**
- Le coverage doit rester à **100%** — tout nouveau fichier source a son fichier de test dans `tests/`
- 0 erreur ruff, 0 erreur mypy avant de commiter
- L'infra locale doit tourner pour les tests d'intégration : `docker compose -f ../infra/docker-compose.dev.yml up -d`
