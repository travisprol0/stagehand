from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README_PATH = ROOT / "README.md"
MAKEFILE_PATH = ROOT / "Makefile"
TEST_SCRIPT_PATH = ROOT / "scripts" / "test.sh"
CI_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"

TICKET_TEST_MODULES = (
    "monitor/tests/test_collect_metrics_command.py",
    "monitor/tests/test_host_collector.py",
    "monitor/tests/test_docker_collector.py",
    "monitor/tests/test_github_collector.py",
    "monitor/tests/test_fragment_views.py",
    "monitor/tests/test_dashboard_layout.py",
    "monitor/tests/test_dashboard_interactivity.py",
    "monitor/tests/test_charts.py",
    "monitor/tests/test_compose_config.py",
)

README_SECTIONS = (
    "## Overview",
    "## Local development",
    "## Docker Compose",
    "## Environment variables",
    "## Running tests",
    "## Architecture",
)


@pytest.mark.parametrize("relative_path", TICKET_TEST_MODULES)
def test_ticket_test_modules_exist(relative_path):
    assert (ROOT / relative_path).is_file(), f"missing test module: {relative_path}"


def test_readme_contains_runbook_sections():
    content = README_PATH.read_text(encoding="utf-8")

    for section in README_SECTIONS:
        assert section in content, f"README missing section: {section}"


def test_makefile_has_harness_targets():
    content = MAKEFILE_PATH.read_text(encoding="utf-8")
    targets = {
        line.split(":", 1)[0]
        for line in content.splitlines()
        if line and not line.startswith(("\t", " ", "#", ".")) and ":" in line
    }

    assert {"test", "lint", "up"}.issubset(targets)


def test_test_script_exists():
    assert TEST_SCRIPT_PATH.is_file()


def test_ci_workflow_exists():
    assert CI_WORKFLOW_PATH.is_file()
