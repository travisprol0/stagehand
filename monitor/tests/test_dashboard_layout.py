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
    assert 'id="host-summary"' in content or "CPU" in content
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
    assert "Stagehand" in content


@pytest.mark.django_db
def test_dashboard_has_responsive_grid_classes(client, host):
    response = client.get("/")
    content = response.content.decode()

    assert "grid" in content
    assert (
        "md:grid-cols" in content
        or "lg:grid-cols" in content
        or "xl:grid-cols" in content
    )


@pytest.mark.django_db
def test_dashboard_stacks_fleet_runners_then_containers(
    client, host, host_snapshots, runner
):
    content = client.get("/").content.decode()

    fleet = content.index('id="fleet-section"')
    runners = content.index('id="runners-section"')
    containers = content.index('id="containers-section"')
    assert fleet < runners < containers
    # The hour chart is tucked behind the host row, not beside the runners.
    assert 'id="charts-section"' in content
    assert 'x-show="open"' in content
    assert "lg:col-span-2" not in content
    # Old rainbow KPI tiles are gone.
    assert "bg-indigo-50" not in content
    assert "bg-cyan-50" not in content


@pytest.mark.django_db
def test_host_row_shows_sparklines(client, host, host_snapshots):
    content = client.get("/fragments/host-summary/").content.decode()

    assert content.count('class="spark ') == 2  # CPU + memory
    assert "<polyline" in content


@pytest.mark.django_db
def test_dashboard_has_kpi_strip_and_icon_chrome(client, host, container, runner):
    response = client.get("/")
    content = response.content.decode()

    assert "CPU" in content
    assert "Memory" in content
    assert "Disk" in content
    assert "Network" in content
    assert "Refresh now" in content
    assert "Menu" not in content
    assert "Toggle dark mode" not in content


@pytest.mark.django_db
def test_dashboard_formats_memory_and_container_uptime(client, host, container):
    response = client.get("/")
    content = response.content.decode()

    assert "MB" in content or "GB" in content
    assert "up " in content
    assert "free" in content
    assert "poll " in content
