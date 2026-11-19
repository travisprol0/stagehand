from django.conf import settings
from django.utils import timezone

from monitor.models import DockerContainer, GitHubRunner, Host, RunnerStatus


def get_host_containers(host: Host):
    return DockerContainer.objects.filter(host=host).exclude(status="removed")


def _container_rank(container: DockerContainer) -> int:
    if container.health == "unhealthy" or container.state_error:
        return 0
    if container.status != "running":
        return 1
    return 2


def containers_for_display(host: Host) -> list[DockerContainer]:
    """Problems first, then stopped, then running; each with its sparklines."""
    from monitor.services.charts import get_container_sparklines

    sparks = get_container_sparklines(host)
    rows = list(get_host_containers(host))
    for container in rows:
        container.spark = sparks.get(container.pk, {})
    rows.sort(key=lambda c: (_container_rank(c), c.name))
    return rows


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
    if not host.reachable:
        since = ""
        if host.updated_at is not None:
            age = int((timezone.now() - host.updated_at).total_seconds())
            since = f" (last data {age}s ago)"
        items.append(
            {
                "level": "error",
                "text": (
                    f"{host.name} unreachable{since}: "
                    f"{host.last_error or 'no response'}"
                ),
            }
        )
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
    return items


def configured_host_names() -> list[str]:
    """Local host first, then REMOTE_HOSTS in configured order."""
    return [settings.HOST_NAME, *settings.REMOTE_HOSTS]


def get_host_by_name(name: str) -> Host | None:
    return Host.objects.filter(name=name).first()


def build_section(name: str) -> dict:
    """Everything one per-host dashboard section needs.

    The local host keeps unprefixed DOM ids and plain fragment URLs so existing
    pages and tests are unchanged; remote hosts get a `<name>-` id prefix and a
    `?host=<name>` query on their fragment URLs.
    """
    from monitor.services.charts import get_host_chart_data, get_host_sparklines

    is_local = name == settings.HOST_NAME
    host = get_host_by_name(name)
    return {
        "name": name,
        "is_local": is_local,
        "prefix": "" if is_local else f"{name}-",
        "qs": "" if is_local else f"?host={name}",
        "host": host,
        "containers": containers_for_display(host) if host else [],
        "runners": get_host_runners(host) if host else [],
        "container_stats": summarize_containers(host) if host else None,
        "runner_stats": summarize_runners(host) if host else None,
        "chart": get_host_chart_data(host) if host else None,
        "spark": get_host_sparklines(host) if host else {},
        "attention": attention_items(host) if host else [],
    }


def build_runner_panel(host_name: str | None = None, filters=None) -> dict:
    """Fleet-wide runner timeline (or one host's, when `host_name` is given)."""
    from monitor.services.runner_jobs import (
        OUTCOMES,
        WINDOWS,
        HistoryFilters,
        build_timeline,
        job_stats,
        queue_snapshot,
        workflow_names,
        workflow_stats,
    )

    filters = filters or HistoryFilters()

    order = {name: index for index, name in enumerate(configured_host_names())}
    runners = GitHubRunner.objects.select_related("host")
    if host_name:
        runners = runners.filter(host__name=host_name)
    runners = sorted(
        runners, key=lambda r: (order.get(r.host.name, len(order)), r.name)
    )
    counts = {
        "total": len(runners),
        "idle": sum(1 for r in runners if r.status == RunnerStatus.IDLE),
        "active": sum(1 for r in runners if r.status == RunnerStatus.ACTIVE),
        "offline": sum(1 for r in runners if r.status == RunnerStatus.OFFLINE),
    }
    return {
        "runners": runners,
        "runner_stats": counts,
        "timeline": build_timeline(runners, filters=filters),
        "queue": queue_snapshot(),
        "job_stats": job_stats(filters=filters),
        "workflows": workflow_stats(filters=filters),
        "filters": filters,
        "outcome_choices": OUTCOMES.items(),
        "window_choices": WINDOWS.items(),
        "workflow_choices": workflow_names(),
        "runners_qs": filters.querystring(host_name or ""),
        "multi_host": len(order) > 1,
    }
