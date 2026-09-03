.PHONY: test lint setup migrate up down start

test:
	./scripts/test.sh

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

setup:
	./scripts/setup.sh

migrate:
	.venv/bin/python manage.py migrate

up:
	docker compose up --build

down:
	docker compose down

start:
	./start.sh
