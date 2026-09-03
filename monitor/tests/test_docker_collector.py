from unittest.mock import MagicMock, patch

import docker
import pytest

from monitor.collectors.docker import DockerCollector
from monitor.models import DockerContainer, Host, MetricSnapshot, MetricSubject


def _make_container(
    *,
    container_id: str = "abc123deadbeef",
    name: str = "web",
    status: str = "running",
    health: str = "healthy",
    image: str = "nginx:latest",
    started_at: str = "2024-01-01T00:00:00.000000000Z",
):
    container = MagicMock()
    container.id = container_id
    container.name = f"/{name}"
    container.attrs = {
        "State": {
            "Status": status,
            "Health": {"Status": health},
            "StartedAt": started_at,
        },
        "Config": {"Image": image},
    }
    container.stats.return_value = {
        "memory_stats": {"usage": 128_000_000, "limit": 256_000_000},
        "cpu_stats": {
            "cpu_usage": {"total_usage": 2_000_000_000},
            "system_cpu_usage": 10_000_000_000,
            "online_cpus": 4,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 1_000_000_000},
            "system_cpu_usage": 5_000_000_000,
        },
    }
    return container


@pytest.fixture
def host(db):
    return Host.objects.create(name="talos", hostname="talos.local")


@pytest.mark.django_db
def test_collect_upserts_docker_container(host):
    container = _make_container()
    client = MagicMock()
    client.containers.all.return_value = [container]

    with patch("monitor.collectors.docker.docker.from_env", return_value=client):
        with patch("monitor.collectors.docker.get_or_create_host", return_value=host):
            DockerCollector().collect()

    row = DockerContainer.objects.get(host=host, container_id="abc123deadbeef")
    assert row.name == "web"
    assert row.image == "nginx:latest"
    assert row.status == "running"
    assert row.health == "healthy"
    assert row.memory_bytes == 128_000_000
    assert row.cpu_percent is not None


@pytest.mark.django_db
def test_running_container_gets_metric_snapshot(host):
    container = _make_container()
    client = MagicMock()
    client.containers.all.return_value = [container]

    with patch("monitor.collectors.docker.docker.from_env", return_value=client):
        with patch("monitor.collectors.docker.get_or_create_host", return_value=host):
            DockerCollector().collect()

    snapshot = MetricSnapshot.objects.get(
        host=host,
        subject_type=MetricSubject.CONTAINER,
    )
    assert snapshot.container.name == "web"
    assert snapshot.memory_bytes == 128_000_000


@pytest.mark.django_db
def test_unreachable_docker_logs_warning_no_raise(host, caplog):
    with patch(
        "monitor.collectors.docker.docker.from_env",
        side_effect=docker.errors.DockerException("connection failed"),
    ):
        with patch("monitor.collectors.docker.get_or_create_host", return_value=host):
            DockerCollector().collect()

    assert "connection failed" in caplog.text.lower() or "docker" in caplog.text.lower()
    assert DockerContainer.objects.count() == 0


@pytest.mark.django_db
def test_no_mutating_docker_calls(host):
    container = _make_container()
    client = MagicMock()
    client.containers.all.return_value = [container]

    with patch("monitor.collectors.docker.docker.from_env", return_value=client):
        with patch("monitor.collectors.docker.get_or_create_host", return_value=host):
            DockerCollector().collect()

    container.start.assert_not_called()
    container.stop.assert_not_called()
    container.kill.assert_not_called()


@pytest.mark.django_db
def test_missing_container_marked_removed(host):
    existing = DockerContainer.objects.create(
        host=host,
        container_id="oldcontainer",
        name="old",
        image="alpine",
        status="running",
    )
    client = MagicMock()
    client.containers.all.return_value = []

    with patch("monitor.collectors.docker.docker.from_env", return_value=client):
        with patch("monitor.collectors.docker.get_or_create_host", return_value=host):
            DockerCollector().collect()

    existing.refresh_from_db()
    assert existing.status == "removed"


@pytest.mark.django_db
def test_exited_container_no_snapshot(host):
    container = _make_container(status="exited")
    client = MagicMock()
    client.containers.all.return_value = [container]

    with patch("monitor.collectors.docker.docker.from_env", return_value=client):
        with patch("monitor.collectors.docker.get_or_create_host", return_value=host):
            DockerCollector().collect()

    assert DockerContainer.objects.filter(host=host).count() == 1
    assert (
        MetricSnapshot.objects.filter(subject_type=MetricSubject.CONTAINER).count()
        == 0
    )
