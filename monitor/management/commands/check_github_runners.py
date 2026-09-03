import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from monitor.collectors.github import _fetch_all_runners, map_runner_status
from monitor.services.github_runners import (
    github_config_issues,
    runners_endpoint,
    runners_scope_label,
)


class Command(BaseCommand):
    help = (
        "Verify GitHub runner API configuration and list runners visible to stagehand."
    )

    def handle(self, *args, **options):
        issues = github_config_issues()
        if issues:
            for issue in issues:
                self.stderr.write(self.style.ERROR(issue))
            raise CommandError("GitHub runner configuration is incomplete")

        endpoint = runners_endpoint()
        assert endpoint is not None

        self.stdout.write(f"Scope: {runners_scope_label()}")
        self.stdout.write(f"API:   {endpoint}")

        headers = {
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }

        try:
            with httpx.Client(headers=headers, timeout=httpx.Timeout(10.0)) as client:
                runners = _fetch_all_runners(client, endpoint)
        except httpx.HTTPStatusError as exc:
            self._raise_http_error(exc)
        except httpx.HTTPError as exc:
            raise CommandError(f"GitHub API request failed: {exc}") from exc

        if not runners:
            self.stdout.write(
                self.style.WARNING(
                    "API call succeeded but returned 0 runners for this scope."
                )
            )
            self.stdout.write(
                "If runners appear under a different repo in GitHub, set "
                "GITHUB_REPO=owner/repo for that repo and clear GITHUB_ORG."
            )
            return

        self.stdout.write(self.style.SUCCESS(f"Found {len(runners)} runner(s):"))
        for runner in runners:
            status = map_runner_status(
                runner.get("status", "offline"),
                bool(runner.get("busy", False)),
            )
            labels = ", ".join(
                label.get("name", label) if isinstance(label, dict) else str(label)
                for label in runner.get("labels", [])
            )
            self.stdout.write(
                f"  - {runner.get('name', '(unnamed)')} "
                f"[{status}, busy={runner.get('busy', False)}]"
                + (f" labels: {labels}" if labels else "")
            )

    def _raise_http_error(self, exc: httpx.HTTPStatusError) -> None:
        status = exc.response.status_code
        hint = {
            401: "Token is invalid or expired. Create a new PAT with repo (repo runners) "
            "or admin:org (org runners) scope.",
            403: "Token lacks permission for this endpoint. For repo runners use a PAT "
            "with repo scope; for org runners use admin:org or a fine-grained token "
            "with Organization administration / Actions read.",
            404: "Org or repo not found, or token cannot access it. Check "
            "GITHUB_ORG / GITHUB_REPO spelling.",
        }.get(status, "See https://docs.github.com/en/rest/actions/self-hosted-runners")

        body = exc.response.text.strip()
        detail = f" ({body[:200]})" if body else ""
        raise CommandError(f"GitHub API HTTP {status}: {hint}{detail}") from exc
