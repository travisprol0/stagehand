from unittest.mock import patch

import docker
import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client()


@pytest.fixture(autouse=True)
def allow_testserver(settings):
    settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]


@pytest.mark.django_db
def test_host_summary_fragment(client, host):
    response = client.get("/fragments/host-summary/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    content = response.content.decode()
    assert "42.5" in content
    assert "61" in content
    assert "talos" in content


@pytest.mark.django_db
def test_containers_fragment(client, host, container):
    response = client.get("/fragments/containers/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "web" in content
    assert "nginx:latest" in content
    assert "running" in content


@pytest.mark.django_db
def test_runners_fragment(client, host, runner):
    response = client.get("/fragments/runners/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "talos-runner-1" in content
    assert "idle" in content


@pytest.mark.django_db
def test_host_summary_empty_state(client):
    response = client.get("/fragments/host-summary/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "No host data" in content


@pytest.mark.django_db
def test_container_logs_docker_failure(client, host, container):
    with patch(
        "monitor.views.fragments.docker.from_env",
        side_effect=docker.errors.DockerException("socket unavailable"),
    ):
        response = client.get(f"/fragments/container/{container.pk}/logs/")

    assert response.status_code == 200
    assert b"socket unavailable" in response.content


@pytest.mark.django_db
def test_index_includes_fragment_placeholders(client, host):
    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="host-summary"' in content
    assert 'id="container-table"' in content
    assert 'id="runner-list"' in content


@pytest.mark.django_db
def test_containers_empty_state(client, host):
    response = client.get("/fragments/containers/")

    assert response.status_code == 200
    assert b"No containers" in response.content
