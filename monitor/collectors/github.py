from __future__ import annotations

import logging
import re

import httpx
from django.conf import settings
from django.utils.dateparse import parse_datetime

from monitor.collectors.base import BaseCollector
from monitor.models import (
    GitHubRunner,
    Host,
    RunnerJob,
    RunnerStatus,
    get_or_create_host,
)
from monitor.services.github_runners import runners_endpoint as _runners_endpoint

logger = logging.getLogger(__name__)

_EMPTY_JOB = {
    "current_job_name": "",
    "current_workflow_name": "",
    "current_repository": "",
    "current_html_url": "",
    "current_started_at": None,
    "current_head_branch": "",
    "current_pr_number": None,
}

_BUSY_JOB_STATUSES = {"in_progress", "queued"}
_MAX_WATCH_REPOS = 20


def map_runner_status(api_status: str, busy: bool) -> str:
    if api_status == "offline":
        return RunnerStatus.OFFLINE
    if busy:
        return RunnerStatus.ACTIVE
    return RunnerStatus.IDLE


def host_for_runner_name(runner_name: str, hosts: list[Host]) -> Host:
    """Runner names are `<host>-<n>` (talos-1, hermes-1, talos-light).

    The longest matching host-name prefix wins; unmatched runners fall back to
    the first host (the local one).
    """
    best: Host | None = None
    for host in hosts:
        if runner_name.startswith(f"{host.name}-") and (
            best is None or len(host.name) > len(best.name)
        ):
            best = host
    return best or hosts[0]


def _parse_label_names(labels: list) -> list[str]:
    names = []
    for label in labels:
        if isinstance(label, dict) and label.get("name"):
            names.append(label["name"])
        elif isinstance(label, str):
            names.append(label)
    return names


