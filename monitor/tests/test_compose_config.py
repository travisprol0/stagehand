from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
DOCKERIGNORE_PATH = ROOT / ".dockerignore"


@pytest.fixture
def compose_config():
    with COMPOSE_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_compose_services_exist(compose_config):
    services = compose_config["services"]

    assert "db" in services
    assert "web" in services
    assert "collector" in services


def test_web_and_collector_mount_docker_socket_read_only(compose_config):
    for service_name in ("web", "collector"):
        volumes = compose_config["services"][service_name].get("volumes", [])
        assert any(
            volume == "/var/run/docker.sock:/var/run/docker.sock:ro"
            for volume in volumes
        ), f"{service_name} must mount docker.sock read-only"


def test_db_service_has_no_docker_socket_mount(compose_config):
    volumes = compose_config["services"]["db"].get("volumes", [])

    assert not any("docker.sock" in str(volume) for volume in volumes)


def test_dockerignore_excludes_env_and_venv():
    content = DOCKERIGNORE_PATH.read_text(encoding="utf-8")

    assert ".env" in content
    assert ".venv" in content
