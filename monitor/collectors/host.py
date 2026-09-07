import logging
import os
import socket
from datetime import datetime
from datetime import timezone as dt_timezone

import psutil
from django.conf import settings
from django.utils import timezone

from monitor.collectors.base import BaseCollector
from monitor.models import Host, MetricSnapshot, MetricSubject

logger = logging.getLogger(__name__)


def _read_load_averages() -> tuple[float | None, float | None, float | None]:
    try:
        load_1, load_5, load_15 = psutil.getloadavg()
        return load_1, load_5, load_15
    except (AttributeError, OSError):
        return None, None, None


def _read_boot_time():
    try:
        return datetime.fromtimestamp(psutil.boot_time(), tz=dt_timezone.utc)
    except (AttributeError, OSError, OverflowError, ValueError):
        return None


def _disk_path() -> str:
    """Prefer a bind-mounted host root so Compose collectors don't report the overlay."""
    override = os.environ.get("HOST_FS_ROOT", "").strip()
    candidates = [override, "/host", "/"] if override else ["/host", "/"]
    for path in candidates:
        if path and os.path.isdir(path) and os.path.isdir(os.path.join(path, "etc")):
            if override and path != override:
                logger.warning(
                    "HOST_FS_ROOT=%s is not usable; measuring disk at %s",
                    override,
                    path,
                )
            return path
    if override:
        logger.warning("HOST_FS_ROOT=%s is not usable; measuring disk at /", override)
    return "/"


def _read_disk_usage() -> tuple[float | None, int | None, int | None]:
    try:
        disk = psutil.disk_usage(_disk_path())
        return disk.percent, int(disk.used), int(disk.total)
    except (AttributeError, OSError, TypeError, ValueError):
        return None, None, None


def _read_network_totals() -> tuple[int | None, int | None]:
    try:
        pernic = psutil.net_io_counters(pernic=True)
    except (AttributeError, OSError, TypeError):
        return None, None
    if not isinstance(pernic, dict):
        return None, None

    sent = 0
    recv = 0
    found = False
    for name, stats in pernic.items():
        if str(name).startswith("lo"):
            continue
        try:
            sent += int(stats.bytes_sent)
            recv += int(stats.bytes_recv)
        except (AttributeError, TypeError, ValueError):
            continue
        found = True
    if not found:
        return None, None
    return sent, recv


def _network_rates(
    host: Host,
    *,
    sent: int | None,
    recv: int | None,
    now,
) -> tuple[float | None, float | None]:
    if (
        sent is None
        or recv is None
        or host.net_bytes_sent is None
        or host.net_bytes_recv is None
        or host.updated_at is None
    ):
        return None, None
    elapsed = (now - host.updated_at).total_seconds()
    if elapsed <= 0:
        return None, None
    sent_bps = max(0.0, (sent - host.net_bytes_sent) / elapsed)
    recv_bps = max(0.0, (recv - host.net_bytes_recv) / elapsed)
    return sent_bps, recv_bps


class HostMetricsCollector(BaseCollector):
    name = "host"

    def collect(self) -> None:
        hostname = socket.gethostname()
        host, created = Host.objects.get_or_create(
            name=settings.HOST_NAME,
            defaults={"hostname": hostname},
        )

        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        load_1, load_5, load_15 = _read_load_averages()
        boot_time = _read_boot_time()
        disk_percent, disk_used, disk_total = _read_disk_usage()
        net_sent, net_recv = _read_network_totals()
        now = timezone.now()
        net_sent_bps, net_recv_bps = _network_rates(
            host,
            sent=net_sent,
            recv=net_recv,
            now=now,
        )

        Host.objects.filter(pk=host.pk).update(
            hostname=hostname,
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_used_bytes=memory.used,
            memory_total_bytes=memory.total,
            load_avg_1=load_1,
            load_avg_5=load_5,
            load_avg_15=load_15,
            boot_time=boot_time,
            disk_percent=disk_percent,
            disk_used_bytes=disk_used,
            disk_total_bytes=disk_total,
            net_bytes_sent=net_sent,
            net_bytes_recv=net_recv,
            net_sent_bps=net_sent_bps,
            net_recv_bps=net_recv_bps,
            updated_at=now,
        )

        MetricSnapshot.objects.create(
            recorded_at=now,
            subject_type=MetricSubject.HOST,
            host=host,
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_bytes=memory.used,
            disk_percent=disk_percent,
            net_sent_bps=net_sent_bps,
            net_recv_bps=net_recv_bps,
        )

        if created:
            logger.info("Created host record for %s", settings.HOST_NAME)
