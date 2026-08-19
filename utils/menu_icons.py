"""Shared inline menu-icon helpers.

The sidebar menu icons live at ``images/menu/<page_key>.png`` (see ``app.py``).
These helpers let page markdown embed the same PNG inline (e.g. beside a page
heading or a Home-page link) so headings match the navigation. When a page has
no PNG yet the helpers return an empty string, so the icon is simply omitted.

Source PNGs can be large (1000+ px); embedding them as base64 data URIs made
pages megabytes heavy and navigation slow. Icons are therefore downscaled once
to small thumbnails cached in ``images/menu/.thumbs/`` (regenerated when the
source PNG changes) and the thumbnail is what gets embedded.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

MENU_DIR = Path(__file__).resolve().parent.parent / "images" / "menu"
THUMB_DIR = MENU_DIR / ".thumbs"
THUMB_PX = 96  # icons display at 18-44 px; 96 px stays crisp on retina

_TOKEN_RE = re.compile(r"__ICON:([A-Za-z_]+)__")

_uri_cache: dict[str, str] = {}


def _thumb_path(source: Path, px: int = THUMB_PX) -> Path:
    thumb = THUMB_DIR / f"{source.stem}_{px}.png"
    if thumb.exists() and thumb.stat().st_mtime >= source.stat().st_mtime:
        return thumb
    from PIL import Image

    THUMB_DIR.mkdir(exist_ok=True)
    with Image.open(source) as img:
        img.thumbnail((px, px), Image.LANCZOS)
        img.save(thumb, "PNG", optimize=True)
    return thumb


def image_thumb_uri(source: Path, px: int = THUMB_PX) -> str:
    """Downscaled-PNG data URI for any image file ('' if the file is absent)."""
    if not source.exists():
        return ""
    try:
        payload = _thumb_path(source, px).read_bytes()
    except Exception:  # noqa: BLE001 - fall back to the full-size image
        payload = source.read_bytes()
    return f"data:image/png;base64,{base64.b64encode(payload).decode('ascii')}"


def menu_icon_uri(key: str) -> str:
    """Return a small thumbnail of ``images/menu/<key>.png`` as a base64 data
    URI, or '' if the source PNG is absent."""
    if key in _uri_cache:
        return _uri_cache[key]
    uri = image_thumb_uri(MENU_DIR / f"{key.lower()}.png")
    _uri_cache[key] = uri
    return uri


def icon_md(key: str) -> str:
    """Inline markdown image for a menu icon (trailing space), or '' if absent."""
    uri = menu_icon_uri(key)
    return f"![menu-icon]({uri}) " if uri else ""


def inject_icons(md: str) -> str:
    """Replace every ``__ICON:PageKey__`` token in ``md`` with its inline image."""
    return _TOKEN_RE.sub(lambda m: icon_md(m.group(1)), md)
