from django.conf import settings
from django.shortcuts import render

from monitor.services.dashboard import build_section, configured_host_names


def index(request):
    return render(
        request,
        "monitor/dashboard.html",
        {
            "host_name": settings.HOST_NAME,
            "poll_seconds": settings.METRICS_INTERVAL_SECONDS,
            "sections": [build_section(name) for name in configured_host_names()],
        },
    )
