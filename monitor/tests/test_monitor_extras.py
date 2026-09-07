from datetime import timedelta

from django.utils import timezone

from monitor.templatetags.monitor_extras import (
    bar_color,
    bitrate,
    duration_short,
    relative_age,
)


def test_bar_color_thresholds():
    assert "emerald" in bar_color(10)
    assert "amber" in bar_color(75)
    assert "red" in bar_color(95)
    assert "slate" in bar_color(None)


def test_relative_age_seconds():
    moment = timezone.now() - timedelta(seconds=12)
    assert relative_age(moment) == "12s ago"


def test_duration_short_days_and_hours():
    moment = timezone.now() - timedelta(days=12, hours=4, minutes=10)
    assert duration_short(moment) == "12d 4h"


def test_bitrate_formats_units():
    assert bitrate(None) == "—"
    assert bitrate(800) == "800 B/s"
    assert "KB/s" in bitrate(80_000)
    assert "MB/s" in bitrate(1_200_000)
