from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import docker
import httpx
import pytest
from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from monitor.admin import (
    DockerContainerAdmin,
    GitHubRunnerAdmin,
    HostAdmin,
    MetricSnapshotAdmin,
)
from monitor.collectors.base import BaseCollector
from monitor.collectors.docker import (
    DockerCollector,
    _container_health,
    _cpu_percent_from_stats,
    _memory_bytes_from_stats,
    _parse_started_at,
)
from monitor.collectors.github import (
    GitHubRunnerCollector,
    _fetch_all_runners,
    _next_page_url,
    _parse_label_names,
)
from monitor.collectors.host import (
    HostMetricsCollector,
    _network_rates,
    _read_boot_time,
    _read_disk_usage,
    _read_network_totals,
)
from monitor.management.commands.collect_metrics import Command as CollectMetricsCommand
from monitor.models import (
    DockerContainer,
    GitHubRunner,
    Host,
    MetricSnapshot,
    MetricSubject,
    get_or_create_host,
)
from monitor.services.charts import build_area, build_polyline, downsample_points
from monitor.services.github_runners import (
    github_config_issues,
    runners_endpoint,
    runners_scope_label,
)
from monitor.templatetags.monitor_extras import (
    bar_color,
    bitrate,
    duration_short,
    relative_age,
)


class _CallsSuperCollect(BaseCollector):
    def collect(self) -> None:
        super().collect()


def test_base_collector_abstract_collect():
    _CallsSuperCollect().collect()


def test_admin_disallows_add():
    site = AdminSite()
    request = RequestFactory().get("/admin/")
    for admin_cls, model in (
        (HostAdmin, Host),
        (DockerContainerAdmin, DockerContainer),
        (GitHubRunnerAdmin, GitHubRunner),
        (MetricSnapshotAdmin, MetricSnapshot),
    ):
        assert admin_cls(model, site).has_add_permission(request) is False


def test_parse_started_at_empty_and_unset():
    assert _parse_started_at(None) is None
    assert _parse_started_at("") is None
    assert _parse_started_at("0001-01-01T00:00:00Z") is None


def test_container_health_missing_and_empty_status():
    assert _container_health({}) == "none"
    assert _container_health({"State": {}}) == "none"
    assert _container_health({"State": {"Health": {}}}) == "none"


def test_cpu_percent_non_positive_system_delta_and_bad_stats():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 1},
            "system_cpu_usage": 10,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 1},
            "system_cpu_usage": 10,
        },
    }
    assert _cpu_percent_from_stats(stats) is None
    assert _cpu_percent_from_stats({}) is None
    without_online = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 2},
            "system_cpu_usage": 20,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 1},
            "system_cpu_usage": 10,
        },
    }
    assert _cpu_percent_from_stats(without_online) == pytest.approx(10.0)


def test_memory_bytes_missing_stats():
    assert _memory_bytes_from_stats({}) is None
    assert _memory_bytes_from_stats({"memory_stats": {"usage": "nope"}}) is None


@pytest.mark.django_db
def test_docker_list_containers_failure(host):
    client = MagicMock()
    client.containers.all.side_effect = docker.errors.DockerException("list failed")
    with patch("monitor.collectors.docker.docker.from_env", return_value=client):
        with patch("monitor.collectors.docker.get_or_create_host", return_value=host):
            DockerCollector().collect()
    assert DockerContainer.objects.count() == 0


@pytest.mark.django_db
def test_docker_marks_absent_when_others_listed(host):
    stale = DockerContainer.objects.create(
        host=host,
        container_id="old",
        name="old",
        image="alpine",
        status="running",
    )
    live = MagicMock()
    live.id = "new"
    live.name = "web"
    live.attrs = {
        "State": {"Status": "exited", "Health": {"Status": None}, "StartedAt": ""},
        "Config": {"Image": "nginx"},
    }
    client = MagicMock()
    client.containers.all.return_value = [live]
    with patch("monitor.collectors.docker.docker.from_env", return_value=client):
        with patch("monitor.collectors.docker.get_or_create_host", return_value=host):
            DockerCollector().collect()
    stale.refresh_from_db()
    assert stale.status == "removed"


@pytest.mark.django_db
def test_docker_stats_failure_still_upserts(host):
    container = MagicMock()
    container.id = "cid"
    container.name = "web"
    container.attrs = {
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Config": {"Image": "nginx"},
    }
    container.stats.side_effect = docker.errors.DockerException("stats failed")
    client = MagicMock()
    client.containers.all.return_value = [container]
    with patch("monitor.collectors.docker.docker.from_env", return_value=client):
        with patch("monitor.collectors.docker.get_or_create_host", return_value=host):
            DockerCollector().collect()
    row = DockerContainer.objects.get(container_id="cid")
    assert row.cpu_percent is None
    assert row.memory_bytes is None


