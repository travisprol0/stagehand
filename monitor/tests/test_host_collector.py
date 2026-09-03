from unittest.mock import MagicMock, patch

import pytest

from monitor.collectors.host import HostMetricsCollector
from monitor.models import Host, MetricSnapshot, MetricSubject


@pytest.fixture
def psutil_mocks():
    with patch("monitor.collectors.host.psutil") as mock_psutil:
        mock_psutil.cpu_percent.return_value = 42.0
        mock_psutil.virtual_memory.return_value = MagicMock(
            percent=61.0,
            used=8_000_000_000,
            total=16_000_000_000,
        )
        mock_psutil.getloadavg.return_value = (1.2, 0.9, 0.7)
        yield mock_psutil


@pytest.mark.django_db
def test_collect_creates_host_and_snapshot(psutil_mocks):
    with patch("monitor.collectors.host.socket.gethostname", return_value="test-host"):
        HostMetricsCollector().collect()

    host = Host.objects.get(name="talos")
    assert host.hostname == "test-host"
    snapshots = MetricSnapshot.objects.filter(
        host=host,
        subject_type=MetricSubject.HOST,
    )
    assert snapshots.count() == 1
    assert snapshots.first().cpu_percent == 42.0


@pytest.mark.django_db
def test_collect_updates_denormalized_host_fields(psutil_mocks):
    with patch("monitor.collectors.host.socket.gethostname", return_value="test-host"):
        HostMetricsCollector().collect()

    host = Host.objects.get(name="talos")
    assert host.cpu_percent == 42.0
    assert host.memory_percent == 61.0
    assert host.memory_used_bytes == 8_000_000_000
    assert host.memory_total_bytes == 16_000_000_000
    assert host.load_avg_1 == 1.2
    assert host.load_avg_5 == 0.9
    assert host.load_avg_15 == 0.7


@pytest.mark.django_db
def test_second_collect_appends_snapshot(psutil_mocks):
    with patch("monitor.collectors.host.socket.gethostname", return_value="test-host"):
        collector = HostMetricsCollector()
        collector.collect()
        collector.collect()

    host = Host.objects.get(name="talos")
    assert (
        MetricSnapshot.objects.filter(
            host=host,
            subject_type=MetricSubject.HOST,
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_collect_without_loadavg_support(psutil_mocks):
    psutil_mocks.getloadavg.side_effect = AttributeError("unsupported")
    with patch("monitor.collectors.host.socket.gethostname", return_value="test-host"):
        HostMetricsCollector().collect()

    host = Host.objects.get(name="talos")
    assert host.load_avg_1 is None
    assert host.load_avg_5 is None
    assert host.load_avg_15 is None
