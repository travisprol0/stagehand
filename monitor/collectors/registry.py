import logging

from monitor.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


def get_collectors() -> list[BaseCollector]:
    collectors: list[BaseCollector] = []
    imports = (
        ("monitor.collectors.host", "HostMetricsCollector"),
        ("monitor.collectors.docker", "DockerCollector"),
        ("monitor.collectors.github", "GitHubRunnerCollector"),
    )
    for module_name, class_name in imports:
        try:
            module = __import__(module_name, fromlist=[class_name])
            collectors.append(getattr(module, class_name)())
        except Exception:
            logger.exception("Failed to load collector %s", class_name)
    return collectors
