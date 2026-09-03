import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings


@pytest.mark.django_db
def test_check_github_runners_reports_missing_token(capsys):
    with override_settings(GITHUB_TOKEN="", GITHUB_ORG="", GITHUB_REPO=""):
        with pytest.raises(CommandError):
            call_command("check_github_runners")

    captured = capsys.readouterr()
    assert "GITHUB_TOKEN" in captured.err


@pytest.mark.django_db
@override_settings(
    GITHUB_TOKEN="test-token",
    GITHUB_ORG="",
    GITHUB_REPO="owner/repo",
    GITHUB_API_URL="https://api.github.com",
)
def test_check_github_runners_lists_runners(monkeypatch):
    def fake_fetch(_client, _url):
        return [
            {
                "id": 1,
                "name": "talos-runner",
                "status": "online",
                "busy": False,
                "labels": [{"name": "self-hosted"}],
            }
        ]

    monkeypatch.setattr(
        "monitor.management.commands.check_github_runners._fetch_all_runners",
        fake_fetch,
    )

    call_command("check_github_runners")