def test_parse_label_names_strings_and_dicts():
    assert _parse_label_names(
        [{"name": "self-hosted"}, "linux", {"name": ""}, 1, None]
    ) == ["self-hosted", "linux"]


def test_next_page_url_variants():
    assert _next_page_url(None) is None
    assert _next_page_url("") is None
    assert (
        _next_page_url(
            '<https://api.github.com/r?page=2>; rel="next", '
            '<https://api.github.com/r?page=1>; rel="prev"'
        )
        == "https://api.github.com/r?page=2"
    )
    assert _next_page_url('<https://api.github.com/r>; rel="prev"') is None
    assert _next_page_url('rel="next" without-brackets') is None


def test_fetch_all_runners_follows_next_link():
    first = MagicMock()
    first.json.return_value = {"runners": [{"id": 1}]}
    first.headers = {"Link": '<https://api.example/page2>; rel="next"'}
    first.raise_for_status = MagicMock()
    second = MagicMock()
    second.json.return_value = {"runners": [{"id": 2}]}
    second.headers = {}
    second.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.side_effect = [first, second]
    runners = _fetch_all_runners(client, "https://api.example/page1")
    assert [r["id"] for r in runners] == [1, 2]


@pytest.mark.django_db
@override_settings(GITHUB_TOKEN="tok", GITHUB_ORG="", GITHUB_REPO="")
def test_github_collect_skips_without_scope(host, caplog):
    with patch("monitor.collectors.github.get_or_create_host", return_value=host):
        GitHubRunnerCollector().collect()
    assert GitHubRunner.objects.count() == 0
    assert "GITHUB_ORG" in caplog.text


