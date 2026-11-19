from django.conf import settings
from django.shortcuts import render

from monitor.services.dashboard import (
    build_runner_panel,
    build_section,
    configured_host_names,
)
from monitor.services.runner_jobs import HistoryFilters


def index(request):
    names = configured_host_names()
    return render(
        request,
        "monitor/dashboard.html",
        {
            "host_name": settings.HOST_NAME,
            "poll_seconds": settings.METRICS_INTERVAL_SECONDS,
            "sections": [build_section(name) for name in names],
            "show_host": len(names) > 1,
            **build_runner_panel(None, HistoryFilters.from_params(request.GET)),
        },
    )
