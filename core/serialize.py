"""JSON-safe conversion of core results: non-finite floats become None, NumPy and
pandas objects become plain Python, dataclasses become dicts."""
from __future__ import annotations

import dataclasses
import math
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd


def jsonable(obj):
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, Enum):
        return jsonable(obj.value)
    if isinstance(obj, Path):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, pd.DataFrame):
        return [jsonable(r) for r in obj.to_dict("records")]
    if isinstance(obj, (pd.Series, dict)):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, np.ndarray):
        return [jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if obj is pd.NaT or obj is pd.NA:
        return None
    return str(obj)
