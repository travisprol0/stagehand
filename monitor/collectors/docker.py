import logging

from monitor.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class DockerCollector(BaseCollector):
    name = "docker"

    def collect(self) -> None:
        logger.debug("Docker collector not yet implemented")
