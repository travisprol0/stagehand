from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from monitor.collectors.base import BaseCollector
from monitor.collectors.registry import get_collectors


@pytest.mark.django_db
def test_registry_exposes_three_stub_collectors():
    collectors = get_collectors()
    names = {collector.name for collector in collectors}
    assert names == {"host", "docker", "github"}
    assert len(collectors) == 3
    for collector in collectors:
        assert isinstance(collector, BaseCollector)


@pytest.mark.django_db
def test_collect_metrics_once_calls_each_collector():
    collectors = [MagicMock(spec=BaseCollector) for _ in range(3)]
    for index, collector in enumerate(collectors):
        collector.name = ("host", "docker", "github")[index]

    with patch(
        "monitor.management.commands.collect_metrics.get_collectors",
        return_value=collectors,
    ):
        call_command("collect_metrics", once=True)

    for collector in collectors:
        collector.run.assert_called_once()


@pytest.mark.django_db
def test_collect_metrics_continues_when_collector_raises(caplog):
    class FailingCollector(BaseCollector):
        name = "failing"

        def collect(self) -> None:
            raise RuntimeError("boom")

    succeeding = MagicMock(spec=BaseCollector)
    succeeding.name = "succeeding"

    with patch(
        "monitor.management.commands.collect_metrics.get_collectors",
        return_value=[FailingCollector(), succeeding],
    ):
        call_command("collect_metrics", once=True)

    succeeding.run.assert_called_once()
    assert "boom" in caplog.text


@pytest.mark.django_db
def test_collect_metrics_interval_override():
    with patch(
        "monitor.management.commands.collect_metrics.get_collectors",
        return_value=[],
    ):
        with patch("monitor.management.commands.collect_metrics.time.sleep") as sleep:
            with patch(
                "monitor.management.commands.collect_metrics.Command._should_continue",
                side_effect=[True, False],
            ):
                call_command("collect_metrics", interval=7)

    sleep.assert_called_once_with(7)
