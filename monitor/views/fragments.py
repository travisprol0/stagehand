import logging

import docker
from django.conf import settings
from django.shortcuts import get_object_or_404, render
from docker.errors import DockerException

from monitor.models import DockerContainer
from monitor.services.dashboard import (
    get_current_host,
    get_host_containers,
    get_host_runners,
)

logger = logging.getLogger(__name__)


def _poll_context():
    return {"poll_seconds": settings.METRICS_INTERVAL_SECONDS}


def host_summary(request):
    host = get_current_host()
    if host is None:
        return render(
            request,
            "monitor/fragments/polled_empty_state.html",
            {
                "element_id": "host-summary",
                "fragment_url": "/fragments/host-summary/",
                "message": "No host data yet. Start the metrics collector.",
                **_poll_context(),
            },
        )
    return render(
        request,
        "monitor/fragments/host_summary.html",
        {"host": host, **_poll_context()},
    )


def containers(request):
    host = get_current_host()
    if host is None:
        return render(
            request,
            "monitor/fragments/polled_empty_state.html",
            {
                "element_id": "container-table",
                "fragment_url": "/fragments/containers/",
                "message": "No host data yet. Start the metrics collector.",
                **_poll_context(),
            },
        )
    container_rows = get_host_containers(host)
    return render(
        request,
        "monitor/fragments/container_table.html",
        {"containers": container_rows, **_poll_context()},
    )


def container_row(request, pk: int):
    host = get_current_host()
    container = get_object_or_404(DockerContainer, pk=pk, host=host)
    return render(
        request,
        "monitor/fragments/container_row.html",
        {"container": container},
    )


def runners(request):
    host = get_current_host()
    if host is None:
        return render(
            request,
            "monitor/fragments/polled_empty_state.html",
            {
                "element_id": "runner-list",
                "fragment_url": "/fragments/runners/",
                "message": "No host data yet. Start the metrics collector.",
                **_poll_context(),
            },
        )
    runner_rows = get_host_runners(host)
    return render(
        request,
        "monitor/fragments/runner_list.html",
        {"runners": runner_rows, **_poll_context()},
    )


def container_logs(request, pk: int):
    host = get_current_host()
    container = get_object_or_404(DockerContainer, pk=pk, host=host)

    try:
        client = docker.from_env(timeout=10)
        docker_container = client.containers.get(container.container_id)
        log_bytes = docker_container.logs(tail=100)
        logs = log_bytes.decode("utf-8", errors="replace")
        error = None
    except DockerException as exc:
        logger.warning("Failed to fetch logs for %s: %s", container.name, exc)
        logs = ""
        error = str(exc)

    return render(
        request,
        "monitor/fragments/container_logs.html",
        {"container": container, "logs": logs, "error": error},
    )
