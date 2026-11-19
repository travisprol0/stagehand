from django import template
from django.utils import timezone

register = template.Library()


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@register.filter
def bar_color(value) -> str:
    percent = _as_float(value)
    if percent is None:
        return "bg-slate-400 dark:bg-slate-500"
    if percent >= 90:
        return "bg-red-600 dark:bg-red-500"
    if percent >= 70:
        return "bg-amber-500 dark:bg-amber-400"
    return "bg-emerald-600 dark:bg-emerald-500"


@register.filter
def relative_age(moment) -> str:
    if moment is None:
        return "—"
    seconds = int((timezone.now() - moment).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


@register.filter
def duration_short(moment) -> str:
    if moment is None:
        return "—"
    seconds = int((timezone.now() - moment).total_seconds())
    if seconds < 0:
        seconds = 0
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours and len(parts) < 2:
        parts.append(f"{hours}h")
    if minutes and len(parts) < 2:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


@register.filter
def bitrate(bps) -> str:
    rate = _as_float(bps)
    if rate is None:
        return "—"
    units = ("B/s", "KB/s", "MB/s", "GB/s")
    value = rate
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024 or candidate == units[-1]:
            break
        value /= 1024
    if value >= 100 or unit == "B/s":
        return f"{value:.0f} {unit}"
    return f"{value:.1f} {unit}"


@register.filter
def remaining_bytes(used, total):
    try:
        free = int(total) - int(used)
    except (TypeError, ValueError):
        return None
    return max(0, free)


@register.filter
def level_text(value) -> str:
    """Text colour for a utilisation percent: neutral until it matters."""
    percent = _as_float(value)
    if percent is None:
        return "text-slate-400 dark:text-zinc-500"
    if percent >= 90:
        return "text-red-600 dark:text-red-400"
    if percent >= 70:
        return "text-amber-600 dark:text-amber-400"
    return ""


@register.filter
def short_repo(full_name) -> str:
    """owner/repo -> repo."""
    if not full_name:
        return ""
    return str(full_name).rsplit("/", 1)[-1]


@register.simple_tag
def versioned_static(path: str) -> str:
    """Static URL with ?v=<mtime> so browsers drop cached CSS/JS after a deploy
    (the storage backend doesn't hash file names)."""
    from django.contrib.staticfiles import finders
    from django.templatetags.static import static

    url = static(path)
    found = finders.find(path)
    if not found:
        return url
    try:
        import os

        return f"{url}?v={int(os.path.getmtime(found))}"
    except OSError:
        return url
