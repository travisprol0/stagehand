"""Host metrics for remote hosts (e.g. hermes), pulled over SSH from /proc."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone

from django.conf import settings
from django.utils import timezone

from monitor.collectors.base import BaseCollector
from monitor.collectors.host import _network_rates, store_host_sample
from monitor.models import Host
from monitor.services.remote import RemoteProbeError, run_probe

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteSample:
    load: tuple[float | None, float | None, float | None]
    boot_time: datetime | None
    memory_total: int
    memory_used: int
    cpu_percent: float | None
    cpu_count: int | None
    disk: tuple[float | None, int | None, int | None]
    net_recv: int | None
    net_sent: int | None


def _sections(output: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in output.splitlines():
        if line.isupper() and line.replace("1", "").replace("2", "").isalpha():
            current = line
            sections[current] = []
        elif current is not None and line.strip():
            sections[current].append(line)
    return sections


def cpu_percent_from_stat(first: str, second: str) -> float | None:
    """CPU busy % between two `cpu ...` lines of /proc/stat."""

    def counters(line: str) -> tuple[int, int]:
        values = [int(v) for v in line.split()[1:9]]
        idle = values[3] + values[4]  # idle + iowait
        return sum(values), idle

    total_1, idle_1 = counters(first)
    total_2, idle_2 = counters(second)
    total_delta = total_2 - total_1
    if total_delta <= 0:
        return None
    return max(0.0, min(100.0, (1 - (idle_2 - idle_1) / total_delta) * 100.0))


def parse_probe(output: str, *, now: datetime) -> RemoteSample:
    sec = _sections(output)
    try:
        load = tuple(float(v) for v in sec["LOADAVG"][0].split()[:3])
        uptime = float(sec["UPTIME"][0].split()[0])
        meminfo = {
            line.split(":")[0]: int(line.split()[1]) * 1024 for line in sec["MEMINFO"]
        }
        total = meminfo["MemTotal"]
        available = meminfo["MemAvailable"]
        cpu_count = int(sec["NPROC"][0])
        cpu_percent = cpu_percent_from_stat(sec["CPU1"][0], sec["CPU2"][0])
        df = sec["DISK"][0].split()
        disk_total, disk_used = int(df[1]), int(df[2])
        disk_percent = disk_used / disk_total * 100.0 if disk_total else None
        net_recv = net_sent = 0
        for line in sec["NET"]:
            if ":" not in line:
                continue
            iface, data = line.split(":", 1)
            if iface.strip().startswith("lo"):
                continue
            fields = data.split()
            net_recv += int(fields[0])
            net_sent += int(fields[8])
    except (KeyError, IndexError, ValueError) as exc:
        raise RemoteProbeError(f"unexpected probe output: {exc}") from exc

    boot = datetime.fromtimestamp(
        now.timestamp() - uptime,
        tz=dt_timezone.utc,
    )
    return RemoteSample(
        load=load,
        boot_time=boot,
        memory_total=total,
        memory_used=total - available,
        cpu_percent=cpu_percent,
        cpu_count=cpu_count,
        disk=(disk_percent, disk_used, disk_total),
        net_recv=net_recv,
        net_sent=net_sent,
    )


class RemoteHostMetricsCollector(BaseCollector):
    name = "remote-host"

    def collect(self) -> None:
        for name, target in settings.REMOTE_HOSTS.items():
            host, _ = Host.objects.get_or_create(name=name, defaults={"hostname": name})
            try:
                now = timezone.now()
                sample = parse_probe(run_probe(target), now=now)
            except RemoteProbeError as exc:
                logger.warning("Host %s unreachable: %s", name, exc)
                # Keep last-good values and updated_at so staleness shows.
                Host.objects.filter(pk=host.pk).update(
                    reachable=False,
                    last_error=str(exc)[:255],
                )
                continue

            net_rates = _network_rates(
                host,
                sent=sample.net_sent,
                recv=sample.net_recv,
                now=now,
            )
            store_host_sample(
                host,
                hostname=name,
                now=now,
                cpu_percent=sample.cpu_percent,
                cpu_count=sample.cpu_count,
                memory_percent=sample.memory_used / sample.memory_total * 100.0,
                memory_used=sample.memory_used,
                memory_total=sample.memory_total,
                load=sample.load,
                boot_time=sample.boot_time,
                disk=sample.disk,
                net=(sample.net_sent, sample.net_recv),
                net_rates=net_rates,
            )
