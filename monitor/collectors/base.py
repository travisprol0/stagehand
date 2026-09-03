import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    name: str = "base"

    def run(self) -> None:
        try:
            self.collect()
        except Exception:
            logger.exception("Collector %s failed", self.name)

    @abstractmethod
    def collect(self) -> None:
        pass
