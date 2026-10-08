"""Golden fixtures and comparison helpers for the API / service regression tests.

``golden/page_outputs.json`` and ``golden/report_outputs.json`` hold the results the
original Taipy pages produced; ``golden/requests.json`` and ``golden/page_parity.json``
hold the page inputs and page-side values those tests compared against, frozen when the
Taipy UI was retired (archived in ``../mixing_lab_taipy_depr``).
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).parent / "golden"
PAGE_OUTPUTS = json.loads((HERE / "page_outputs.json").read_text())
REPORT_OUTPUTS = json.loads((HERE / "report_outputs.json").read_text())
REQUESTS = json.loads((HERE / "requests.json").read_text())
PARITY = json.loads((HERE / "page_parity.json").read_text())


def norm(obj):
    if isinstance(obj, pd.DataFrame):
        return [norm(r) for r in obj.to_dict("records")]
    if isinstance(obj, dict):
        return {str(k): norm(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [norm(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, float, np.integer, np.floating)):
        f = float(obj)
        if math.isnan(f) or math.isinf(f):
            return str(f)
        return float(f"{f:.6g}")
    return obj


def fig_key(fig) -> str:
    return "fig:" + hashlib.sha256(fig.to_json().encode()).hexdigest()[:20]


def snapshot_norm(obj):
    """``norm`` that also replaces figures / bytes with stable keys (report snapshots)."""
    if isinstance(obj, go.Figure):
        return fig_key(obj)
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode() if obj.startswith(b"fig:") else f"bytes[{len(obj)}]"
    if isinstance(obj, pd.DataFrame):
        return [snapshot_norm(r) for r in obj.to_dict("records")]
    if isinstance(obj, dict):
        return {str(k): snapshot_norm(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [snapshot_norm(v) for v in obj]
    return norm(obj)


def first_diff(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: missing on one side"
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"
