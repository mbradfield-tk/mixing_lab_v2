"""Route modules, each exporting ``ROUTERS``."""
from __future__ import annotations

import unicodedata
from urllib.parse import quote


def attachment(filename: str) -> dict[str, str]:
    """Content-Disposition header safe for non-Latin-1 names (headers are Latin-1 encoded)."""
    fallback = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    fallback = fallback.replace('"', "").replace("\\", "") or "download"
    return {"Content-Disposition":
            f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"}
