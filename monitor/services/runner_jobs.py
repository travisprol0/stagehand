"""Runner job history: the timeline, queue wait, and per-workflow CI stats."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.db.models import Q
from django.utils import timezone

from monitor.models import GitHubRunner, RunnerJob

TIMELINE_HOURS = 6
# An in_progress row the collector hasn't touched in this long is treated as
# ended at its last update (its run fell out of the recent-runs window).
STALE_AFTER = timedelta(minutes=5)
# Queued rows older than this are assumed abandoned, not still waiting.
QUEUED_MAX_AGE = timedelta(hours=24)


OUTCOMES = {"success": "Successful", "failure": "Failed", "all": "All"}
WINDOWS = {6: "6h", 24: "24h", 168: "7d"}
DEFAULT_OUTCOME = "success"
DEFAULT_HOURS = TIMELINE_HOURS
FAILED = ("failure", "timed_out")


@dataclass(frozen=True)
class HistoryFilters:
    """Filters for the job history (timeline + workflow table).

    Defaults to successful jobs over the last 6h. Running jobs always show,
    whatever the outcome filter, because they have no outcome yet.
    """

    outcome: str = DEFAULT_OUTCOME
    workflow: str = ""
    hours: int = DEFAULT_HOURS

    @classmethod
    def from_params(cls, params) -> "HistoryFilters":
        outcome = params.get("outcome") or DEFAULT_OUTCOME
        if outcome not in OUTCOMES:
            outcome = DEFAULT_OUTCOME
        try:
            hours = int(params.get("hours") or DEFAULT_HOURS)
        except (TypeError, ValueError):
            hours = DEFAULT_HOURS
        if hours not in WINDOWS:
            hours = DEFAULT_HOURS
        workflow = (params.get("workflow") or "").strip()[:255]
        return cls(outcome=outcome, workflow=workflow, hours=hours)

    @property
    def window_label(self) -> str:
        return WINDOWS[self.hours]

    @property
    def is_default(self) -> bool:
        return self == HistoryFilters()

    def querystring(self, host: str = "") -> str:
        """`?…` for the polled fragment URL so polling keeps the filters."""
        params = {}
        if host:
            params["host"] = host
        if self.outcome != DEFAULT_OUTCOME:
            params["outcome"] = self.outcome
        if self.workflow:
            params["workflow"] = self.workflow
        if self.hours != DEFAULT_HOURS:
            params["hours"] = self.hours
        return f"?{urlencode(params)}" if params else ""

    def apply(self, jobs):
        if self.workflow:
            jobs = jobs.filter(workflow_name=self.workflow)
        return jobs.filter(outcome_q(self.outcome))


def outcome_q(outcome: str) -> Q:
    running = Q(completed_at__isnull=True)
    if outcome == "success":
        return Q(conclusion="success") | running
    if outcome == "failure":
        return Q(conclusion__in=FAILED) | running
    return Q()


def workflow_names(*, days: int = 7, now: datetime | None = None) -> list[str]:
    now = now or timezone.now()
    return list(
        RunnerJob.objects.filter(started_at__gte=now - timedelta(days=days))
        .exclude(workflow_name="")
        .values_list("workflow_name", flat=True)
        .distinct()
        .order_by("workflow_name")
    )


@dataclass
class TimelineBar:
    job: RunnerJob
    left: float
    width: float
    running: bool
    tone: str
    label: str


@dataclass
class TimelineRow:
    runner: GitHubRunner
    bars: list[TimelineBar] = field(default_factory=list)
    busy_percent: float = 0.0


@dataclass
class Timeline:
    rows: list[TimelineRow]
    ticks: list[tuple[float, str]]
    hours: int


def _effective_end(job: RunnerJob, now: datetime) -> datetime:
    if job.completed_at is not None:
        return job.completed_at
    if job.updated_at is not None and now - job.updated_at > STALE_AFTER:
        return job.updated_at
    return now


def _tone(job: RunnerJob, running: bool) -> str:
    if running:
        return "running"
    if job.conclusion == "success":
        return "success"
    if job.conclusion in FAILED:
        return "failure"
    return "neutral"


def format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s" if minutes < 10 else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _bar_label(job: RunnerJob, seconds: float, running: bool) -> str:
    name = " / ".join(part for part in (job.workflow_name, job.job_name) if part)
    bits = [name or "job"]
    if job.pr_number:
        bits.append(f"PR #{job.pr_number}")
    elif job.head_branch:
        bits.append(job.head_branch)
    bits.append(format_seconds(seconds))
    bits.append("running" if running else (job.conclusion or job.status))
    return " · ".join(bits)


def _tick_step(hours: int) -> timedelta:
    if hours <= 6:
        return timedelta(hours=1)
    if hours <= 24:
        return timedelta(hours=3)
    return timedelta(days=1)


def build_timeline(
    runners,
    *,
    filters: HistoryFilters | None = None,
    now: datetime | None = None,
) -> Timeline:
    filters = filters or HistoryFilters()
    hours = filters.hours
    now = now or timezone.now()
    start = now - timedelta(hours=hours)
    window = (now - start).total_seconds()
    runners = list(runners)

    names = [runner.name for runner in runners]
    in_window = RunnerJob.objects.filter(
        runner_name__in=names,
        started_at__isnull=False,
        started_at__lt=now,
    ).filter(Q(completed_at__isnull=True) | Q(completed_at__gt=start))
    shown_ids = set(filters.apply(in_window).values_list("pk", flat=True))
    by_runner: dict[str, list[RunnerJob]] = defaultdict(list)
    for job in in_window.order_by("started_at"):
        by_runner[job.runner_name].append(job)

    rows: list[TimelineRow] = []
    for runner in runners:
        row = TimelineRow(runner=runner)
        busy = 0.0
        for job in by_runner.get(runner.name, []):
            end = _effective_end(job, now)
            if end <= start:
                continue
            visible_start = max(job.started_at, start)
            visible_end = min(end, now)
            span = max(0.0, (visible_end - visible_start).total_seconds())
            # Utilisation counts every job; the filters only pick the bars.
            busy += span
            if job.pk not in shown_ids:
                continue
            running = job.completed_at is None and end == now
            row.bars.append(
                TimelineBar(
                    job=job,
                    left=(visible_start - start).total_seconds() / window * 100,
                    # Keep sub-pixel jobs visible as a sliver.
                    width=max(span / window * 100, 0.35),
                    running=running,
                    tone=_tone(job, running),
                    label=_bar_label(
                        job, (end - job.started_at).total_seconds(), running
                    ),
                )
            )
        row.busy_percent = min(100.0, busy / window * 100)
        rows.append(row)

    step = _tick_step(hours)
    local_start = timezone.localtime(start)
    if step >= timedelta(days=1):
        tick = local_start.replace(hour=0, minute=0, second=0, microsecond=0)
        fmt = "%a %d"
    else:
        step_hours = int(step.total_seconds() // 3600)
        tick = local_start.replace(
            hour=local_start.hour - local_start.hour % step_hours,
            minute=0,
            second=0,
            microsecond=0,
        )
        fmt = "%H:%M"
    ticks: list[tuple[float, str]] = []
    while tick < now:
        if tick > start:
            offset = (tick - start).total_seconds() / window * 100
            # Skip labels hugging the edges; they'd clip.
            if 3 < offset < 97:
                ticks.append((offset, tick.strftime(fmt)))
        tick += step

    return Timeline(rows=rows, ticks=ticks, hours=hours)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def queue_snapshot(*, now: datetime | None = None) -> dict:
    """Jobs waiting for a self-hosted runner right now."""
    now = now or timezone.now()
    waiting = list(
        RunnerJob.objects.filter(
            status="queued",
            created_at__gte=now - QUEUED_MAX_AGE,
        ).order_by("created_at")
    )
    oldest = waiting[0].created_at if waiting else None
    return {
        "count": len(waiting),
        "oldest_seconds": (now - oldest).total_seconds() if oldest else None,
        "oldest_label": format_seconds((now - oldest).total_seconds())
        if oldest
        else "",
        "jobs": waiting,
    }


def job_stats(
    *, filters: HistoryFilters | None = None, now: datetime | None = None
) -> dict:
    """Headline numbers for the window. Ignores the outcome filter on purpose:
    a pass rate over only-successful jobs would always read 100%."""
    filters = filters or HistoryFilters()
    hours = filters.hours
    now = now or timezone.now()
    since = now - timedelta(hours=hours)
    jobs = RunnerJob.objects.filter(started_at__gte=since).exclude(runner_name="")
    if filters.workflow:
        jobs = jobs.filter(workflow_name=filters.workflow)
    jobs = list(jobs)
    waits = [job.queue_seconds for job in jobs if job.queue_seconds is not None]
    finished = [job for job in jobs if job.conclusion in {"success", "failure"}]
    passed = sum(1 for job in finished if job.conclusion == "success")
    durations = [
        job.duration_seconds for job in jobs if job.duration_seconds is not None
    ]
    return {
        "window": filters.window_label,
        "count": len(jobs),
        "failures": len(finished) - passed,
        "pass_rate": (passed / len(finished) * 100) if finished else None,
        "wait_p50": format_seconds(_percentile(waits, 50)),
        "wait_p95": format_seconds(_percentile(waits, 95)),
        "wait_p95_seconds": _percentile(waits, 95),
        "duration_p50": format_seconds(_percentile(durations, 50)),
    }


def workflow_stats(
    *, filters: HistoryFilters | None = None, now: datetime | None = None
) -> list:
    """Per workflow in the window: filtered job count and timings, plus the
    pass rate over every finished job (independent of the outcome filter)."""
    filters = filters or HistoryFilters()
    now = now or timezone.now()
    in_window = RunnerJob.objects.filter(
        started_at__gte=now - timedelta(hours=filters.hours)
    ).exclude(runner_name="")
    if filters.workflow:
        in_window = in_window.filter(workflow_name=filters.workflow)

    everything: dict[tuple[str, str], list[RunnerJob]] = defaultdict(list)
    for job in in_window:
        everything[(job.repository, job.workflow_name or "—")].append(job)
    shown: dict[tuple[str, str], list[RunnerJob]] = defaultdict(list)
    for job in in_window.filter(outcome_q(filters.outcome)):
        shown[(job.repository, job.workflow_name or "—")].append(job)

    rows = []
    for key, items in shown.items():
        repository, workflow = key
        finished = [j for j in everything[key] if j.conclusion in {"success", *FAILED}]
        passed = sum(1 for j in finished if j.conclusion == "success")
        durations = [
            j.duration_seconds for j in items if j.duration_seconds is not None
        ]
        waits = [j.queue_seconds for j in items if j.queue_seconds is not None]
        last = max(items, key=lambda job: job.started_at)
        rows.append(
            {
                "repository": repository,
                "workflow": workflow,
                "count": len(items),
                "failures": len(finished) - passed,
                "pass_rate": (passed / len(finished) * 100) if finished else None,
                "duration_p50": format_seconds(_percentile(durations, 50)),
                "duration_p95": format_seconds(_percentile(durations, 95)),
                "wait_p50": format_seconds(_percentile(waits, 50)),
                "last": last,
            }
        )
    rows.sort(key=lambda row: (-row["count"], row["workflow"]))
    return rows
