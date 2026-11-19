from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from monitor.collectors.github import GitHubRunnerCollector
from monitor.models import GitHubRunner, Host, RunnerJob, RunnerStatus
from monitor.services.charts import build_sparkline
from monitor.services.runner_jobs import (
    HistoryFilters,
    build_timeline,
    format_seconds,
    job_stats,
    queue_snapshot,
    workflow_stats,
)

REPO = "travisprol0/lattice-log"


@pytest.fixture(autouse=True)
def allow_testserver(settings):
    settings.ALLOWED_HOSTS = ["testserver"]


@pytest.fixture
def talos(db):
    return Host.objects.create(name="talos", hostname="talos.local")


@pytest.fixture
def talos_1(talos):
    return GitHubRunner.objects.create(
        host=talos,
        runner_id=1,
        name="talos-1",
        labels=["self-hosted"],
        status=RunnerStatus.IDLE,
    )


_job_ids = iter(range(1000, 100000))


def make_job(
    runner_name="talos-1",
    *,
    ago,
    minutes=5,
    wait=30,
    conclusion="success",
    workflow="CI",
    host=None,
    running=False,
):
    now = timezone.now()
    started = now - ago
    return RunnerJob.objects.create(
        github_job_id=next(_job_ids),
        run_id=1,
        host=host,
        runner_name=runner_name,
        repository=REPO,
        workflow_name=workflow,
        job_name="test",
        status="in_progress" if running else "completed",
        conclusion="" if running else conclusion,
        created_at=started - timedelta(seconds=wait),
        started_at=started,
        completed_at=None if running else started + timedelta(minutes=minutes),
    )


# --- collector -------------------------------------------------------------


def _fake_github(runs, jobs_by_run):
    calls = []

    def _get(url):
        calls.append(url)
        response = MagicMock()
        response.headers = {}
        response.raise_for_status = MagicMock()
        if url.endswith("/actions/runners"):
            response.json.return_value = {
                "runners": [
                    {
                        "id": 1,
                        "name": "talos-1",
                        "status": "online",
                        "busy": True,
                        "labels": [{"name": "self-hosted"}],
                    },
                ]
            }
        elif "/actions/runs?" in url:
            response.json.return_value = {"workflow_runs": runs}
        elif "/jobs" in url:
            run_id = int(url.split("/runs/")[1].split("/")[0])
            response.json.return_value = {"jobs": jobs_by_run[run_id]}
        else:
            raise AssertionError(url)
        return response

    return _get, calls


