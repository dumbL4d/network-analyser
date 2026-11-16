# Common commands. Run `make` or `make help` for the list.
#
# The Docker targets read infra/.env (copy infra/.env.example first).
# CHAOS=1 adds the fault-injection agent:  make up CHAOS=1

COMPOSE := docker compose -f infra/docker-compose.yml
# The backend's interpreter, relative to backend/. Override: make test PYTHON=python
PYTHON ?= .venv/bin/python

.PHONY: help up down seed-reset test lint build

help: ## Show this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | expand -t 14

up: ## Build and start the stack (CHAOS=1 adds the chaos agent)
	$(COMPOSE) $(if $(CHAOS),--profile chaos) up -d --build

# --profile chaos here and below, so that the agent is stopped too if it runs.
down: ## Stop the stack; the data is kept
	$(COMPOSE) --profile chaos down

seed-reset: ## Stop the stack, DELETE its database, start again from the seed file
	$(COMPOSE) --profile chaos down -v
	$(MAKE) up

test: ## Backend tests with coverage, then the coverage gate CI enforces
	cd backend && $(PYTHON) -m pytest --cov=app --cov-report=term-missing
	cd backend && $(PYTHON) -m coverage report --include="app/services/*" --fail-under=80

lint: ## Frontend typecheck and lint
	cd frontend && npx tsc -b --noEmit && npm run lint

build: ## Frontend production build
	cd frontend && npm run build
