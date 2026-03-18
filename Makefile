# ────────────────────────────────────────────────
#  Cloudbreak Backend — commandes de développement
#  Usage : make <commande>
# ────────────────────────────────────────────────

.PHONY: validate lint format typecheck test dev down logs migrate migration install

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
	alembic upgrade head

migration:
	@read -p "Description de la migration : " desc; \
	alembic revision --autogenerate -m "$$desc"

# Dépendances
install:
	pip install -r requirements.txt -r requirements-dev.txt
