import socket

from django.conf import settings
from django.db import models
from django.utils import timezone


class Host(models.Model):
    name = models.CharField(max_length=64, unique=True)
    hostname = models.CharField(max_length=255)
    cpu_percent = models.FloatField(null=True, blank=True)
    memory_percent = models.FloatField(null=True, blank=True)
    memory_used_bytes = models.BigIntegerField(null=True, blank=True)
    memory_total_bytes = models.BigIntegerField(null=True, blank=True)
    load_avg_1 = models.FloatField(null=True, blank=True)
    load_avg_5 = models.FloatField(null=True, blank=True)
    load_avg_15 = models.FloatField(null=True, blank=True)
    boot_time = models.DateTimeField(null=True, blank=True)
    disk_percent = models.FloatField(null=True, blank=True)
    disk_used_bytes = models.BigIntegerField(null=True, blank=True)
    disk_total_bytes = models.BigIntegerField(null=True, blank=True)
    net_bytes_sent = models.BigIntegerField(null=True, blank=True)
    net_bytes_recv = models.BigIntegerField(null=True, blank=True)
    net_sent_bps = models.FloatField(null=True, blank=True)
    net_recv_bps = models.FloatField(null=True, blank=True)
    cpu_count = models.IntegerField(null=True, blank=True)
    reachable = models.BooleanField(default=True)
    last_error = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DockerContainer(models.Model):
    host = models.ForeignKey(Host, on_delete=models.CASCADE, related_name="containers")
    container_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    image = models.CharField(max_length=512)
    status = models.CharField(max_length=32)
    health = models.CharField(max_length=32, blank=True, default="none")
    cpu_percent = models.FloatField(null=True, blank=True)
    memory_bytes = models.BigIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    restart_count = models.IntegerField(default=0)
    exit_code = models.IntegerField(null=True, blank=True)
    compose_project = models.CharField(max_length=255, blank=True)
    ports = models.CharField(max_length=512, blank=True)
    state_error = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["host", "container_id"],
                name="uniq_container_per_host",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class RunnerStatus(models.TextChoices):
    IDLE = "idle", "Idle"
    ACTIVE = "active", "Active"
    OFFLINE = "offline", "Offline"


class GitHubRunner(models.Model):
    host = models.ForeignKey(Host, on_delete=models.CASCADE, related_name="runners")
    runner_id = models.BigIntegerField()
    name = models.CharField(max_length=255)
    labels = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=RunnerStatus.choices)
    busy = models.BooleanField(default=False)
    current_job_name = models.CharField(max_length=255, blank=True)
    current_workflow_name = models.CharField(max_length=255, blank=True)
    current_repository = models.CharField(max_length=255, blank=True)
    current_html_url = models.URLField(max_length=512, blank=True)
    current_started_at = models.DateTimeField(null=True, blank=True)
    current_head_branch = models.CharField(max_length=255, blank=True)
    current_pr_number = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["host", "runner_id"],
                name="uniq_runner_per_host",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class RunnerJob(models.Model):
    """One GitHub Actions job that ran (or is waiting to run) on our runners.

    `created_at` is when GitHub queued the job, `started_at` when a runner
    picked it up — the gap is the queue wait.
    """

    github_job_id = models.BigIntegerField(unique=True)
    run_id = models.BigIntegerField(db_index=True)
    host = models.ForeignKey(
        Host,
        on_delete=models.SET_NULL,
        related_name="jobs",
        null=True,
        blank=True,
    )
    runner_id = models.BigIntegerField(null=True, blank=True)
    runner_name = models.CharField(max_length=255, blank=True)
    repository = models.CharField(max_length=255)
    workflow_name = models.CharField(max_length=255, blank=True)
    job_name = models.CharField(max_length=255, blank=True)
    head_branch = models.CharField(max_length=255, blank=True)
    pr_number = models.PositiveIntegerField(null=True, blank=True)
    html_url = models.URLField(max_length=512, blank=True)
    status = models.CharField(max_length=32)
    conclusion = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["started_at"], name="runnerjob_started_idx"),
            models.Index(fields=["status"], name="runnerjob_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.workflow_name}/{self.job_name}@{self.runner_name or '?'}"

    @property
    def queue_seconds(self) -> float | None:
        if self.created_at is None or self.started_at is None or not self.runner_name:
            return None
        return max(0.0, (self.started_at - self.created_at).total_seconds())

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.completed_at is None:
            return None
        return max(0.0, (self.completed_at - self.started_at).total_seconds())


class MetricSubject(models.TextChoices):
    HOST = "host", "Host"
    CONTAINER = "container", "Container"


class MetricSnapshotQuerySet(models.QuerySet):
    def for_host(self, host: Host, *, minutes: int = 60):
        since = timezone.now() - timezone.timedelta(minutes=minutes)
        return self.filter(
            host=host,
            subject_type=MetricSubject.HOST,
            recorded_at__gte=since,
        ).order_by("recorded_at")

    def for_container(self, container: DockerContainer, *, minutes: int = 60):
        since = timezone.now() - timezone.timedelta(minutes=minutes)
        return self.filter(
            container=container,
            subject_type=MetricSubject.CONTAINER,
            recorded_at__gte=since,
        ).order_by("recorded_at")


class MetricSnapshot(models.Model):
    recorded_at = models.DateTimeField(db_index=True)
    subject_type = models.CharField(max_length=16, choices=MetricSubject.choices)
    host = models.ForeignKey(Host, on_delete=models.CASCADE, related_name="snapshots")
    container = models.ForeignKey(
        DockerContainer,
        on_delete=models.CASCADE,
        related_name="snapshots",
        null=True,
        blank=True,
    )
    cpu_percent = models.FloatField(null=True, blank=True)
    memory_percent = models.FloatField(null=True, blank=True)
    memory_bytes = models.BigIntegerField(null=True, blank=True)
    disk_percent = models.FloatField(null=True, blank=True)
    net_sent_bps = models.FloatField(null=True, blank=True)
    net_recv_bps = models.FloatField(null=True, blank=True)

    objects = MetricSnapshotQuerySet.as_manager()

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [
            models.Index(
                fields=["subject_type", "host", "recorded_at"],
                name="metrics_host_time_idx",
            ),
            models.Index(
                fields=["container", "recorded_at"],
                name="metrics_container_time_idx",
                condition=models.Q(container__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        target = self.container.name if self.container_id else self.host.name
        return f"{self.subject_type}:{target}@{self.recorded_at:%Y-%m-%d %H:%M:%S}"


def get_or_create_host() -> Host:
    hostname = socket.gethostname()
    host, _ = Host.objects.get_or_create(
        name=settings.HOST_NAME,
        defaults={"hostname": hostname},
    )
    if host.hostname != hostname:
        host.hostname = hostname
        host.save(update_fields=["hostname", "updated_at"])
    return host
