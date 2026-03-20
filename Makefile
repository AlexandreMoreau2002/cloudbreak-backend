# ────────────────────────────────────────────────
#  Cloudbreak Backend — commandes de développement
#  Usage : make <commande>
# ────────────────────────────────────────────────

.PHONY: help validate lint format typecheck test dev down logs migrate migration install seed

help:
	@echo ""
	@echo "  Cloudbreak Backend"
	@echo ""
	@echo "  Qualité"
	@echo "    make validate    ruff + mypy + pytest --cov (à lancer avant chaque commit)"
	@echo "    make lint        ruff check uniquement"
	@echo "    make format      ruff format (corrige les fichiers)"
	@echo "    make typecheck   mypy uniquement"
	@echo "    make test        pytest avec coverage"
	@echo ""
	@echo "  Infra locale"
	@echo "    make dev         lance api + db + redis (Docker)"
	@echo "    make down        arrête les containers"
	@echo "    make logs        suit les logs en temps réel"
	@echo ""
	@echo "  Base de données"
	@echo "    make migrate     applique les migrations"
	@echo "    make migration   génère une nouvelle migration (autogenerate)"
	@echo "    make seed        insère les sommets initiaux"
	@echo ""
	@echo "  Dépendances"
	@echo "    make install     pip install requirements"
	@echo ""

# Valide tout avant de commiter — à lancer obligatoirement
validate:
	ruff check .
	ruff format --check .
	mypy app/
	pytest --cov=app --cov-report=term-missing

# Qualité individuelle
lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy app/

test:
	pytest --cov=app --cov-report=term-missing

# Infra locale (db + redis)
dev:
	docker compose -f ../infra/docker-compose.dev.yml up -d

down:
	docker compose -f ../infra/docker-compose.dev.yml down

logs:
	docker compose -f ../infra/docker-compose.dev.yml logs -f

# Migrations
migrate:
	PYTHONPATH=. alembic upgrade head

migration:
	@read -p "Description de la migration : " desc; \
	PYTHONPATH=. alembic revision --autogenerate -m "$$desc"

# Seed données initiales (sommets)
seed:
	python -m app.db.seed

# Dépendances
install:
	pip install -r requirements.txt -r requirements-dev.txt
