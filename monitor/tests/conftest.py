"""Shared pytest fixtures for monitor tests."""

import pytest
from django.utils import timezone

from monitor.models import (
    DockerContainer,
    GitHubRunner,
    Host,
    MetricSnapshot,
    MetricSubject,
    RunnerStatus,
)


@pytest.fixture
def host(db):
    return Host.objects.create(
        name="talos",
        hostname="talos.local",
        cpu_percent=42.5,
        memory_percent=61.0,
        memory_used_bytes=8_000_000_000,
        memory_total_bytes=16_000_000_000,
        load_avg_1=1.2,
        load_avg_5=0.9,
        load_avg_15=0.7,
    )


@pytest.fixture
def container(db, host):
    return DockerContainer.objects.create(
        host=host,
        container_id="abc123deadbeef",
        name="web",
        image="nginx:latest",
        status="running",
        health="healthy",
        cpu_percent=5.0,
        memory_bytes=128_000_000,
    )


@pytest.fixture
def runner(db, host):
    return GitHubRunner.objects.create(
        host=host,
        runner_id=42,
        name="talos-runner-1",
        labels=["self-hosted", "linux"],
        status=RunnerStatus.IDLE,
        busy=False,
    )


@pytest.fixture
def host_snapshots(db, host):
    now = timezone.now()
    return [
        MetricSnapshot.objects.create(
            recorded_at=now - timezone.timedelta(minutes=30),
            subject_type=MetricSubject.HOST,
            host=host,
            cpu_percent=10.0,
            memory_percent=50.0,
        ),
        MetricSnapshot.objects.create(
            recorded_at=now - timezone.timedelta(minutes=10),
            subject_type=MetricSubject.HOST,
            host=host,
            cpu_percent=25.0,
            memory_percent=55.0,
        ),
    ]


@pytest.fixture
def container_snapshots(db, host, container):
    now = timezone.now()
    return [
        MetricSnapshot.objects.create(
            recorded_at=now - timezone.timedelta(minutes=5),
            subject_type=MetricSubject.CONTAINER,
            host=host,
            container=container,
            cpu_percent=15.0,
            memory_bytes=100_000_000,
        ),
    ]
