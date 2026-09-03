"""Chart data helpers for server-rendered SVG time series."""

from __future__ import annotations

from dataclasses import dataclass

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
        if len(values) == 1:
            x = padding
        else:
            x = padding + (index / (len(values) - 1)) * plot_width
        value = 0.0 if raw_value is None else float(raw_value)
        clamped = max(0.0, min(value, value_max))
        y = padding + plot_height - (clamped / value_max) * plot_height
        coords.append(f"{x:.1f},{y:.1f}")

    return " ".join(coords)


def get_host_chart_data(host: Host, *, minutes: int = 60) -> HostChartData | None:
    snapshots = list(MetricSnapshot.objects.for_host(host, minutes=minutes))
    snapshots = downsample_points(snapshots)
    if not snapshots:
        return None

    cpu_values = [snapshot.cpu_percent or 0.0 for snapshot in snapshots]
    memory_values = [snapshot.memory_percent or 0.0 for snapshot in snapshots]
    time_labels = [snapshot.recorded_at.strftime("%H:%M") for snapshot in snapshots]

    return HostChartData(
        cpu_polyline=build_polyline(cpu_values),
        memory_polyline=build_polyline(memory_values),
        time_labels=time_labels,
        start_label=time_labels[0],
        end_label=time_labels[-1],
    )
