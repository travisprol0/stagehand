"""Chart data helpers for server-rendered SVG time series."""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from monitor.models import Host, MetricSnapshot

DOWNSAMPLE_THRESHOLD = 200
MAX_CHART_POINTS = 120
CHART_WIDTH = 400
CHART_HEIGHT = 100
CHART_PADDING = 8


@dataclass(frozen=True)
class HostChartData:
    cpu_polyline: str
    memory_polyline: str
    disk_polyline: str
    cpu_area: str
    memory_area: str
    disk_area: str
    time_labels: list[str]
    start_label: str
    end_label: str


def downsample_points(points: list, max_points: int = MAX_CHART_POINTS) -> list:
    if len(points) <= DOWNSAMPLE_THRESHOLD:
        return list(points)
    if len(points) <= max_points:
        return list(points)

    step = (len(points) - 1) / (max_points - 1)
    indices = [round(index * step) for index in range(max_points)]
    return [points[index] for index in indices]


def build_polyline(
    values: list[float],
    *,
    width: int = CHART_WIDTH,
    height: int = CHART_HEIGHT,
    padding: int = CHART_PADDING,
    value_max: float = 100.0,
) -> str:
    if len(values) < 2:
        return ""

    plot_width = width - (2 * padding)
    plot_height = height - (2 * padding)
    coords: list[str] = []

    for index, raw_value in enumerate(values):
        x = padding + (index / (len(values) - 1)) * plot_width
        value = 0.0 if raw_value is None else float(raw_value)
        clamped = max(0.0, min(value, value_max))
        y = padding + plot_height - (clamped / value_max) * plot_height
        coords.append(f"{x:.1f},{y:.1f}")

    return " ".join(coords)


def build_area(
    values: list[float],
    *,
    width: int = CHART_WIDTH,
    height: int = CHART_HEIGHT,
    padding: int = CHART_PADDING,
    value_max: float = 100.0,
) -> str:
    line = build_polyline(
        values,
        width=width,
        height=height,
        padding=padding,
        value_max=value_max,
    )
    if not line:
        return ""
    points = line.split()
    first_x = points[0].split(",")[0]
    last_x = points[-1].split(",")[0]
    baseline = height - padding
    return f"{first_x},{baseline:.1f} {line} {last_x},{baseline:.1f}"


def get_host_chart_data(host: Host, *, minutes: int = 60) -> HostChartData | None:
    snapshots = list(MetricSnapshot.objects.for_host(host, minutes=minutes))
    snapshots = downsample_points(snapshots)
    if not snapshots:
        return None

    cpu_values = [snapshot.cpu_percent or 0.0 for snapshot in snapshots]
    memory_values = [snapshot.memory_percent or 0.0 for snapshot in snapshots]
    disk_values = [snapshot.disk_percent or 0.0 for snapshot in snapshots]
    time_labels = [
        timezone.localtime(snapshot.recorded_at).strftime("%H:%M")
        for snapshot in snapshots
    ]

    return HostChartData(
        cpu_polyline=build_polyline(cpu_values),
        memory_polyline=build_polyline(memory_values),
        disk_polyline=build_polyline(disk_values),
        cpu_area=build_area(cpu_values),
        memory_area=build_area(memory_values),
        disk_area=build_area(disk_values),
        time_labels=time_labels,
        start_label=time_labels[0],
        end_label=time_labels[-1],
    )


SPARK_WIDTH = 120
SPARK_HEIGHT = 28
SPARK_POINTS = 40


@dataclass(frozen=True)
class Sparkline:
    line: str
    area: str
    peak: float


def _even_sample(values: list, max_points: int) -> list:
    if len(values) <= max_points:
        return list(values)
    step = (len(values) - 1) / (max_points - 1)
    return [values[round(index * step)] for index in range(max_points)]


def build_sparkline(
    values: list[float | None],
    *,
    value_max: float | None = None,
    floor: float = 0.0,
) -> Sparkline | None:
    """Small inline trend line. `value_max=None` scales to the series peak."""
    clean = [float(v) for v in values if v is not None]
    if len(clean) < 2:
        return None
    clean = _even_sample(clean, SPARK_POINTS)
    peak = max(clean)
    scale = value_max if value_max is not None else max(peak * 1.15, floor, 1e-9)
    kwargs = {
        "width": SPARK_WIDTH,
        "height": SPARK_HEIGHT,
        "padding": 2,
        "value_max": scale,
    }
    return Sparkline(
        line=build_polyline(clean, **kwargs),
        area=build_area(clean, **kwargs),
        peak=peak,
    )


def get_host_sparklines(host: Host, *, minutes: int = 60) -> dict:
    rows = list(
        MetricSnapshot.objects.for_host(host, minutes=minutes).values_list(
            "cpu_percent", "memory_percent"
        )
    )
    return {
        "cpu": build_sparkline([row[0] for row in rows], value_max=100.0),
        "memory": build_sparkline([row[1] for row in rows], value_max=100.0),
    }


def get_container_sparklines(host: Host, *, minutes: int = 60) -> dict[int, dict]:
    """container pk -> {"cpu": Sparkline, "memory": Sparkline} in one query."""
    since = timezone.now() - timezone.timedelta(minutes=minutes)
    rows = (
        MetricSnapshot.objects.filter(
            host=host,
            subject_type="container",
            recorded_at__gte=since,
            container__isnull=False,
        )
        .order_by("container_id", "recorded_at")
        .values_list("container_id", "cpu_percent", "memory_bytes")
    )
    series: dict[int, tuple[list, list]] = {}
    for container_id, cpu, memory in rows:
        cpu_values, memory_values = series.setdefault(container_id, ([], []))
        cpu_values.append(cpu)
        memory_values.append(memory)
    return {
        container_id: {
            "cpu": build_sparkline(cpu_values, floor=5.0),
            "memory": build_sparkline(memory_values),
        }
        for container_id, (cpu_values, memory_values) in series.items()
    }
