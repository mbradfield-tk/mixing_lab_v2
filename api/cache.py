"""In-process cache for slow, deterministic API results (PDFs, charts, surfaces, comparisons).

The key is the endpoint name, the validated request (as canonical JSON) and a
data version: the modification times of every file under ``data/`` that the
calculations read, plus today's date (PDFs print it). Editing a database
therefore invalidates every cached result. Errors are never cached.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from core.records import DATA_DIR

T = TypeVar("T")

MAX_ENTRIES = 48
_DATA_GLOBS = ("*.csv", "*.json")

_lock = threading.Lock()
_entries: OrderedDict[tuple, Any] = OrderedDict()
stats = {"hits": 0, "misses": 0}


def data_version() -> tuple:
    files = sorted(p for g in _DATA_GLOBS for p in DATA_DIR.glob(g))
    return (dt.date.today().isoformat(), *((p.name, p.stat().st_mtime_ns) for p in files))


def _canonical(payload: Any) -> str:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, default=str)


def cached(name: str, payload: Any, compute: Callable[[], T]) -> T:
    """Return the cached result for (name, payload, data version), computing it on a miss."""
    key = (name, _canonical(payload), data_version())
    with _lock:
        if key in _entries:
            _entries.move_to_end(key)
            stats["hits"] += 1
            return _entries[key]
    result = compute()
    with _lock:
        stats["misses"] += 1
        _entries[key] = result
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)
    return result


def clear() -> None:
    with _lock:
        _entries.clear()
        stats.update(hits=0, misses=0)
