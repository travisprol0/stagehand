"""Multi-host monitoring: config, SSH host probe, per-host Docker, runner mapping."""

from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from config.settings import _remote_hosts_from_env
from monitor.collectors.docker import docker_client_for
from monitor.collectors.github import host_for_runner_name
from monitor.collectors.remote import (
    RemoteHostMetricsCollector,
    cpu_percent_from_stat,
    parse_probe,
)
from monitor.models import DockerContainer, GitHubRunner, Host, RunnerStatus
from monitor.services.remote import RemoteProbeError

PROBE_OUTPUT = """\
LOADAVG
0.50 0.40 0.30 1/200 999
UPTIME
3600.00 7000.00
MEMINFO
MemTotal:        3984000 kB
MemAvailable:    1992000 kB
CPU1
cpu  100 0 100 800 0 0 0 0 0 0
sleep
CPU2
cpu  150 0 150 900 0 0 0 0 0 0
NET
Inter-|   Receive
 face |bytes
    lo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0
  wlan0: 1000 1 0 0 0 0 0 0 2000 1 0 0 0 0 0 0
DISK
/dev/sda1 100000 25000 75000 25% /
NPROC
4
"""


@pytest.fixture
def remote_settings(settings):
    settings.REMOTE_HOSTS = {"hermes": "twelvetwo@192.168.50.65"}
    return settings


def test_remote_hosts_empty_by_default():
    assert _remote_hosts_from_env({}) == {}


def test_remote_hosts_parse_names_and_targets():
    env = {
        "REMOTE_HOSTS": "hermes",
        "REMOTE_HERMES_SSH": "twelvetwo@192.168.50.65",
    }
    assert _remote_hosts_from_env(env) == {"hermes": "twelvetwo@192.168.50.65"}


def test_remote_host_requires_ssh_target():
    with pytest.raises(ImproperlyConfigured, match="REMOTE_HERMES_SSH"):
        _remote_hosts_from_env({"REMOTE_HOSTS": "hermes"})


def test_remote_host_rejects_local_name_and_bad_names():
    with pytest.raises(ImproperlyConfigured):
        _remote_hosts_from_env({"REMOTE_HOSTS": "talos", "REMOTE_TALOS_SSH": "u@h"})
    with pytest.raises(ImproperlyConfigured):
        _remote_hosts_from_env(
            {"REMOTE_HOSTS": "bad name", "REMOTE_BAD NAME_SSH": "u@h"}
        )


def test_cpu_percent_from_two_stat_samples():
    first = "cpu  100 0 100 800 0 0 0 0 0 0"
    second = "cpu  150 0 150 900 0 0 0 0 0 0"
    # 200 ticks elapsed, 100 idle → 50% busy
    assert cpu_percent_from_stat(first, second) == pytest.approx(50.0)


def test_parse_probe_extracts_host_metrics():
    now = timezone.now()
    sample = parse_probe(PROBE_OUTPUT, now=now)

    assert sample.load == (0.5, 0.4, 0.3)
    assert sample.memory_total == 3984000 * 1024
    assert sample.memory_used == (3984000 - 1992000) * 1024
    assert sample.cpu_count == 4
    assert sample.disk == (25.0, 25000, 100000)
    assert sample.net_recv == 1000  # lo excluded
    assert sample.net_sent == 2000
    assert sample.cpu_percent == pytest.approx(50.0)
    assert (now - sample.boot_time).total_seconds() == pytest.approx(3600, abs=2)


def test_parse_probe_rejects_garbage():
    with pytest.raises(RemoteProbeError):
        parse_probe("not a probe", now=timezone.now())


@pytest.mark.django_db
def test_remote_collector_stores_hermes_metrics(remote_settings):
    with patch("monitor.collectors.remote.run_probe", return_value=PROBE_OUTPUT):
        RemoteHostMetricsCollector().run()

    hermes = Host.objects.get(name="hermes")
    assert hermes.reachable is True
    assert hermes.last_error == ""
    assert hermes.cpu_count == 4
    assert hermes.disk_percent == 25.0
    assert hermes.snapshots.count() == 1


