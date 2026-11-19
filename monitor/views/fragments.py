import logging

import docker
from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from docker.errors import DockerException

from monitor.models import DockerContainer
from monitor.services.dashboard import build_section, configured_host_names
from monitor.services.remote import docker_ssh_url, remote_ssh_target

logger = logging.getLogger(__name__)


def _poll_context():
    return {"poll_seconds": settings.METRICS_INTERVAL_SECONDS}


def _requested_section(request) -> dict:
    """Section for ?host=<name>; defaults to the local host. Unknown → 404."""
    name = request.GET.get("host") or settings.HOST_NAME
    if name not in configured_host_names():
        raise Http404("Unknown host")
    return build_section(name)


def _empty(request, *, section, element_id, fragment, message):
    return render(
        request,
        "monitor/fragments/polled_empty_state.html",
        {
            "element_id": f"{section['prefix']}{element_id}",
            "fragment_url": f"/fragments/{fragment}/{section['qs']}",
            "message": message,
            **_poll_context(),
        },
    )


NO_HOST_MESSAGE = "No host data yet. Start the metrics collector."


def host_summary(request):
    section = _requested_section(request)
    if section["host"] is None:
        return _empty(
            request,
            section=section,
            element_id="host-summary",
            fragment="host-summary",
            message=NO_HOST_MESSAGE,
        )
    return render(
        request,
        "monitor/fragments/host_summary.html",
        {
            "host": section["host"],
            "prefix": section["prefix"],
            "qs": section["qs"],
            "container_stats": section["container_stats"],
            "runner_stats": section["runner_stats"],
            "attention": section["attention"],
            **_poll_context(),
        },
    )


def containers(request):
    section = _requested_section(request)
    if section["host"] is None:
        return _empty(
            request,
            section=section,
            element_id="container-table",
            fragment="containers",
            message=NO_HOST_MESSAGE,
        )
    return render(
        request,
        "monitor/fragments/container_table.html",
        {
            "containers": section["containers"],
            "container_stats": section["container_stats"],
            "prefix": section["prefix"],
            "qs": section["qs"],
            **_poll_context(),
        },
    )


def container_row(request, pk: int):
    container = get_object_or_404(DockerContainer.objects.select_related("host"), pk=pk)
    if container.host.name not in configured_host_names():
        raise Http404("Unknown host")
    return render(
        request,
        "monitor/fragments/container_row.html",
        {"container": container},
    )


def runners(request):
    section = _requested_section(request)
    if section["host"] is None:
        return _empty(
            request,
            section=section,
            element_id="runner-list",
            fragment="runners",
            message=NO_HOST_MESSAGE,
        )
    return render(
        request,
        "monitor/fragments/runner_list.html",
        {
            "runners": section["runners"],
            "runner_stats": section["runner_stats"],
            "prefix": section["prefix"],
            "qs": section["qs"],
            **_poll_context(),
        },
    )


def chart_host_metrics(request):
    section = _requested_section(request)
    if section["host"] is None:
        return _empty(
            request,
            section=section,
            element_id="host-chart",
            fragment="charts/host",
            message=NO_HOST_MESSAGE,
        )
    return render(
        request,
        "monitor/fragments/host_chart.html",
        {
            "chart": section["chart"],
            "prefix": section["prefix"],
            "qs": section["qs"],
            **_poll_context(),
        },
    )


def container_logs(request, pk: int):
    container = get_object_or_404(DockerContainer.objects.select_related("host"), pk=pk)
    if container.host.name not in configured_host_names():
        raise Http404("Unknown host")

    try:
        target = remote_ssh_target(container.host.name)
        if target is None:
            client = docker.from_env(timeout=10)
        else:
            client = docker.DockerClient(base_url=docker_ssh_url(target), timeout=10)
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
