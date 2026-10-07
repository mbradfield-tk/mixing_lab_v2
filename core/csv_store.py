"""Thread-safe CSV persistence with an mtime-keyed read cache.

One lock guards all CSV I/O so concurrent sessions can't interleave writes;
writes go to a temp file + ``os.replace`` so a crash never corrupts a database.
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import pandas as pd

_io_lock = threading.Lock()
# str(path) -> (mtime, DataFrame)
_fresh_cache: dict[str, tuple[float, pd.DataFrame]] = {}


def _atomic_write(df: pd.DataFrame, path: Path) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            df.to_csv(fh, index=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    _fresh_cache.pop(str(path), None)


def save_csv(df: pd.DataFrame, path: Path) -> None:
    """Persist ``df`` to ``path`` atomically (lock-guarded temp file + replace)."""
    with _io_lock:
        _atomic_write(df, path)


def append_csv(new_df: pd.DataFrame, path: Path) -> int:
    """Append rows to a CSV atomically; returns the resulting row count."""
    with _io_lock:
        existing = pd.read_csv(path) if path.exists() else None
        out = (new_df if existing is None or existing.empty
               else pd.concat([existing, new_df], ignore_index=True))
        _atomic_write(out, path)
        return len(out)


def fresh_csv(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    """Latest contents of ``path``, re-read only when its mtime changes.

    The returned frame is shared across sessions — treat it as read-only.
    ``columns`` are guaranteed present (added empty when missing) so lookups
    never raise ``KeyError`` on a malformed or missing file.
    """
    key = str(path)
    with _io_lock:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return pd.DataFrame(columns=columns or [])
        cached = _fresh_cache.get(key)
        if cached is not None and cached[0] == mtime:
            for c in columns or []:
                if c not in cached[1].columns:
                    cached[1][c] = pd.NA
            return cached[1]
        try:
            df = pd.read_csv(path).reset_index(drop=True)
        except Exception:  # unreadable/half-synced file — keep serving the last good copy
            return cached[1] if cached is not None else pd.DataFrame(columns=columns or [])
        for c in columns or []:
            if c not in df.columns:
                df[c] = pd.NA
        _fresh_cache[key] = (mtime, df)
        return df
