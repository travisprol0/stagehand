# stagehand

Private infrastructure monitor for host **talos**: Django + PostgreSQL dashboard for host metrics, Docker containers, and GitHub Actions self-hosted runners.

## Quick start

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
source .venv/bin/activate
python manage.py runserver
```

Open [http://127.0.0.1:8000/health/](http://127.0.0.1:8000/health/) — should return `OK`.

`setup.sh` starts Postgres in Docker on **port 5433** (avoids your system Postgres on 5432) and runs migrations.

If Docker says `permission denied`, the script retries with `sudo`. One-time fix so you don't need sudo:

```bash
sudo usermod -aG docker $USER
# log out and back in
```

## Manual steps

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d db    # or: sudo docker compose up -d db
python manage.py migrate
python manage.py runserver
```

Use the venv — Ubuntu does not provide a global `python` command.

## Testing (TDD from ticket 003)

```bash
pip install -r requirements-dev.txt
chmod +x scripts/test.sh
./scripts/test.sh          # or: make test
```

Tickets 003+ require writing failing tests first, then implementation. See `local-development/AGENT-CHECKLIST.md`.

## Environment variables

See [`.env.example`](.env.example). Default database: `stagehand` / `stagehand` on `localhost:5433`.

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | — | Django secret |
| `POSTGRES_PORT` | `5433` | App DB port (Compose maps 5433→5432 in container) |
| `HOST_NAME` | `talos` | Host label for metrics (later tickets) |

Planning tickets: `local-development/` (gitignored locally).
