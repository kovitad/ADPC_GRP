PYTHON ?= python
COMPOSE = docker compose --env-file .env -f deploy/compose.yml

.PHONY: install test lint format migrate compose-config up down

install:
	$(PYTHON) -m pip install -e ".[dev,gis]"

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

migrate:
	$(PYTHON) -m alembic upgrade head

compose-config:
	$(COMPOSE) config

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down
