from django.test import TestCase
from django.utils import timezone

from monitor.models import (
    DockerContainer,
    GitHubRunner,
    Host,
    MetricSnapshot,
    MetricSubject,
    RunnerStatus,
    get_or_create_host,
)


class HostModelTests(TestCase):
    def test_get_or_create_host_uses_settings_name(self):
        host = get_or_create_host()
        self.assertEqual(host.name, "talos")
        self.assertTrue(host.hostname)

    def test_host_name_unique(self):
        Host.objects.create(name="talos", hostname="a")
        with self.assertRaises(Exception):
            Host.objects.create(name="talos", hostname="b")


class DockerContainerModelTests(TestCase):
    def setUp(self):
        self.host = Host.objects.create(name="talos", hostname="talos")

    def test_unique_container_per_host(self):
        DockerContainer.objects.create(
            host=self.host,
            container_id="abc123",
            name="web",
            image="nginx:latest",
            status="running",
        )
        with self.assertRaises(Exception):
            DockerContainer.objects.create(
                host=self.host,
                container_id="abc123",
                name="web-dup",
                image="nginx:latest",
                status="exited",
            )


class MetricSnapshotQueryTests(TestCase):
    def setUp(self):
        self.host = Host.objects.create(name="talos", hostname="talos")
        self.container = DockerContainer.objects.create(
            host=self.host,
            container_id="abc123",
            name="web",
            image="nginx:latest",
            status="running",
        )
        now = timezone.now()
        MetricSnapshot.objects.create(
            recorded_at=now - timezone.timedelta(minutes=30),
            subject_type=MetricSubject.HOST,
            host=self.host,
            cpu_percent=10.0,
        )
        MetricSnapshot.objects.create(
            recorded_at=now - timezone.timedelta(minutes=90),
            subject_type=MetricSubject.HOST,
            host=self.host,
            cpu_percent=5.0,
        )
        MetricSnapshot.objects.create(
            recorded_at=now - timezone.timedelta(minutes=10),
            subject_type=MetricSubject.CONTAINER,
            host=self.host,
            container=self.container,
            cpu_percent=20.0,
        )

    def test_host_snapshots_last_hour(self):
        rows = MetricSnapshot.objects.for_host(self.host, minutes=60)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().cpu_percent, 10.0)

    def test_container_snapshots_last_hour(self):
        rows = MetricSnapshot.objects.for_container(self.container, minutes=60)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().cpu_percent, 20.0)


class GitHubRunnerModelTests(TestCase):
    def setUp(self):
        self.host = Host.objects.create(name="talos", hostname="talos")

    def test_create_runner(self):
        runner = GitHubRunner.objects.create(
            host=self.host,
            runner_id=42,
            name="talos-runner",
            labels=["self-hosted", "linux"],
            status=RunnerStatus.IDLE,
        )
        self.assertEqual(runner.status, RunnerStatus.IDLE)
