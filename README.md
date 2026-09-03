# stagehand

Private infrastructure monitor for host **talos**: Django + PostgreSQL dashboard for host metrics, Docker containers, and GitHub Actions self-hosted runners.

## Overview

**stagehand** collects metrics from three sources and stores them in PostgreSQL:

- **Host** — CPU, memory, and load average via `psutil`
- **Docker** — container status, health, and resource usage via a read-only Docker socket
- **GitHub Actions** — self-hosted runner idle/active/offline state via the GitHub REST API

A Django dashboard renders server-side HTML fragments (HTMX) with Tailwind CSS and Alpine.js for polling, dark mode, and a container logs modal. Historical CPU and memory trends are drawn as inline SVG charts from `MetricSnapshot` rows.

## Local development

### Quick start

```bash
chmod +x start.sh
./start.sh
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) for the dashboard.

`start.sh` creates a venv, installs dependencies, copies `.env.example` → `.env` on first run, starts Postgres in Docker on **port 5433**, runs migrations, and launches `runserver`.

Use `./start.sh --collector` to also run the metrics collector in the background so the dashboard populates automatically.

Other flags: `./start.sh --no-migrate`, `HOST=0.0.0.0 PORT=8000 ./start.sh`.

### Setup without starting the server

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
source .venv/bin/activate
python manage.py runserver
```

### Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
docker compose up -d db    # or: sudo docker compose up -d db
python manage.py migrate
python manage.py runserver
```

Use the venv — Ubuntu does not provide a global `python` command.

### Collect metrics locally

Run a single collection iteration:

```bash
python manage.py collect_metrics --once
```

Run the collector loop (same command the Compose `collector` service uses):

```bash
python manage.py collect_metrics
```

Override the interval with `--interval` or `METRICS_INTERVAL_SECONDS` in `.env`.

### Docker permission fix

If Docker says `permission denied`, `setup.sh` retries with `sudo`. One-time fix so you don't need sudo:

```bash
sudo usermod -aG docker $USER
# log out and back in
```

## Docker Compose

Run the full stack on talos (PostgreSQL, Gunicorn web, metrics collector):

```bash
cp .env.example .env
# Set SECRET_KEY and ALLOWED_HOSTS=talos,localhost,127.0.0.1
# Optional: GITHUB_TOKEN, GITHUB_ORG or GITHUB_REPO
make up
# or: docker compose up --build
```

Open [http://localhost:8000/](http://localhost:8000/) (or `http://talos:8000/` on the host).

| Service | Role |
|---------|------|
| `db` | PostgreSQL 16 with persistent volume |
| `web` | Django + Gunicorn; runs migrations and `collectstatic` on start |
| `collector` | `collect_metrics` loop |

For local-only tweaks (e.g. `DEBUG=1`), copy `docker-compose.override.yml.example` to `docker-compose.override.yml`.

Host-only development can still use `docker compose up -d db` plus `runserver` (see Local development above).

### Security checklist

- Docker socket is mounted **read-only** (`:ro`) on `web` and `collector` only — never on `db`.
- The socket is used internally by the Python Docker SDK; it is not exposed on the host network.
- Set `DEBUG=0` in production compose (default in `docker-compose.yml`).
- Provide `GITHUB_TOKEN` via `.env` / `env_file` at runtime — never bake secrets into the image.
- `.env` is listed in `.dockerignore` and excluded from the build context.

## Environment variables

Copy [`.env.example`](.env.example) to `.env` and adjust values. Never commit `.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | — | Django secret key (required in production) |
| `DEBUG` | `False` | Django debug mode (`True`/`1`/`yes` to enable) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hostnames |
| `DATABASE_URL` | — | Optional Postgres URL (overrides `POSTGRES_*`) |
| `POSTGRES_DB` | `stagehand` | Database name |
| `POSTGRES_USER` | `stagehand` | Database user |
| `POSTGRES_PASSWORD` | `stagehand` | Database password |
| `POSTGRES_HOST` | `localhost` | Database host (`db` inside Compose network) |
| `POSTGRES_PORT` | `5433` | Database port (`5432` inside Compose network) |
| `HOST_NAME` | `talos` | Label for the monitored host row |
| `METRICS_INTERVAL_SECONDS` | `10` | Collector and HTMX poll interval |
| `GITHUB_TOKEN` | — | GitHub PAT for runner API (collector skips if unset) |
| `GITHUB_ORG` | — | Organization slug for org-level runners |
| `GITHUB_REPO` | — | `owner/repo` for repo-level runners (use org **or** repo) |
| `GITHUB_API_URL` | `https://api.github.com` | GitHub API base URL |

### GitHub self-hosted runners

Runners only appear if the collector can list them via the GitHub API. That means:

1. **`GITHUB_TOKEN`** is set in `.env` (and the `collector` service sees it if using Compose).
2. **Scope matches registration** — if runners were added under a specific repo (Settings → Actions → Runners), set `GITHUB_REPO=owner/repo` for **that** repo and leave `GITHUB_ORG` empty. If they are org-wide runners, set `GITHUB_ORG` instead.
3. **Collector is running** — `./start.sh --collector`, or the Compose `collector` service.

Verify configuration:

```bash
python manage.py check_github_runners
```

Classic PAT scopes: `repo` for repo-level runners; `admin:org` for org-level runners. Fine-grained tokens need Actions read on the repo or org.

After changing `.env`, restart the collector (`docker compose restart collector` or restart `./start.sh --collector`).
| `DOCKER_HOST` | local socket | Docker daemon URL (optional) |

## Running tests

Install dev dependencies once:

```bash
pip install -r requirements-dev.txt
chmod +x scripts/test.sh
```

Run the full suite:

```bash
make test          # ./scripts/test.sh → pytest -q
pytest -q          # direct
make lint          # ruff check + format --check
```

Unit tests mock Docker and GitHub — no real socket or token is required.

Tickets 003+ were implemented TDD-first. See `local-development/AGENT-CHECKLIST.md` for the workflow.

## Architecture

Django app `monitor` runs a `collect_metrics` management command (or Compose `collector` service) that registers pluggable collectors for host, Docker, and GitHub metrics. Each iteration upserts current state on `Host`, `DockerContainer`, and `GitHubRunner` models and appends `MetricSnapshot` time-series rows. The web tier serves a dashboard and HTMX fragment routes that read from PostgreSQL; the browser polls fragments every `METRICS_INTERVAL_SECONDS` without a full page reload. Compose deploys `web` and `collector` with a read-only Docker socket mount and injects secrets via `env_file` at runtime.

## Makefile targets

| Target | Command |
|--------|---------|
| `make start` | `./start.sh` — bootstrap + runserver |
| `make setup` | `./scripts/setup.sh` — venv, deps, Postgres, migrate (no server) |
| `make migrate` | `python manage.py migrate` |
| `make test` | `./scripts/test.sh` |
| `make lint` | `ruff check .` and `ruff format --check .` |
| `make up` | `docker compose up --build` |
| `make down` | `docker compose down` |

Planning tickets live under `local-development/` (gitignored locally).
