import pytest
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import Client, override_settings
from django.utils import timezone

from monitor.models import MetricSnapshot, MetricSubject
from monitor.services.charts import downsample_points, get_host_chart_data


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
    assert content.count("<polyline") == 3
    assert content.count("<svg") == 1
    assert "CPU" in content
    assert "Memory" in content
    assert "Disk" in content


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
    points = [
        MetricSnapshot(
            recorded_at=timezone.now(),
            subject_type=MetricSubject.HOST,
            cpu_percent=float(i),
            memory_percent=float(i),
        )
        for i in range(50)
    ]

    result = downsample_points(points)

    assert len(result) == 50


@pytest.mark.django_db
@override_settings(TIME_ZONE="America/New_York")
def test_host_chart_labels_use_eastern_time(host):
    timezone.activate(ZoneInfo("America/New_York"))
    frozen_now = datetime(2026, 9, 8, 16, 10, tzinfo=dt_timezone.utc)
    start = datetime(2026, 9, 8, 15, 20, tzinfo=dt_timezone.utc)
    end = datetime(2026, 9, 8, 16, 5, tzinfo=dt_timezone.utc)
    for recorded_at, cpu in ((start, 10.0), (end, 40.0)):
        MetricSnapshot.objects.create(
            recorded_at=recorded_at,
            subject_type=MetricSubject.HOST,
            host=host,
            cpu_percent=cpu,
            memory_percent=50.0,
            disk_percent=20.0,
        )

    try:
        with patch("monitor.models.timezone.now", return_value=frozen_now):
            chart = get_host_chart_data(host)
    finally:
        timezone.deactivate()

    assert chart is not None
    assert chart.start_label == "11:20"
    assert chart.end_label == "12:05"
