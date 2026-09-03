from django.conf import settings
from django.shortcuts import render

from monitor.services.dashboard import (
    get_current_host,
    get_host_containers,
    get_host_runners,
)


def index(request):
    host = get_current_host()
    return render(
        request,
        "monitor/index.html",
        {
            "host_name": settings.HOST_NAME,
            "host": host,
            "containers": get_host_containers(host) if host else [],
            "runners": get_host_runners(host) if host else [],
        },
    )
