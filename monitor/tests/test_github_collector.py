from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.test import override_settings

from monitor.collectors.github import GitHubRunnerCollector, map_runner_status
from monitor.models import GitHubRunner, Host, RunnerStatus


@pytest.fixture
def host(db):
    return Host.objects.create(name="talos", hostname="talos.local")


def _runners_payload():
    return {
        "total_count": 3,
        "runners": [
            {
                "id": 1,
                "name": "talos-runner-1",
                "status": "online",
                "busy": False,
                "labels": [{"name": "self-hosted"}, {"name": "linux"}],
            },
            {
                "id": 2,
                "name": "talos-runner-2",
                "status": "online",
                "busy": True,
                "labels": [{"name": "self-hosted"}],
            },
            {
                "id": 3,
                "name": "talos-runner-3",
                "status": "offline",
                "busy": False,
                "labels": [],
            },
        ],
    }


@pytest.mark.parametrize(
    ("api_status", "busy", "expected"),
    [
        ("online", False, RunnerStatus.IDLE),
        ("online", True, RunnerStatus.ACTIVE),
        ("offline", False, RunnerStatus.OFFLINE),
        ("offline", True, RunnerStatus.OFFLINE),
    ],
)
def test_map_runner_status(api_status, busy, expected):
    assert map_runner_status(api_status, busy) == expected


@pytest.mark.django_db
@override_settings(
    GITHUB_TOKEN="test-token",
    GITHUB_ORG="my-org",
    GITHUB_REPO="",
    GITHUB_API_URL="https://api.github.com",
)
def test_collect_upserts_runners_from_org(host):
    response = MagicMock()
    response.json.return_value = _runners_payload()
    response.headers = {}
    response.raise_for_status = MagicMock()

    with patch("monitor.collectors.github.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = response
        with patch("monitor.collectors.github.get_or_create_host", return_value=host):
            GitHubRunnerCollector().collect()

    runners = GitHubRunner.objects.filter(host=host).order_by("runner_id")
    assert runners.count() == 3
    assert runners[0].status == RunnerStatus.IDLE
    assert runners[0].labels == ["self-hosted", "linux"]
    assert runners[1].status == RunnerStatus.ACTIVE
    assert runners[1].busy is True
    assert runners[2].status == RunnerStatus.OFFLINE

    client.get.assert_called()
    assert "/orgs/my-org/actions/runners" in client.get.call_args_list[0].args[0]
    assert (
        client_cls.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"
    )


@pytest.mark.django_db
@override_settings(
    GITHUB_TOKEN="test-token",
    GITHUB_ORG="",
    GITHUB_REPO="owner/repo",
    GITHUB_API_URL="https://api.github.com",
)
def test_collect_uses_repo_scope(host):
    response = MagicMock()
    response.json.return_value = {"total_count": 0, "runners": []}
    response.headers = {}
    response.raise_for_status = MagicMock()

    with patch("monitor.collectors.github.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = response
        with patch("monitor.collectors.github.get_or_create_host", return_value=host):
            GitHubRunnerCollector().collect()

    assert "/repos/owner/repo/actions/runners" in client.get.call_args.args[0]


@pytest.mark.django_db
@override_settings(
    GITHUB_TOKEN="test-token",
    GITHUB_ORG="",
    GITHUB_REPO="travisprol0/lattice-log",
    GITHUB_API_URL="https://api.github.com",
)
def test_collect_attaches_in_progress_job_to_busy_runner(host):
    def _get(url):
        response = MagicMock()
        response.headers = {}
        response.raise_for_status = MagicMock()
        if url.endswith("/actions/runners"):
            response.json.return_value = {
                "runners": [
                    {
                        "id": 2,
                        "name": "talos-4",
                        "status": "online",
                        "busy": True,
                        "labels": [{"name": "talos"}],
                    }
                ]
            }
        elif "/actions/runs?" in url:
            response.json.return_value = {
                "workflow_runs": [
                    {"id": 34098672928, "name": "NUC Nightly Maintenance"}
                ]
            }
        elif "/jobs" in url:
            response.json.return_value = {
                "jobs": [
                    {
                        "id": 99,
                        "name": "cleanup",
                        "status": "in_progress",
                        "runner_id": 2,
                        "workflow_name": "NUC Nightly Maintenance",
                        "html_url": "https://github.com/travisprol0/lattice-log/actions/runs/1/job/99",
                        "started_at": "2026-09-07T08:04:49Z",
                        "head_branch": "master",
                    }
                ]
            }
        else:
            raise AssertionError(url)
        return response

    with patch("monitor.collectors.github.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.side_effect = _get
        with patch("monitor.collectors.github.get_or_create_host", return_value=host):
            GitHubRunnerCollector().collect()

    runner = GitHubRunner.objects.get(runner_id=2)
    assert runner.busy is True
    assert runner.current_job_name == "cleanup"
    assert runner.current_workflow_name == "NUC Nightly Maintenance"
    assert runner.current_repository == "travisprol0/lattice-log"
    assert "actions/runs/1/job/99" in runner.current_html_url
    assert runner.current_started_at is not None
    assert runner.current_head_branch == "master"


@pytest.mark.django_db
@override_settings(GITHUB_TOKEN="", GITHUB_ORG="my-org", GITHUB_REPO="")
def test_missing_token_skips_without_raising(host, caplog):
    with patch("monitor.collectors.github.get_or_create_host", return_value=host):
        GitHubRunnerCollector().collect()

    assert GitHubRunner.objects.count() == 0
    assert "GITHUB_TOKEN" in caplog.text


@pytest.mark.django_db
@override_settings(
    GITHUB_TOKEN="super-secret-pat-value",
    GITHUB_ORG="my-org",
    GITHUB_REPO="",
    GITHUB_API_URL="https://api.github.com",
)
def test_token_never_appears_in_logs(host, caplog):
    with patch("monitor.collectors.github.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.side_effect = httpx.HTTPError("request failed")
        with patch("monitor.collectors.github.get_or_create_host", return_value=host):
            GitHubRunnerCollector().collect()

    assert "super-secret-pat-value" not in caplog.text


@pytest.mark.django_db
@override_settings(
    GITHUB_TOKEN="test-token",
    GITHUB_ORG="my-org",
    GITHUB_REPO="",
    GITHUB_API_URL="https://api.github.com",
)
def test_missing_runners_marked_offline(host):
    stale = GitHubRunner.objects.create(
        host=host,
        runner_id=99,
        name="gone-runner",
        labels=[],
        status=RunnerStatus.IDLE,
    )
    response = MagicMock()
    response.json.return_value = {"total_count": 0, "runners": []}
    response.headers = {}
    response.raise_for_status = MagicMock()

    with patch("monitor.collectors.github.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = response
        with patch("monitor.collectors.github.get_or_create_host", return_value=host):
            GitHubRunnerCollector().collect()

    stale.refresh_from_db()
    assert stale.status == RunnerStatus.OFFLINE
    assert stale.busy is False