@pytest.mark.django_db
def test_remote_collector_marks_unreachable_and_keeps_last_good(remote_settings):
    with patch("monitor.collectors.remote.run_probe", return_value=PROBE_OUTPUT):
        RemoteHostMetricsCollector().run()
    good = Host.objects.get(name="hermes")
    last_seen = good.updated_at

    with patch(
        "monitor.collectors.remote.run_probe",
        side_effect=RemoteProbeError("timed out"),
    ):
        RemoteHostMetricsCollector().run()

    hermes = Host.objects.get(name="hermes")
    assert hermes.reachable is False
    assert hermes.last_error == "timed out"
    assert hermes.updated_at == last_seen
    assert hermes.cpu_percent is not None  # last good value kept


@pytest.mark.django_db
def test_unreachable_host_raises_attention_item(remote_settings, client):
    Host.objects.create(
        name="hermes", hostname="hermes", reachable=False, last_error="no route to host"
    )
    response = client.get("/fragments/host-summary/?host=hermes")
    content = response.content.decode()
    assert "hermes unreachable" in content
    assert "no route to host" in content


@pytest.mark.django_db
def test_docker_client_for_remote_host_uses_ssh_url(remote_settings):
    host = Host.objects.create(name="hermes", hostname="hermes")
    with patch("monitor.collectors.docker.docker.DockerClient") as client_cls:
        docker_client_for(host)
    client_cls.assert_called_once()
    assert client_cls.call_args.kwargs["base_url"] == "ssh://twelvetwo@192.168.50.65"


@pytest.mark.django_db
def test_docker_client_for_local_host_uses_socket(host):
    with patch("monitor.collectors.docker.docker.from_env") as from_env:
        docker_client_for(host)
    from_env.assert_called_once()


@pytest.mark.django_db
def test_container_rows_are_tied_to_their_host(remote_settings):
    hermes = Host.objects.create(name="hermes", hostname="hermes")
    DockerContainer.objects.create(
        host=hermes, container_id="abc", name="runner", image="img", status="running"
    )
    assert DockerContainer.objects.filter(host=hermes).count() == 1


@pytest.mark.parametrize(
    ("runner_name", "expected"),
    [
        ("talos-1", "talos"),
        ("talos-light", "talos"),
        ("hermes-1", "hermes"),
        ("unknown-9", "talos"),
    ],
)
def test_runner_maps_to_host_by_name_prefix(runner_name, expected):
    talos = Host(name="talos")
    hermes = Host(name="hermes")
    assert host_for_runner_name(runner_name, [talos, hermes]).name == expected


@pytest.mark.django_db
def test_dashboard_renders_section_per_host(remote_settings, client, host):
    hermes = Host.objects.create(name="hermes", hostname="hermes")
    GitHubRunner.objects.create(
        host=hermes,
        runner_id=7,
        name="hermes-1",
        labels=["hermes"],
        status=RunnerStatus.IDLE,
    )
    content = client.get("/").content.decode()
    assert 'id="host-summary"' in content
    assert 'id="hermes-host-summary"' in content
    assert 'hx-get="/fragments/runners/?host=hermes"' in content
    assert "hermes-1" in content


@pytest.mark.django_db
def test_dashboard_stays_up_when_hermes_has_no_data(remote_settings, client, host):
    content = client.get("/").content.decode()
    assert "No host data yet" in content
    assert 'id="hermes-host-summary"' in content


@pytest.mark.django_db
def test_fragments_accept_host_param_and_reject_unknown(remote_settings, client, host):
    Host.objects.create(name="hermes", hostname="hermes")
    assert client.get("/fragments/containers/?host=hermes").status_code == 200
    assert client.get("/fragments/runners/?host=nope").status_code == 404


def test_probe_uses_mock_free_path_for_unknown_target():
    # Ensure the SSH client refuses unknown host keys instead of trusting them.
    from monitor.services import remote

    fake = MagicMock()
    with patch.object(remote.paramiko, "SSHClient", return_value=fake):
        with pytest.raises(RemoteProbeError):
            fake.connect.side_effect = remote.paramiko.SSHException("boom")
            remote.run_probe("twelvetwo@192.168.50.65")
    fake.set_missing_host_key_policy.assert_called_once()
    assert isinstance(
        fake.set_missing_host_key_policy.call_args.args[0],
        remote.paramiko.RejectPolicy,
    )
