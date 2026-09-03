import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client()


@pytest.fixture(autouse=True)
def allow_testserver(settings):
    settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]


@pytest.mark.django_db
def test_dashboard_returns_html(client, host):
    response = client.get("/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")


@pytest.mark.django_db
def test_dashboard_contains_section_landmarks(client, host, container, runner):
    response = client.get("/")
    content = response.content.decode()

    assert "<main" in content
    assert 'id="host-section"' in content or "Host" in content
    assert 'id="containers-section"' in content or "Containers" in content
    assert 'id="runners-section"' in content or "Runners" in content


@pytest.mark.django_db
def test_dashboard_contains_progress_bars(client, host, container):
    response = client.get("/")
    content = response.content.decode()

    assert 'role="progressbar"' in content
    assert "42.5" in content
    assert "61" in content


@pytest.mark.django_db
def test_dashboard_loads_tailwind_cdn(client, host):
    response = client.get("/")
    content = response.content.decode()

    assert "cdn.tailwindcss.com" in content
    assert "Talos Monitor" in content


@pytest.mark.django_db
def test_dashboard_has_responsive_grid_classes(client, host):
    response = client.get("/")
    content = response.content.decode()

    assert "grid" in content
    assert "md:grid-cols" in content or "lg:grid-cols" in content
