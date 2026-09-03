from django.urls import path

from monitor.views import dashboard, fragments, health

urlpatterns = [
    path("", dashboard.index, name="index"),
    path("health/", health.health, name="health"),
    path(
        "fragments/host-summary/",
        fragments.host_summary,
        name="fragment-host-summary",
    ),
    path("fragments/containers/", fragments.containers, name="fragment-containers"),
    path(
        "fragments/container/<int:pk>/row/",
        fragments.container_row,
        name="fragment-container-row",
    ),
    path("fragments/runners/", fragments.runners, name="fragment-runners"),
    path(
        "fragments/container/<int:pk>/logs/",
        fragments.container_logs,
        name="fragment-container-logs",
    ),
]
