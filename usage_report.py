#!/usr/bin/env python3
"""Terminal summary of app usage recorded in ``data/usage.db``.

Reads the SQLite access log written by :mod:`utils.usage` and prints a concise
text report — no Taipy, no pandas required. Run from the project root::

    python usage_report.py

Options::

    python usage_report.py --days 30      # limit daily breakdown to last 30 days
    python usage_report.py --top 20       # show top 20 IPs
    python usage_report.py --recent 15    # list the 15 most recent accesses
    python usage_report.py --db /path/to/usage.db
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DEFAULT_DB = Path(__file__).resolve().parent / "data" / "usage.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"No usage database found at: {db_path}")

    # The app opens the DB in WAL mode. A plain ``mode=ro`` connection still
    # needs to write the ``-shm``/``-wal`` shared-memory files, which fails when
    # the report is run by a user without write access to the DB directory
    # ("attempt to write a readonly database"). ``immutable=1`` reads the file
    # with no locking or shm writes, so it works read-only in that case.
    attempts = (
        f"file:{db_path}?mode=ro",              # normal read-only (non-WAL / writable shm)
        f"file:{db_path}?mode=ro&immutable=1",  # pure read, no shm/wal writes
    )
    last_err: Exception | None = None
    for uri in attempts:
        try:
            con = sqlite3.connect(uri, uri=True)
            con.row_factory = sqlite3.Row
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "access_log" not in tables:
                con.close()
                raise SystemExit(f"'access_log' table not found in {db_path}")
            return con
        except sqlite3.OperationalError as exc:
            last_err = exc
            continue

    raise SystemExit(
        f"Could not open usage database read-only: {db_path}\n  ({last_err})"
    )


def _fmt_local(ts_utc: str | None) -> str:
    """Format a stored UTC ISO timestamp as local time, best-effort."""
    if not ts_utc:
        return "—"
    try:
        dt = datetime.fromisoformat(ts_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return ts_utc


def _hr(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def build_report(con: sqlite3.Connection, *, days: int | None,
                 top: int, recent: int) -> None:
    total = con.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
    if total == 0:
        print("No usage has been recorded yet.")
        return

    unique_ips = con.execute(
        "SELECT COUNT(DISTINCT client_ip) FROM access_log"
    ).fetchone()[0]
    first_seen, last_seen = con.execute(
        "SELECT MIN(ts_utc), MAX(ts_utc) FROM access_log"
    ).fetchone()

    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    last7 = con.execute(
        "SELECT COUNT(*) FROM access_log WHERE ts_utc >= ?", (week_ago,)
    ).fetchone()[0]

    print("=" * 52)
    print("  MIXING LAB 2.0 — USAGE SUMMARY")
    print("=" * 52)
    print(f"Total accesses     : {total:,}")
    print(f"Unique IP addresses: {unique_ips:,}")
    print(f"Accesses (7 days)  : {last7:,}")
    print(f"First access       : {_fmt_local(first_seen)}")
    print(f"Last access        : {_fmt_local(last_seen)}")

    # Accesses per day
    day_query = (
        "SELECT substr(ts_utc, 1, 10) AS day, COUNT(*) AS n "
        "FROM access_log "
    )
    params: tuple = ()
    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        day_query += "WHERE ts_utc >= ? "
        params = (cutoff,)
    day_query += "GROUP BY day ORDER BY day"
    day_rows = con.execute(day_query, params).fetchall()

    _hr(f"Accesses per day{f' (last {days} days)' if days else ''}")
    if day_rows:
        peak = max(r["n"] for r in day_rows)
        for r in day_rows:
            bar = "#" * max(1, round(r["n"] / peak * 30))
            print(f"  {r['day']}  {r['n']:>5,}  {bar}")
    else:
        print("  (no data in range)")

    # Top IPs
    ip_rows = con.execute(
        "SELECT client_ip, COUNT(*) AS n, MAX(ts_utc) AS last_seen "
        "FROM access_log GROUP BY client_ip ORDER BY n DESC LIMIT ?",
        (top,),
    ).fetchall()

    _hr(f"Top {top} client IP addresses")
    print(f"  {'IP address':<24}{'Hits':>7}  Last seen")
    for r in ip_rows:
        ip = r["client_ip"] or "(unknown)"
        print(f"  {ip:<24}{r['n']:>7,}  {_fmt_local(r['last_seen'])}")

    # Recent activity
    if recent > 0:
        rec_rows = con.execute(
            "SELECT ts_utc, client_ip, page "
            "FROM access_log ORDER BY ts_utc DESC LIMIT ?",
            (recent,),
        ).fetchall()
        _hr(f"{recent} most recent accesses")
        for r in rec_rows:
            ip = r["client_ip"] or "(unknown)"
            page = r["page"] or "—"
            print(f"  {_fmt_local(r['ts_utc']):<26}{ip:<24}{page}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print a text summary of Mixing Lab 2.0 usage from usage.db."
    )
    parser.add_argument(
        "--db", type=Path, default=_DEFAULT_DB,
        help=f"Path to usage.db (default: {_DEFAULT_DB})",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Limit the daily breakdown to the last N days (default: all).",
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="Number of top IP addresses to show (default: 10).",
    )
    parser.add_argument(
        "--recent", type=int, default=10,
        help="Number of most-recent accesses to list (default: 10; 0 to hide).",
    )
    args = parser.parse_args()

    con = _connect(args.db)
    try:
        build_report(con, days=args.days, top=args.top, recent=args.recent)
    finally:
        con.close()


if __name__ == "__main__":
    main()
