"""Prometheus metrics exporter for pipeline monitoring."""

from __future__ import annotations

import time
import logging
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── In-memory metrics store (lightweight — no Prometheus dependency required) ──

_metrics: dict[str, Any] = {
    "videos_total": 0,
    "videos_failed": 0,
    "scenes_generated": 0,
    "voices_generated": 0,
    "images_generated": 0,
    "jobs_queued": 0,
    "jobs_completed": 0,
    "jobs_failed": 0,
    "pipeline_duration_seconds": [],
    "render_duration_seconds": [],
}


def increment(metric: str, value: int = 1) -> None:
    """Increment a counter metric."""
    if metric in _metrics and isinstance(_metrics[metric], int):
        _metrics[metric] += value


def record_duration(metric: str, seconds: float) -> None:
    """Record a duration sample."""
    if metric in _metrics and isinstance(_metrics[metric], list):
        _metrics[metric].append(seconds)
        # Keep last 1000 samples
        if len(_metrics[metric]) > 1000:
            _metrics[metric] = _metrics[metric][-1000:]


def get_metrics() -> dict[str, Any]:
    """Return a snapshot of all metrics."""
    result = {}
    for key, value in _metrics.items():
        if isinstance(value, list):
            result[key] = {
                "count": len(value),
                "avg": sum(value) / len(value) if value else 0,
                "min": min(value) if value else 0,
                "max": max(value) if value else 0,
                "last": value[-1] if value else 0,
            }
        else:
            result[key] = value
    return result


def get_prometheus_text() -> str:
    """Export metrics in Prometheus text exposition format."""
    lines: list[str] = []
    for key, value in _metrics.items():
        if isinstance(value, int):
            lines.append(f"# TYPE aiyoutube_{key} counter")
            lines.append(f"aiyoutube_{key} {value}")
        elif isinstance(value, list) and value:
            lines.append(f"# TYPE aiyoutube_{key} summary")
            lines.append(f'aiyoutube_{key}{{quantile="0.5"}} {sorted(value)[len(value)//2]}')
            lines.append(f'aiyoutube_{key}{{quantile="1"}} {max(value)}')
            lines.append(f"aiyoutube_{key}_count {len(value)}")
            lines.append(f"aiyoutube_{key}_sum {sum(value):.3f}")
    return "\n".join(lines) + "\n"


def timed(metric_name: str):
    """Decorator that records the execution time of a function."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start
                record_duration(metric_name, elapsed)
                logger.debug("%s took %.2fs", func.__name__, elapsed)
        return wrapper
    return decorator