def _next_page_url(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            match = re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None


def _parse_github_dt(value: str | None):
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return parse_datetime(value)


def _json_get(client, url: str):
    response = client.get(url)
    response.raise_for_status()
    return response.json()


def _watch_repos() -> list[str]:
    if settings.GITHUB_REPO and "/" in settings.GITHUB_REPO:
        return [settings.GITHUB_REPO]
    if settings.GITHUB_ORG:
        return []
    return []


def _org_recent_repos(client, api_url: str, org: str) -> list[str]:
    payload = _json_get(
        client,
        f"{api_url}/orgs/{org}/repos?per_page={_MAX_WATCH_REPOS}&sort=pushed",
    )
    if not isinstance(payload, list):
        return []
    names: list[str] = []
    for repo in payload:
        if isinstance(repo, dict) and repo.get("full_name"):
            names.append(str(repo["full_name"]))
    return names


def _pr_number(run: dict) -> int | None:
    pulls = run.get("pull_requests") or []
    if pulls and isinstance(pulls[0], dict) and pulls[0].get("number"):
        return int(pulls[0]["number"])
    return None


def _job_fields(job: dict, repository: str, run: dict | None = None) -> dict:
    return {
        "current_pr_number": _pr_number(run or {}),
        "current_job_name": job.get("name") or "",
        "current_workflow_name": job.get("workflow_name") or "",
        "current_repository": repository,
        "current_html_url": job.get("html_url") or "",
        "current_started_at": _parse_github_dt(job.get("started_at")),
        "current_head_branch": job.get("head_branch") or "",
    }


# run_id -> run.updated_at we last synced jobs for. Completed runs are fetched
# once; queued/in-progress runs are re-fetched every cycle. Module-level so it
# survives across collector instances inside one collect_metrics process.
_SYNCED_RUNS: dict[int, str] = {}
_RECENT_RUNS = 30


def _is_ours(job: dict, runner_ids: set[int], hosts: list[Host]) -> bool:
    """Jobs on our self-hosted runners, or self-hosted jobs still queued."""
    runner_id = job.get("runner_id")
    if runner_id is not None and int(runner_id) in runner_ids:
        return True
    runner_name = job.get("runner_name") or ""
    if runner_name and any(runner_name.startswith(f"{h.name}-") for h in hosts):
        return True
    if not runner_name and job.get("status") in _BUSY_JOB_STATUSES:
        return "self-hosted" in (job.get("labels") or [])
    return False


def _store_job(job: dict, repository: str, run: dict, hosts: list[Host]) -> None:
    runner_name = job.get("runner_name") or ""
    status = job.get("status") or ""
    started_at = _parse_github_dt(job.get("started_at"))
    if status == "queued" or not runner_name:
        # GitHub stamps started_at at queue time; it isn't a real start yet.
        started_at = None
    RunnerJob.objects.update_or_create(
        github_job_id=int(job["id"]),
        defaults={
            "run_id": int(job.get("run_id") or run.get("id") or 0),
            "host": host_for_runner_name(runner_name, hosts) if runner_name else None,
            "runner_id": job.get("runner_id"),
            "runner_name": runner_name,
            "repository": repository,
            "workflow_name": job.get("workflow_name") or run.get("name") or "",
            "job_name": job.get("name") or "",
            "head_branch": job.get("head_branch") or run.get("head_branch") or "",
            "pr_number": _pr_number(run),
            "html_url": job.get("html_url") or "",
            "status": status,
            "conclusion": job.get("conclusion") or "",
            "created_at": _parse_github_dt(job.get("created_at")),
            "started_at": started_at,
            "completed_at": _parse_github_dt(job.get("completed_at")),
        },
    )


def _watched_repos(client, api_url: str) -> list[str]:
    repos = _watch_repos()
    if settings.GITHUB_ORG:
        for name in _org_recent_repos(client, api_url, settings.GITHUB_ORG):
            if name not in repos:
                repos.append(name)
    return [name for name in repos if "/" in name]


def _sync_jobs(client, runner_ids: set[int], hosts: list[Host]) -> dict[int, dict]:
    """Record recent jobs and return the in-progress job for each busy runner."""
    api_url = settings.GITHUB_API_URL.rstrip("/")
    try:
        repos = _watched_repos(client, api_url)
    except httpx.HTTPError as exc:
        logger.warning("Failed to list GitHub repos for runner jobs: %s", exc)
        return {}

    current: dict[int, dict] = {}
    for full_name in repos:
        try:
            runs_payload = _json_get(
                client,
                f"{api_url}/repos/{full_name}/actions/runs?per_page={_RECENT_RUNS}",
            )
        except httpx.HTTPError as exc:
            logger.warning("Failed to list runs for %s: %s", full_name, exc)
            continue
        runs = (
            runs_payload.get("workflow_runs", [])
            if isinstance(runs_payload, dict)
            else []
        )
        for run in runs:
            run_id = run.get("id")
            if run_id is None:
                continue
            run_id = int(run_id)
            finished = run.get("status") == "completed"
            marker = str(run.get("updated_at") or "")
            if finished and marker and _SYNCED_RUNS.get(run_id) == marker:
                continue
            try:
                jobs_payload = _json_get(
                    client,
                    f"{api_url}/repos/{full_name}/actions/runs/{run_id}/jobs?per_page=50",
                )
            except httpx.HTTPError as exc:
                logger.warning("Failed to list jobs for run %s: %s", run_id, exc)
                continue
            jobs = (
                jobs_payload.get("jobs", []) if isinstance(jobs_payload, dict) else []
            )
            for job in jobs:
                if job.get("id") is None or not _is_ours(job, runner_ids, hosts):
                    continue
                _store_job(job, full_name, run, hosts)
                runner_id = job.get("runner_id")
                if job.get("status") in _BUSY_JOB_STATUSES and runner_id is not None:
                    current[int(runner_id)] = _job_fields(job, full_name, run)
            if finished and marker:
                _SYNCED_RUNS[run_id] = marker
    return current


def _fetch_all_runners(client, start_url: str) -> list[dict]:
    runners: list[dict] = []
    url: str | None = start_url

    while url:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
        runners.extend(payload.get("runners", []))
        url = _next_page_url(response.headers.get("Link"))

    return runners


class GitHubRunnerCollector(BaseCollector):
    name = "github"

    def collect(self) -> None:
        if not settings.GITHUB_TOKEN:
            logger.warning("GITHUB_TOKEN not set; skipping GitHub runner collection")
            return

        endpoint = _runners_endpoint()
        if not endpoint:
            logger.warning(
                "Set GITHUB_ORG or GITHUB_REPO to collect GitHub runner status"
            )
            return

        logger.info("Fetching GitHub runners from %s", endpoint)

        local = get_or_create_host()
        hosts = [local] + [
            Host.objects.get_or_create(name=name, defaults={"hostname": name})[0]
            for name in settings.REMOTE_HOSTS
        ]
        headers = {
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }

        try:
            with httpx.Client(
                headers=headers,
                timeout=httpx.Timeout(10.0),
            ) as client:
                runners = _fetch_all_runners(client, endpoint)
                runner_ids = {int(runner["id"]) for runner in runners}
                jobs_by_runner = _sync_jobs(client, runner_ids, hosts)
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch GitHub runners: %s", exc)
            return

        seen_ids: set[int] = set()

        for runner in runners:
            runner_id = int(runner["id"])
            seen_ids.add(runner_id)
            api_status = runner.get("status", "offline")
            busy = bool(runner.get("busy", False))
            status = map_runner_status(api_status, busy)
            job = jobs_by_runner.get(runner_id, _EMPTY_JOB) if busy else _EMPTY_JOB

            GitHubRunner.objects.update_or_create(
                runner_id=runner_id,
                defaults={
                    "host": host_for_runner_name(runner.get("name", ""), hosts),
                    "name": runner.get("name", ""),
                    "labels": _parse_label_names(runner.get("labels", [])),
                    "status": status,
                    "busy": busy,
                    **job,
                },
            )

        # Runners removed from GitHub (or never returned) must be deleted, not
        # left as offline ghosts — re-registration creates new runner_ids.
        # GitHub runner ids are global, so this spans every host.
        missing = GitHubRunner.objects.all()
        if seen_ids:
            missing = missing.exclude(runner_id__in=seen_ids)
        missing.delete()
