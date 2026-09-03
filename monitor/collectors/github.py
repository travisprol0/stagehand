import logging

from monitor.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class GitHubRunnerCollector(BaseCollector):
    name = "github"

    def collect(self) -> None:
        logger.debug("GitHub runner collector not yet implemented")
