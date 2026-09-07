from django.conf import settings
from django.shortcuts import render

from monitor.services.charts import get_host_chart_data
from monitor.services.dashboard import (
    attention_items,
    get_current_host,
    get_host_containers,
    get_host_runners,
    summarize_containers,
    summarize_runners,
)


def index(request):
    host = get_current_host()
    poll_seconds = settings.METRICS_INTERVAL_SECONDS
    containers = get_host_containers(host) if host else []
    runners = get_host_runners(host) if host else []
    return render(
        request,
        "monitor/dashboard.html",
        {
            "host_name": settings.HOST_NAME,
            "host": host,
            "containers": containers,
            "runners": runners,
            "container_stats": summarize_containers(host) if host else None,
            "runner_stats": summarize_runners(host) if host else None,
            "poll_seconds": poll_seconds,
            "chart": get_host_chart_data(host) if host else None,
            "attention": attention_items(host) if host else [],
        },
    )
