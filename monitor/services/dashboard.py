from django.conf import settings

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
    }


def summarize_runners(host: Host) -> dict[str, int]:
    rows = get_host_runners(host)
    return {
        "total": rows.count(),
        "idle": rows.filter(status=RunnerStatus.IDLE).count(),
        "active": rows.filter(status=RunnerStatus.ACTIVE).count(),
        "offline": rows.filter(status=RunnerStatus.OFFLINE).count(),
    }
