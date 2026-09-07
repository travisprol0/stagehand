from __future__ import annotations

import logging
import re

import httpx
from django.conf import settings
from django.utils.dateparse import parse_datetime

from monitor.collectors.base import BaseCollector
from monitor.models import GitHubRunner, RunnerStatus, get_or_create_host
from monitor.services.github_runners import runners_endpoint as _runners_endpoint

logger = logging.getLogger(__name__)

_EMPTY_JOB = {
    "current_job_name": "",
    "current_workflow_name": "",
    "current_repository": "",
    "current_html_url": "",
    "current_started_at": None,
    "current_head_branch": "",
}

_BUSY_JOB_STATUSES = {"in_progress", "queued"}
_MAX_WATCH_REPOS = 20


def map_runner_status(api_status: str, busy: bool) -> str:
    if api_status == "offline":
        return RunnerStatus.OFFLINE
    if busy:
        return RunnerStatus.ACTIVE
    return RunnerStatus.IDLE


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


def _job_fields(job: dict, repository: str) -> dict:
    return {
        "current_job_name": job.get("name") or "",
        "current_workflow_name": job.get("workflow_name") or "",
        "current_repository": repository,
        "current_html_url": job.get("html_url") or "",
        "current_started_at": _parse_github_dt(job.get("started_at")),
        "current_head_branch": job.get("head_branch") or "",
    }


def _jobs_for_busy_runners(client, busy_ids: set[int]) -> dict[int, dict]:
    if not busy_ids:
        return {}
    api_url = settings.GITHUB_API_URL.rstrip("/")
    repos = _watch_repos()
    try:
        if settings.GITHUB_ORG:
            for name in _org_recent_repos(client, api_url, settings.GITHUB_ORG):
                if name not in repos:
                    repos.append(name)
    except httpx.HTTPError as exc:
        logger.warning("Failed to list GitHub repos for runner jobs: %s", exc)
        return {}

    found: dict[int, dict] = {}
    remaining = set(busy_ids)
    for full_name in repos:
        if not remaining:
            break
        if "/" not in full_name:
            continue
        try:
            runs_payload = _json_get(
                client,
                f"{api_url}/repos/{full_name}/actions/runs"
                f"?status=in_progress&per_page=20",
            )
        except httpx.HTTPError as exc:
            logger.warning("Failed to list in-progress runs for %s: %s", full_name, exc)
            continue
        runs = (
            runs_payload.get("workflow_runs", [])
            if isinstance(runs_payload, dict)
            else []
        )
        for run in runs:
            if not remaining:
                break
            run_id = run.get("id")
            if run_id is None:
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
                runner_id = job.get("runner_id")
                if runner_id not in remaining:
                    continue
                if job.get("status") not in _BUSY_JOB_STATUSES:
                    continue
                found[int(runner_id)] = _job_fields(job, full_name)
                remaining.discard(int(runner_id))
    return found


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

        host = get_or_create_host()
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
                busy_ids = {
                    int(runner["id"])
                    for runner in runners
                    if runner.get("busy") and runner.get("status") != "offline"
                }
                jobs_by_runner = _jobs_for_busy_runners(client, busy_ids)
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
                host=host,
                runner_id=runner_id,
                defaults={
                    "name": runner.get("name", ""),
                    "labels": _parse_label_names(runner.get("labels", [])),
                    "status": status,
                    "busy": busy,
                    **job,
                },
            )

        stale_update = {
            "status": RunnerStatus.OFFLINE,
            "busy": False,
            **_EMPTY_JOB,
        }
        if seen_ids:
            GitHubRunner.objects.filter(host=host).exclude(
                runner_id__in=seen_ids,
            ).update(**stale_update)
        else:
            GitHubRunner.objects.filter(host=host).update(**stale_update)
