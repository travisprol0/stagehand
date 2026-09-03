import pytest
from django.test import Client
from django.utils import timezone

from monitor.models import MetricSnapshot, MetricSubject
from monitor.services.charts import downsample_points


@pytest.fixture
def client():
    return Client()


@pytest.fixture(autouse=True)
def allow_testserver(settings):
    settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]


@pytest.mark.django_db
def test_host_chart_fragment_renders_polylines(client, host, host_snapshots):
    response = client.get("/fragments/charts/host/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "<polyline" in content or "<path" in content
    assert "CPU" in content
    assert "Memory" in content


@pytest.mark.django_db
def test_host_chart_empty_state(client, host):
    response = client.get("/fragments/charts/host/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "No history yet" in content


@pytest.mark.django_db
def test_host_chart_no_host(client):
    response = client.get("/fragments/charts/host/")

    assert response.status_code == 200
    assert b"No host data" in response.content


def test_downsample_points_reduces_large_series():
    points = list(range(250))

    result = downsample_points(points)

    assert len(result) <= 120
    assert result[0] == 0
    assert result[-1] == points[-1]


@pytest.mark.django_db
def test_dashboard_includes_host_chart_poll_region(client, host, host_snapshots):
    response = client.get("/")
    content = response.content.decode()

    assert 'id="host-chart"' in content
    assert 'hx-get="/fragments/charts/host/"' in content


@pytest.mark.django_db
def test_downsample_points_keeps_small_series():
    points = [MetricSnapshot(
        recorded_at=timezone.now(),
        subject_type=MetricSubject.HOST,
        cpu_percent=float(i),
        memory_percent=float(i),
    ) for i in range(50)]

    result = downsample_points(points)

    assert len(result) == 50
