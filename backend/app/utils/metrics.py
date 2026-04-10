"""
Lightweight in-process metrics helpers.

Kept deliberately simple: a counter and a timer context manager used by
the phase modules and workers. For production you'd swap this with
Prometheus client library — the call-site API would stay the same.
"""
from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from threading import Lock

_counters: dict[str, float] = defaultdict(float)
_timings: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def incr(name: str, value: float = 1.0, **labels) -> None:
    key = _format_key(name, labels)
    with _lock:
        _counters[key] += value


@contextmanager
def timer(name: str, **labels):
    key = _format_key(name, labels)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        with _lock:
            _timings[key].append(time.perf_counter() - t0)


def snapshot() -> dict:
    with _lock:
        return {
            "counters": dict(_counters),
            "timings": {
                k: {
                    "count": len(v),
                    "total_s": round(sum(v), 4),
                    "avg_s": round(sum(v) / len(v), 4) if v else 0.0,
                }
                for k, v in _timings.items()
            },
        }


def _format_key(name: str, labels: dict) -> str:
    if not labels:
        return name
    label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}{{{label_str}}}"
