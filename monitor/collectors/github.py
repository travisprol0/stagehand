import logging
import re

import httpx
from django.conf import settings

from monitor.collectors.base import BaseCollector
from monitor.models import GitHubRunner, RunnerStatus, get_or_create_host
from monitor.services.github_runners import runners_endpoint as _runners_endpoint

logger = logging.getLogger(__name__)


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


def _fetch_all_runners(client: httpx.Client, start_url: str) -> list[dict]:
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
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch GitHub runners: %s", exc)
            return

        seen_ids: set[int] = set()

        for runner in runners:
            runner_id = runner["id"]
            seen_ids.add(runner_id)
            api_status = runner.get("status", "offline")
            busy = bool(runner.get("busy", False))
            status = map_runner_status(api_status, busy)

            GitHubRunner.objects.update_or_create(
                host=host,
                runner_id=runner_id,
                defaults={
                    "name": runner.get("name", ""),
                    "labels": _parse_label_names(runner.get("labels", [])),
                    "status": status,
                    "busy": busy,
                },
            )

        if seen_ids:
            GitHubRunner.objects.filter(host=host).exclude(
                runner_id__in=seen_ids,
            ).update(status=RunnerStatus.OFFLINE, busy=False)
        else:
            GitHubRunner.objects.filter(host=host).update(
                status=RunnerStatus.OFFLINE,
                busy=False,
            )
