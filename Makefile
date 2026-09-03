.PHONY: test lint setup migrate

test:
	./scripts/test.sh

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

setup:
	./scripts/setup.sh

migrate:
	.venv/bin/python manage.py migrate
