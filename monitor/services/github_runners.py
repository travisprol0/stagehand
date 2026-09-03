"""Shared GitHub runner API helpers."""

from django.conf import settings


def runners_endpoint() -> str | None:
    api_url = settings.GITHUB_API_URL.rstrip("/")
    if settings.GITHUB_ORG:
        return f"{api_url}/orgs/{settings.GITHUB_ORG}/actions/runners"
    if settings.GITHUB_REPO:
        owner, repo = settings.GITHUB_REPO.split("/", 1)
        return f"{api_url}/repos/{owner}/{repo}/actions/runners"
    return None


def runners_scope_label() -> str:
    if settings.GITHUB_ORG:
        return f"organization {settings.GITHUB_ORG!r}"
    if settings.GITHUB_REPO:
        return f"repository {settings.GITHUB_REPO!r}"
    return "unset (set GITHUB_ORG or GITHUB_REPO)"


def github_config_issues() -> list[str]:
    issues: list[str] = []
    if not settings.GITHUB_TOKEN:
        issues.append("GITHUB_TOKEN is not set")
    if not settings.GITHUB_ORG and not settings.GITHUB_REPO:
        issues.append("Set GITHUB_ORG or GITHUB_REPO to match where runners are registered")
    if settings.GITHUB_ORG and settings.GITHUB_REPO:
        issues.append(
            "Both GITHUB_ORG and GITHUB_REPO are set; org scope wins. "
            "Clear GITHUB_ORG if runners are registered on a single repo."
        )
    if settings.GITHUB_REPO and "/" not in settings.GITHUB_REPO:
        issues.append("GITHUB_REPO must be owner/repo (e.g. my-org/my-project)")
    return issues
