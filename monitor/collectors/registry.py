from monitor.collectors.base import BaseCollector
from monitor.collectors.docker import DockerCollector
from monitor.collectors.github import GitHubRunnerCollector
from monitor.collectors.host import HostMetricsCollector

_COLLECTOR_CLASSES: list[type[BaseCollector]] = [
    HostMetricsCollector,
    DockerCollector,
    GitHubRunnerCollector,
]


def get_collectors() -> list[BaseCollector]:
    return [collector_class() for collector_class in _COLLECTOR_CLASSES]
