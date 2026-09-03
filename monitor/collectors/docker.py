import logging
from datetime import datetime

import docker
from django.utils import timezone
from docker.errors import DockerException

from monitor.collectors.base import BaseCollector
from monitor.models import (
    DockerContainer,
    MetricSnapshot,
    MetricSubject,
    get_or_create_host,
)

logger = logging.getLogger(__name__)


def _parse_started_at(value: str | None) -> datetime | None:
    if not value or value.startswith("0001"):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _container_health(attrs: dict) -> str:
    health = attrs.get("State", {}).get("Health")
    if not health:
        return "none"
    return health.get("Status") or "none"


def _cpu_percent_from_stats(stats: dict) -> float | None:
    """Instantaneous CPU % from one stats(stream=False) sample (Docker API)."""
    try:
        cpu_stats = stats["cpu_stats"]
        precpu_stats = stats["precpu_stats"]
        cpu_delta = (
            cpu_stats["cpu_usage"]["total_usage"]
            - precpu_stats["cpu_usage"]["total_usage"]
        )
        system_delta = (
            cpu_stats["system_cpu_usage"] - precpu_stats["system_cpu_usage"]
        )
        if system_delta <= 0:
            return None
        online_cpus = cpu_stats.get("online_cpus", 1)
        return (cpu_delta / system_delta) * online_cpus * 100.0
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def _memory_bytes_from_stats(stats: dict) -> int | None:
    try:
        return int(stats["memory_stats"]["usage"])
    except (KeyError, TypeError, ValueError):
        return None


class DockerCollector(BaseCollector):
    name = "docker"

    def collect(self) -> None:
        host = get_or_create_host()

        try:
            client = docker.from_env(timeout=10)
        except DockerException as exc:
            logger.warning("Docker unavailable: %s", exc)
            return

        try:
            containers = client.containers.all()
        except DockerException as exc:
            logger.warning("Failed to list Docker containers: %s", exc)
            return

        seen_ids: set[str] = set()

        for container in containers:
            attrs = container.attrs
            state = attrs.get("State", {})
            status = state.get("Status", "unknown")
            container_id = container.id
            seen_ids.add(container_id)

            name = (container.name or "").lstrip("/")
            image = attrs.get("Config", {}).get("Image", "")
            health = _container_health(attrs)
            started_at = _parse_started_at(state.get("StartedAt"))

            stats = {}
            cpu_percent = None
            memory_bytes = None
            if status == "running":
                try:
                    stats = container.stats(stream=False)
                    cpu_percent = _cpu_percent_from_stats(stats)
                    memory_bytes = _memory_bytes_from_stats(stats)
                except DockerException as exc:
                    logger.warning(
                        "Failed to read stats for container %s: %s",
                        name,
                        exc,
                    )

            row, _ = DockerContainer.objects.update_or_create(
                host=host,
                container_id=container_id,
                defaults={
                    "name": name,
                    "image": image,
                    "status": status,
                    "health": health,
                    "cpu_percent": cpu_percent,
                    "memory_bytes": memory_bytes,
                    "started_at": started_at,
                },
            )

            if status == "running":
                MetricSnapshot.objects.create(
                    recorded_at=timezone.now(),
                    subject_type=MetricSubject.CONTAINER,
                    host=host,
                    container=row,
                    cpu_percent=cpu_percent,
                    memory_bytes=memory_bytes,
                )

        if seen_ids:
            DockerContainer.objects.filter(host=host).exclude(
                container_id__in=seen_ids,
            ).update(status="removed")
        else:
            DockerContainer.objects.filter(host=host).update(status="removed")