@pytest.mark.django_db
@override_settings(
    GITHUB_TOKEN="test-token",
    GITHUB_ORG="my-org",
    GITHUB_REPO="",
    GITHUB_API_URL="https://api.github.com",
)
def test_github_marks_stale_when_others_returned(host):
    stale = GitHubRunner.objects.create(
        host=host,
        runner_id=99,
        name="gone",
        labels=[],
        status="idle",
        busy=True,
    )
    response = MagicMock()
    response.json.return_value = {
        "runners": [
            {
                "id": 1,
                "name": "live",
                "status": "online",
                "busy": False,
                "labels": ["linux"],
            }
        ]
    }
    response.headers = {}
    response.raise_for_status = MagicMock()
    with patch("monitor.collectors.github.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = response
        with patch("monitor.collectors.github.get_or_create_host", return_value=host):
            GitHubRunnerCollector().collect()
    stale.refresh_from_db()
    assert stale.status == "offline"
    assert stale.busy is False


def test_host_boot_disk_net_error_paths():
    with patch(
        "monitor.collectors.host.psutil.boot_time",
        side_effect=AttributeError("x"),
    ):
        assert _read_boot_time() is None
    with patch(
        "monitor.collectors.host.psutil.disk_usage",
        side_effect=TypeError("x"),
    ):
        assert _read_disk_usage() == (None, None, None)
    with patch(
        "monitor.collectors.host.psutil.net_io_counters",
        side_effect=TypeError("x"),
    ):
        assert _read_network_totals() == (None, None)
    with patch(
        "monitor.collectors.host.psutil.net_io_counters",
        return_value="not-a-dict",
    ):
        assert _read_network_totals() == (None, None)
    with patch(
        "monitor.collectors.host.psutil.net_io_counters",
        return_value={"lo": SimpleNamespace(bytes_sent=1, bytes_recv=1)},
    ):
        assert _read_network_totals() == (None, None)
    with patch(
        "monitor.collectors.host.psutil.net_io_counters",
        return_value={"eth0": SimpleNamespace(bytes_sent="bad", bytes_recv=1)},
    ):
        assert _read_network_totals() == (None, None)


def test_network_rates_non_positive_elapsed():
    now = timezone.now()
    host = SimpleNamespace(
        net_bytes_sent=10,
        net_bytes_recv=10,
        updated_at=now,
    )
    assert _network_rates(host, sent=20, recv=20, now=now) == (None, None)
    assert _network_rates(host, sent=None, recv=20, now=now) == (None, None)


@pytest.mark.django_db
def test_host_collect_created_log(psutil_mocks, caplog):
    with patch("monitor.collectors.host.socket.gethostname", return_value="test-host"):
        HostMetricsCollector().collect()
    assert "Created host record" in caplog.text


@pytest.mark.django_db
def test_check_github_runners_http_status_errors(monkeypatch):
    def raise_status(status, body="denied"):
        request = httpx.Request("GET", "https://api.github.com")
        response = httpx.Response(status, text=body, request=request)
        raise httpx.HTTPStatusError(
            "err",
            request=request,
            response=response,
        )

    for status in (401, 403, 404, 500):
        monkeypatch.setattr(
            "monitor.management.commands.check_github_runners._fetch_all_runners",
            lambda *_a, status=status: raise_status(status),
        )
        with override_settings(
            GITHUB_TOKEN="t",
            GITHUB_ORG="",
            GITHUB_REPO="owner/repo",
            GITHUB_API_URL="https://api.github.com",
        ):
            with pytest.raises(CommandError, match=f"HTTP {status}"):
                call_command("check_github_runners")


@pytest.mark.django_db
def test_check_github_runners_http_status_empty_body(monkeypatch):
    def raise_status(*_a, **_k):
        request = httpx.Request("GET", "https://api.github.com")
        response = httpx.Response(401, text="", request=request)
        raise httpx.HTTPStatusError("err", request=request, response=response)

    monkeypatch.setattr(
        "monitor.management.commands.check_github_runners._fetch_all_runners",
        raise_status,
    )
    with override_settings(
        GITHUB_TOKEN="t",
        GITHUB_ORG="",
        GITHUB_REPO="owner/repo",
        GITHUB_API_URL="https://api.github.com",
    ):
        with pytest.raises(CommandError, match="HTTP 401"):
            call_command("check_github_runners")


@pytest.mark.django_db
def test_check_github_runners_http_error(monkeypatch):
    monkeypatch.setattr(
        "monitor.management.commands.check_github_runners._fetch_all_runners",
        lambda *_a, **_k: (_ for _ in ()).throw(httpx.HTTPError("timeout")),
    )
    with override_settings(
        GITHUB_TOKEN="t",
        GITHUB_ORG="",
        GITHUB_REPO="owner/repo",
        GITHUB_API_URL="https://api.github.com",
    ):
        with pytest.raises(CommandError, match="request failed"):
            call_command("check_github_runners")


@pytest.mark.django_db
def test_check_github_runners_empty_list(monkeypatch, capsys):
    monkeypatch.setattr(
        "monitor.management.commands.check_github_runners._fetch_all_runners",
        lambda *_a, **_k: [],
    )
    with override_settings(
        GITHUB_TOKEN="t",
        GITHUB_ORG="",
        GITHUB_REPO="owner/repo",
        GITHUB_API_URL="https://api.github.com",
    ):
        call_command("check_github_runners")
    out = capsys.readouterr().out
    assert "0 runners" in out


@pytest.mark.django_db
def test_check_github_runners_string_labels(monkeypatch, capsys):
    monkeypatch.setattr(
        "monitor.management.commands.check_github_runners._fetch_all_runners",
        lambda *_a, **_k: [
            {
                "id": 1,
                "name": "box",
                "status": "online",
                "busy": True,
                "labels": ["self-hosted", {"name": "linux"}],
            }
        ],
    )
    with override_settings(
        GITHUB_TOKEN="t",
        GITHUB_ORG="",
        GITHUB_REPO="owner/repo",
        GITHUB_API_URL="https://api.github.com",
    ):
        call_command("check_github_runners")
    out = capsys.readouterr().out
    assert "box" in out
    assert "linux" in out


def test_collect_metrics_handle_signal():
    command = CollectMetricsCommand()
    command._handle_signal(15, None)
    assert command._running is False


@pytest.mark.django_db
def test_model_str_and_hostname_update():
    host = Host.objects.create(name="talos", hostname="old-host")
    assert str(host) == "talos"
    container = DockerContainer.objects.create(
        host=host,
        container_id="abc",
        name="web",
        image="nginx",
        status="running",
    )
    assert str(container) == "web"
    runner = GitHubRunner.objects.create(
        host=host,
        runner_id=1,
        name="r1",
        status="idle",
    )
    assert str(runner) == "r1"
    snap_host = MetricSnapshot.objects.create(
        recorded_at=timezone.now(),
        subject_type=MetricSubject.HOST,
        host=host,
    )
    assert "host:talos@" in str(snap_host)
    snap_ctr = MetricSnapshot.objects.create(
        recorded_at=timezone.now(),
        subject_type=MetricSubject.CONTAINER,
        host=host,
        container=container,
    )
    assert "container:web@" in str(snap_ctr)
    with patch("monitor.models.socket.gethostname", return_value="new-host"):
        updated = get_or_create_host()
    assert updated.hostname == "new-host"


def test_downsample_below_max_after_threshold():
    points = list(range(210))
    assert downsample_points(points, max_points=250) == points


def test_build_polyline_and_area_short_series():
    assert build_polyline([]) == ""
    assert build_polyline([1.0]) == ""
    assert build_area([1.0]) == ""
    assert " " in build_polyline([0.0, None, 50.0])


@override_settings(GITHUB_ORG="", GITHUB_REPO="", GITHUB_API_URL="https://api.github.com")
def test_github_runner_helpers_unset():
    assert runners_endpoint() is None
    assert "unset" in runners_scope_label()


@override_settings(
    GITHUB_ORG="acme",
    GITHUB_REPO="owner/repo",
    GITHUB_TOKEN="t",
    GITHUB_API_URL="https://api.github.com",
)
def test_github_config_both_org_and_repo():
    assert "organization 'acme'" == runners_scope_label()
    issues = github_config_issues()
    assert any("Both GITHUB_ORG" in item for item in issues)


@override_settings(
    GITHUB_ORG="",
    GITHUB_REPO="not-a-pair",
    GITHUB_TOKEN="t",
    GITHUB_API_URL="https://api.github.com",
)
def test_github_config_bad_repo_slug():
    issues = github_config_issues()
    assert any("owner/repo" in item for item in issues)
    with pytest.raises(ValueError):
        runners_endpoint()


@override_settings(
    GITHUB_ORG="",
    GITHUB_REPO="owner/repo",
    GITHUB_API_URL="https://api.github.com",
)
def test_runners_scope_label_repo():
    assert "repository 'owner/repo'" == runners_scope_label()


def test_import_hosts_service():
    import monitor.services.hosts as hosts_service

    assert hosts_service.get_or_create_host is get_or_create_host


def test_template_filters_remaining_branches():
    assert bar_color("nope") == bar_color(None)
    assert relative_age(None) == "—"
    assert relative_age(timezone.now() + timedelta(seconds=30)).endswith("ago")
    assert relative_age(timezone.now() - timedelta(minutes=5)) == "5m ago"
    assert relative_age(timezone.now() - timedelta(hours=3)) == "3h ago"
    assert relative_age(timezone.now() - timedelta(days=3)) == "3d ago"
    assert duration_short(None) == "—"
    assert duration_short(timezone.now() + timedelta(seconds=5)) == "0s"
    assert duration_short(timezone.now() - timedelta(minutes=9)) == "9m"
    assert duration_short(timezone.now() - timedelta(hours=2, minutes=1)) == "2h 1m"
    assert duration_short(timezone.now() - timedelta(days=2, minutes=10)) == "2d 10m"
    assert duration_short(timezone.now() - timedelta(days=2)) == "2d"
    assert duration_short(timezone.now() - timedelta(seconds=8)) == "8s"
    assert bar_color(object()) == bar_color(None)
    assert "GB/s" in bitrate(5 * 1024**3)
    assert bitrate(200 * 1024) == "200 KB/s"
    assert bitrate(50.0) == "50 B/s"


@pytest.fixture
def client():
    return Client()


@pytest.fixture(autouse=True)
def allow_testserver(settings):
    settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]


@pytest.mark.django_db
def test_health_ok(client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.content == b"OK"


@pytest.mark.django_db
def test_fragments_empty_host(client):
    assert b"No host data" in client.get("/fragments/containers/").content
    assert b"No host data" in client.get("/fragments/runners/").content


@pytest.mark.django_db
def test_container_row_unknown(client, host):
    response = client.get("/fragments/container/99999/row/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_container_row(client, host, container):
    response = client.get(f"/fragments/container/{container.pk}/row/")
    assert response.status_code == 200
    assert b"web" in response.content


@pytest.mark.django_db
def test_container_logs_success(client, host, container):
    docker_container = MagicMock()
    docker_container.logs.return_value = b"hello logs"
    docker_client = MagicMock()
    docker_client.containers.get.return_value = docker_container
    with patch(
        "monitor.views.fragments.docker.from_env",
        return_value=docker_client,
    ):
        response = client.get(f"/fragments/container/{container.pk}/logs/")
    assert response.status_code == 200
    assert b"hello logs" in response.content
