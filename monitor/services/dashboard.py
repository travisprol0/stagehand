from django.conf import settings
from django.utils import timezone

from monitor.models import DockerContainer, GitHubRunner, Host, RunnerStatus


def get_current_host() -> Host | None:
    return Host.objects.filter(name=settings.HOST_NAME).first()


def get_host_containers(host: Host):
    return DockerContainer.objects.filter(host=host).exclude(status="removed")


def get_host_runners(host: Host):
    return GitHubRunner.objects.filter(host=host)


def summarize_containers(host: Host) -> dict[str, int]:
    rows = get_host_containers(host)
    running = rows.filter(status="running").count()
    unhealthy = rows.filter(health="unhealthy").count()
    return {
        "total": rows.count(),
        "running": running,
        "unhealthy": unhealthy,
        "exited": rows.filter(status="exited").count(),
    }


def summarize_runners(host: Host) -> dict[str, int]:
    rows = get_host_runners(host)
    return {
        "total": rows.count(),
        "idle": rows.filter(status=RunnerStatus.IDLE).count(),
        "active": rows.filter(status=RunnerStatus.ACTIVE).count(),
        "offline": rows.filter(status=RunnerStatus.OFFLINE).count(),
        "busy": rows.filter(busy=True).count(),
    }


def attention_items(host: Host) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if host.updated_at is not None:
        age = (timezone.now() - host.updated_at).total_seconds()
        if age > 90:
            items.append(
                {
                    "level": "warn",
                    "text": f"Collector last update {int(age)}s ago",
                }
            )
    if host.disk_percent is not None and host.disk_percent >= 90:
        items.append(
            {
                "level": "error",
                "text": f"Disk {host.disk_percent:.0f}% full",
            }
        )
    elif host.disk_percent is not None and host.disk_percent >= 70:
        items.append(
            {
                "level": "warn",
                "text": f"Disk {host.disk_percent:.0f}% full",
            }
        )
    for container in get_host_containers(host).filter(health="unhealthy"):
        items.append({"level": "error", "text": f"{container.name} is unhealthy"})
    for container in get_host_containers(host).exclude(state_error=""):
        items.append(
            {
                "level": "error",
                "text": f"{container.name}: {container.state_error}",
            }
        )
    for runner in get_host_runners(host).filter(busy=True):
        label = (
            runner.current_workflow_name
            or runner.current_job_name
            or "unknown job"
        )
        extra = runner.current_repository or runner.current_head_branch
        if extra:
            label = f"{label} ({extra})"
        items.append({"level": "info", "text": f"{runner.name}: {label}"})
    return items
