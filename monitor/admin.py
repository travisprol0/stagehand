from django.contrib import admin

from monitor.models import DockerContainer, GitHubRunner, Host, MetricSnapshot


@admin.register(Host)
class HostAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "hostname",
        "cpu_percent",
        "memory_percent",
        "updated_at",
    )
    search_fields = ("name", "hostname")
    readonly_fields = (
        "name",
        "hostname",
        "cpu_percent",
        "memory_percent",
        "memory_used_bytes",
        "memory_total_bytes",
        "load_avg_1",
        "load_avg_5",
        "load_avg_15",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(DockerContainer)
class DockerContainerAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "host",
        "status",
        "health",
        "cpu_percent",
        "memory_bytes",
        "updated_at",
    )
    list_filter = ("status", "health", "host")
    search_fields = ("name", "container_id", "image")
    readonly_fields = (
        "host",
        "container_id",
        "name",
        "image",
        "status",
        "health",
        "cpu_percent",
        "memory_bytes",
        "started_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(GitHubRunner)
class GitHubRunnerAdmin(admin.ModelAdmin):
    list_display = ("name", "host", "status", "busy", "updated_at")
    list_filter = ("status", "busy", "host")
    search_fields = ("name",)
    readonly_fields = (
        "host",
        "runner_id",
        "name",
        "labels",
        "status",
        "busy",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(MetricSnapshot)
class MetricSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "recorded_at",
        "subject_type",
        "host",
        "container",
        "cpu_percent",
        "memory_percent",
    )
    list_filter = ("subject_type", "host")
    readonly_fields = (
        "recorded_at",
        "subject_type",
        "host",
        "container",
        "cpu_percent",
        "memory_percent",
        "memory_bytes",
    )

    def has_add_permission(self, request):
        return False
