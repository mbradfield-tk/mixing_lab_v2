"""Lightweight app-usage logging (port of the original mixing_lab feature).

Records one row per app load (timestamp UTC, client IP, raw ``X-Forwarded-For``,
user agent, and the requested page) into a local SQLite database at
``data/usage.db``. The hook is installed on the Flask app that Taipy runs on
(see ``install_usage_logging`` in ``app.py``); because Taipy is a single-page
app, only the initial document GET is logged — client-side page navigation does
not create rows, so each row ≈ one browser (re)load of the app.

Behind a reverse proxy (nginx, gunicorn behind a load balancer, corporate
gateway) the direct socket peer is the proxy, so the real client IP is read from
the ``X-Forwarded-For`` header when present. Configure the proxy to set it.

Querying the log
----------------
* Terminal summary: ``python usage_report.py`` (see ``--help`` for options).
* Any SQLite client, e.g.::

      sqlite3 data/usage.db "SELECT client_ip, COUNT(*) FROM access_log GROUP BY client_ip;"
      sqlite3 data/usage.db "SELECT substr(ts_utc,1,10) d, COUNT(*) FROM access_log GROUP BY d;"

* Programmatically: :func:`fetch_access_log` returns a pandas DataFrame.

Load-balancer health checks hitting ``/`` are logged too; filter them out in
queries via their ``user_agent`` (e.g. ``ELB-HealthChecker``) if needed.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "usage.db"
_LOCK = threading.Lock()
_INITIALISED = False


def _init_db() -> None:
    global _INITIALISED
    if _INITIALISED:
        return
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as con:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS access_log (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc         TEXT NOT NULL,
                client_ip      TEXT,
                forwarded_for  TEXT,
                user_agent     TEXT,
                page           TEXT
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_access_ts ON access_log (ts_utc)")
    _INITIALISED = True


def log_access(*, client_ip: str | None, forwarded_for: str | None,
               user_agent: str | None, page: str | None) -> None:
    """Record one access event. Never raises — logging must not break the app."""
    try:
        _init_db()
        row = (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            client_ip, forwarded_for, user_agent, page,
        )
        with _LOCK, sqlite3.connect(_DB_PATH) as con:
            con.execute(
                "INSERT INTO access_log "
                "(ts_utc, client_ip, forwarded_for, user_agent, page) "
                "VALUES (?, ?, ?, ?, ?)",
                row,
            )
    except Exception:
        pass


def install_usage_logging(flask_app, page_names) -> None:
    """Register a ``before_request`` hook that logs app-document GETs.

    Only the SPA document requests count as accesses: the root path and the
    per-page deep-link paths (``/Home``, ``/Vessel_Assessment``, ...). Static
    assets, websocket traffic and Taipy's internal endpoints are ignored.
    """
    names = {str(p).strip("/") for p in page_names}

    @flask_app.before_request
    def _usage_hook():  # pragma: no cover - exercised via the running app
        from flask import request

        if request.method != "GET":
            return
        path = request.path.strip("/")
        if path and path not in names:
            return
        xff = request.headers.get("X-Forwarded-For")
        ip = xff.split(",")[0].strip() if xff else request.remote_addr
        log_access(client_ip=ip, forwarded_for=xff,
                   user_agent=request.headers.get("User-Agent"),
                   page=path or "/")


def fetch_access_log():
    """Full access log as a pandas ``DataFrame`` (newest first).

    ``ts_utc`` is parsed to timezone-aware datetimes. Returns an empty frame
    with the expected columns if nothing has been recorded yet.
    """
    import pandas as pd

    columns = ["id", "ts_utc", "client_ip", "forwarded_for", "user_agent", "page"]
    try:
        _init_db()
        with sqlite3.connect(_DB_PATH) as con:
            df = pd.read_sql_query("SELECT * FROM access_log ORDER BY ts_utc DESC", con)
        if not df.empty:
            df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
        return df
    except Exception:
        return pd.DataFrame(columns=columns)
