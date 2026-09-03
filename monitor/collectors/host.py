import logging
import socket

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

        Host.objects.filter(pk=host.pk).update(
            hostname=hostname,
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_used_bytes=memory.used,
            memory_total_bytes=memory.total,
            load_avg_1=load_1,
            load_avg_5=load_5,
            load_avg_15=load_15,
        )

        MetricSnapshot.objects.create(
            recorded_at=timezone.now(),
            subject_type=MetricSubject.HOST,
            host=host,
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_bytes=memory.used,
        )

        if created:
            logger.info("Created host record for %s", settings.HOST_NAME)
