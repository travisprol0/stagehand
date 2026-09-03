import pytest
from django.test import Client, override_settings


@pytest.fixture
def client():
    return Client()


@pytest.fixture(autouse=True)
def allow_testserver(settings):
    settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]


@pytest.mark.django_db
def test_dashboard_includes_htmx_fragment_urls(client, host):
    response = client.get("/")
    content = response.content.decode()

    assert 'hx-get="/fragments/host-summary/"' in content
    assert 'hx-get="/fragments/containers/"' in content
    assert 'hx-get="/fragments/runners/"' in content


@pytest.mark.django_db
def test_dashboard_polled_regions_have_stable_ids(client, host):
    response = client.get("/")
    content = response.content.decode()

    assert 'id="host-summary"' in content
    assert 'id="container-table"' in content
    assert 'id="runner-list"' in content


@pytest.mark.django_db
@override_settings(METRICS_INTERVAL_SECONDS=12)
def test_dashboard_htmx_trigger_uses_poll_interval(client, host):
    response = client.get("/")
    content = response.content.decode()

    assert "every 12s" in content


@pytest.mark.django_db
def test_dashboard_includes_alpine_dark_mode_and_modal(client, host, container):
    response = client.get("/")
    content = response.content.decode()

    assert "x-data" in content
    assert "toggleDark" in content or "dark" in content
    assert "log-modal" in content
    assert "log-modal-body" in content


@pytest.mark.django_db
def test_container_row_includes_logs_button(client, host, container):
    response = client.get("/")
    content = response.content.decode()

    assert f"/fragments/container/{container.pk}/logs/" in content
    assert 'hx-target="#log-modal-body"' in content


@pytest.mark.django_db
def test_dashboard_loads_htmx_and_alpine_cdn(client, host):
    response = client.get("/")
    content = response.content.decode()

    assert "unpkg.com/htmx" in content or "htmx.org" in content
    assert "alpinejs" in content


@pytest.mark.django_db
def test_polled_fragments_do_not_use_load_trigger(client, host, host_snapshots):
    """load on swapped outerHTML re-fires every swap and causes a request storm."""
    urls = (
        "/fragments/host-summary/",
        "/fragments/containers/",
        "/fragments/runners/",
        "/fragments/charts/host/",
    )

    for url in urls:
        content = client.get(url).content.decode()
        assert 'hx-trigger="load' not in content
        assert "every " in content and "s" in content