def _collect(talos, get):
    with patch("monitor.collectors.github.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = get
        with patch("monitor.collectors.github.get_or_create_host", return_value=talos):
            GitHubRunnerCollector().collect()


@pytest.mark.django_db
@override_settings(
    GITHUB_TOKEN="t",
    GITHUB_ORG="",
    GITHUB_REPO=REPO,
    GITHUB_API_URL="https://api.github.com",
)
def test_collector_records_job_history_and_skips_finished_runs(talos):
    runs = [
        {
            "id": 10,
            "status": "completed",
            "updated_at": "2026-11-19T10:10:00Z",
            "name": "CI",
            "pull_requests": [{"number": 7}],
        },
        {
            "id": 11,
            "status": "in_progress",
            "updated_at": "2026-11-19T10:20:00Z",
            "name": "CI",
        },
    ]
    jobs = {
        10: [
            {
                "id": 100,
                "run_id": 10,
                "name": "test",
                "workflow_name": "CI",
                "status": "completed",
                "conclusion": "success",
                "runner_id": 1,
                "runner_name": "talos-1",
                "created_at": "2026-11-19T10:00:00Z",
                "started_at": "2026-11-19T10:01:30Z",
                "completed_at": "2026-11-19T10:09:00Z",
                "labels": ["self-hosted"],
            },
            # GitHub-hosted job in the same run: not ours.
            {
                "id": 101,
                "run_id": 10,
                "name": "lint",
                "status": "completed",
                "conclusion": "success",
                "runner_id": 555,
                "runner_name": "GitHub Actions 3",
                "labels": ["ubuntu-latest"],
            },
        ],
        11: [
            {
                "id": 110,
                "run_id": 11,
                "name": "e2e",
                "workflow_name": "CI",
                "status": "in_progress",
                "runner_id": 1,
                "runner_name": "talos-1",
                "created_at": "2026-11-19T10:15:00Z",
                "started_at": "2026-11-19T10:16:00Z",
                "labels": ["self-hosted"],
            },
            {
                "id": 111,
                "run_id": 11,
                "name": "build",
                "workflow_name": "CI",
                "status": "queued",
                "runner_id": None,
                "runner_name": None,
                "created_at": "2026-11-19T10:18:00Z",
                "started_at": "2026-11-19T10:18:00Z",
                "labels": ["self-hosted"],
            },
        ],
    }
    get, calls = _fake_github(runs, jobs)
    _collect(talos, get)

    assert set(RunnerJob.objects.values_list("github_job_id", flat=True)) == {
        100,
        110,
        111,
    }
    done = RunnerJob.objects.get(github_job_id=100)
    assert done.queue_seconds == 90
    assert done.duration_seconds == 450
    assert done.pr_number == 7
    assert done.host == talos
    queued = RunnerJob.objects.get(github_job_id=111)
    assert queued.started_at is None  # queue-time stamp isn't a real start
    assert queued.host is None

    runner = GitHubRunner.objects.get(runner_id=1)
    assert runner.current_job_name == "e2e"

    # Second cycle: the completed run is unchanged, so its jobs aren't refetched.
    calls.clear()
    _collect(talos, get)
    assert not any("/runs/10/jobs" in url for url in calls)
    assert any("/runs/11/jobs" in url for url in calls)


# --- services --------------------------------------------------------------


@pytest.mark.django_db
def test_timeline_defaults_to_successful_jobs_but_keeps_running(talos_1):
    make_job(ago=timedelta(hours=3), conclusion="success")
    make_job(ago=timedelta(hours=2), conclusion="failure")
    make_job(ago=timedelta(minutes=4), running=True)

    row = build_timeline([talos_1]).rows[0]
    assert [bar.tone for bar in row.bars] == ["success", "running"]

    failed = build_timeline([talos_1], filters=HistoryFilters(outcome="failure")).rows[
        0
    ]
    assert [bar.tone for bar in failed.bars] == ["failure", "running"]

    # Busy % is utilisation, independent of which bars are shown.
    assert failed.busy_percent == pytest.approx(row.busy_percent, abs=0.01)

    everything = build_timeline([talos_1], filters=HistoryFilters(outcome="all")).rows[
        0
    ]
    assert len(everything.bars) == 3


@pytest.mark.django_db
def test_timeline_window_and_busy_percent(talos_1):
    make_job(ago=timedelta(hours=1), minutes=36)  # 36m of a 6h window = 10%
    make_job(ago=timedelta(hours=20), minutes=10)  # outside 6h, inside 24h

    six = build_timeline([talos_1]).rows[0]
    assert len(six.bars) == 1
    assert six.busy_percent == pytest.approx(10, abs=0.5)
    assert six.bars[0].left == pytest.approx(5 / 6 * 100, abs=0.5)

    day = build_timeline([talos_1], filters=HistoryFilters(hours=24)).rows[0]
    assert len(day.bars) == 2


@pytest.mark.django_db
def test_workflow_filter_and_stats(talos_1):
    make_job(ago=timedelta(hours=1), workflow="CI", wait=20)
    make_job(ago=timedelta(hours=2), workflow="CI", wait=40, conclusion="failure")
    make_job(ago=timedelta(hours=3), workflow="Nightly", wait=600)

    stats = job_stats(filters=HistoryFilters(hours=24))
    assert stats["count"] == 3
    assert stats["failures"] == 1
    assert stats["pass_rate"] == pytest.approx(200 / 3)

    ci = job_stats(filters=HistoryFilters(hours=24, workflow="CI"))
    assert ci["count"] == 2
    assert ci["wait_p95"] == "40s"

    rows = workflow_stats(filters=HistoryFilters(hours=24))
    by_name = {row["workflow"]: row for row in rows}
    # Count follows the outcome filter (successful), pass rate covers all runs.
    assert by_name["CI"]["count"] == 1
    assert by_name["CI"]["pass_rate"] == 50
    assert by_name["Nightly"]["wait_p50"] == "10m"


@pytest.mark.django_db
def test_queue_snapshot_counts_waiting_jobs():
    RunnerJob.objects.create(
        github_job_id=1,
        run_id=1,
        repository=REPO,
        status="queued",
        created_at=timezone.now() - timedelta(minutes=3),
    )
    RunnerJob.objects.create(  # abandoned long ago
        github_job_id=2,
        run_id=1,
        repository=REPO,
        status="queued",
        created_at=timezone.now() - timedelta(days=3),
    )
    queue = queue_snapshot()
    assert queue["count"] == 1
    assert queue["oldest_label"].startswith("3m")


def test_history_filters_parse_and_roundtrip():
    assert HistoryFilters.from_params({}) == HistoryFilters(outcome="success", hours=6)
    bad = HistoryFilters.from_params({"outcome": "nope", "hours": "13"})
    assert bad.is_default
    f = HistoryFilters.from_params({"outcome": "all", "hours": "168", "workflow": "CI"})
    assert f.querystring("hermes") == "?host=hermes&outcome=all&workflow=CI&hours=168"
    assert HistoryFilters().querystring() == ""


def test_format_seconds():
    assert format_seconds(None) == "—"
    assert format_seconds(42) == "42s"
    assert format_seconds(125) == "2m 05s"
    assert format_seconds(3 * 3600 + 120) == "3h 02m"


def test_sparkline_needs_two_points_and_scales_to_peak():
    assert build_sparkline([1.0]) is None
    spark = build_sparkline([None, 10.0, 20.0])
    assert spark is not None and spark.peak == 20.0
    assert len(spark.line.split()) == 2


# --- views -----------------------------------------------------------------


@pytest.mark.django_db
def test_runner_fragment_filters_keep_polling_url(talos_1):
    make_job(ago=timedelta(hours=1), conclusion="failure", workflow="CI")
    client = Client()

    default = client.get("/fragments/runners/").content.decode()
    assert 'value="success" checked' in default
    assert "job-failure absolute" not in default

    failed = client.get("/fragments/runners/?outcome=failure&hours=24").content.decode()
    assert "job-failure absolute" in failed
    assert 'hx-get="/fragments/runners/?outcome=failure&amp;hours=24"' in failed
    assert "Reset" in failed


@pytest.mark.django_db
def test_container_rows_put_problems_first(talos):
    from monitor.models import DockerContainer

    for name, status, health in (
        ("a-ok", "running", "healthy"),
        ("b-sick", "running", "unhealthy"),
        ("c-stopped", "exited", "none"),
    ):
        DockerContainer.objects.create(
            host=talos,
            container_id=name,
            name=name,
            image="img",
            status=status,
            health=health,
        )
    content = Client().get("/fragments/containers/").content.decode()
    assert content.index("b-sick") < content.index("c-stopped") < content.index("a-ok")
