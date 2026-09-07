from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from monitor.collectors.host import HostMetricsCollector, _disk_path, _read_disk_usage
from monitor.models import Host, MetricSnapshot, MetricSubject


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
    assert host.disk_percent == 40.0
    assert host.disk_used_bytes == 100_000_000_000
    assert host.disk_total_bytes == 250_000_000_000
    assert host.cpu_count == 8
    assert host.boot_time is not None
    assert host.net_bytes_sent == 1_000_000
    assert host.net_bytes_recv == 2_000_000
    assert host.net_sent_bps is None
    assert host.net_recv_bps is None


@pytest.mark.django_db
def test_second_collect_computes_network_rates(psutil_mocks):
    with patch("monitor.collectors.host.socket.gethostname", return_value="test-host"):
        HostMetricsCollector().collect()

    host = Host.objects.get(name="talos")
    Host.objects.filter(pk=host.pk).update(
        updated_at=timezone.now() - timezone.timedelta(seconds=10),
    )
    psutil_mocks.net_io_counters.return_value = {
        "lo": MagicMock(bytes_sent=999, bytes_recv=999),
        "eth0": MagicMock(bytes_sent=1_500_000, bytes_recv=2_200_000),
    }

    with patch("monitor.collectors.host.socket.gethostname", return_value="test-host"):
        HostMetricsCollector().collect()

    host.refresh_from_db()
    assert host.net_sent_bps == pytest.approx(50_000, rel=0.2)
    assert host.net_recv_bps == pytest.approx(20_000, rel=0.2)
    snapshot = (
        MetricSnapshot.objects.filter(
            host=host,
            subject_type=MetricSubject.HOST,
        )
        .order_by("-recorded_at")
        .first()
    )
    assert snapshot.disk_percent == 40.0
    assert snapshot.net_sent_bps == pytest.approx(host.net_sent_bps)
    assert snapshot.net_recv_bps == pytest.approx(host.net_recv_bps)


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


def test_disk_path_prefers_host_fs_root(tmp_path, monkeypatch):
    host_root = tmp_path / "hostroot"
    (host_root / "etc").mkdir(parents=True)
    monkeypatch.setenv("HOST_FS_ROOT", str(host_root))

    assert _disk_path() == str(host_root)


def test_read_disk_usage_queries_host_bind_mount(tmp_path, monkeypatch):
    host_root = tmp_path / "hostroot"
    (host_root / "etc").mkdir(parents=True)
    monkeypatch.setenv("HOST_FS_ROOT", str(host_root))

    with patch("monitor.collectors.host.psutil.disk_usage") as usage:
        usage.return_value = MagicMock(percent=12.5, used=3, total=24)
        assert _read_disk_usage() == (12.5, 3, 24)
        usage.assert_called_once_with(str(host_root))
