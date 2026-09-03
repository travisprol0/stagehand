import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from monitor.collectors.registry import get_collectors

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Collect host, Docker, and GitHub runner metrics in a loop."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._running = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run a single collection iteration and exit.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=None,
            help="Seconds between iterations (overrides METRICS_INTERVAL_SECONDS).",
        )

    def handle(self, *args, **options):
        interval = options["interval"] or settings.METRICS_INTERVAL_SECONDS
        once = options["once"]

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        while self._should_continue():
            started = time.monotonic()
            for collector in get_collectors():
                collector.run()
            elapsed = time.monotonic() - started
            logger.info(
                "Collection iteration finished in %.2fs (%d collectors)",
                elapsed,
                len(get_collectors()),
            )

            if once:
                break

            time.sleep(interval)

    def _should_continue(self) -> bool:
        return self._running

    def _handle_signal(self, signum, frame):
        logger.info("Received signal %s; stopping after current iteration", signum)
        self._running = False
