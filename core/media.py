"""Vessel media lookup: which 3D model / image file a reactor has and its static URL.

The files are served from ``images/`` under :data:`IMAGES_URL_PREFIX` (Taipy
``path_mapping`` in app.py, a static mount in the API); the viewer script from
``assets/`` under :data:`ASSETS_URL_PREFIX`.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parent.parent
IMAGES_ROOT = BASE_DIR / "images"
IMG_DIR = IMAGES_ROOT / "reactors"
ASSETS_DIR = BASE_DIR / "assets"
MODEL_VIEWER_JS = ASSETS_DIR / "model-viewer-umd.min.js"

IMAGES_URL_PREFIX = "/vimages"
ASSETS_URL_PREFIX = "/vassets"

IMG_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
MODEL_SUFFIXES = (".glb", ".gltf")

# Reactor IDs are used in file names and glob patterns: no separators or "..".
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def find_vessel_media(reactor_id: str) -> tuple[str, Path] | None:
    """Return ``(kind, path)`` for a vessel's best available media.

    ``kind`` is ``"3d"`` for a navigable model or ``"image"`` for a 2D picture.
    3D ``.glb`` is preferred (self-contained binary), then ``.gltf``, then the
    ``_iso`` image, then ``_side``, then any other matching image.
    """
    rid = str(reactor_id).strip()
    if (not rid or rid.lower() == "nan" or ".." in rid or not _SAFE_ID.match(rid)
            or not IMG_DIR.exists()):
        return None

    for ext in MODEL_SUFFIXES:
        candidate = IMG_DIR / f"{rid}_3d{ext}"
        if candidate.is_file():
            return "3d", candidate

    for view in ("iso", "side"):
        for ext in IMG_SUFFIXES:
            candidate = IMG_DIR / f"{rid}_{view}{ext}"
            if candidate.is_file():
                return "image", candidate

    for p in sorted(IMG_DIR.glob(f"{rid}_*")):
        if p.suffix.lower() in IMG_SUFFIXES:
            return "image", p
    return None


def mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MODEL_SUFFIXES:
        return "model/gltf-binary" if suffix == ".glb" else "model/gltf+json"
    suffix = suffix.lstrip(".")
    return f"image/{'jpeg' if suffix in ('jpg', 'jpeg') else suffix}"


def static_url(path: Path) -> str | None:
    """URL of a file under ``images/``; None for files outside it."""
    try:
        rel = Path(path).resolve().relative_to(IMAGES_ROOT)
    except ValueError:
        return None
    return f"{IMAGES_URL_PREFIX}/{quote(rel.as_posix())}"


def media_caption(reactor_id: str) -> str:
    media = find_vessel_media(reactor_id)
    if media is None:
        return "No vessel imagery found."
    kind, path = media
    label = "Interactive 3D model" if kind == "3d" else "Image"
    return f"{label}: {path.name}"


def vessel_media(reactor_id: str) -> dict | None:
    """{kind: "3d" | "image", url, mime, file, caption} for a reactor, or None."""
    media = find_vessel_media(reactor_id)
    if media is None:
        return None
    kind, path = media
    return {"kind": kind, "url": static_url(path), "mime": mime_type(path), "file": path.name,
            "caption": media_caption(reactor_id)}


# ---------------------------------------------------------------------------
# Icons (source PNGs are 0.5-1 MB; downscaled copies are cached next to them)
# ---------------------------------------------------------------------------
MENU_DIR = IMAGES_ROOT / "menu"
THUMB_DIR = MENU_DIR / ".thumbs"
LOGO = IMAGES_ROOT / "general" / "logo.png"
ICON_SIZES = (48, 96, 192, 240, 360)


def thumbnail(source: Path, px: int = 96) -> Path:
    """Downscaled PNG copy of ``source`` (cached; regenerated when the source changes)."""
    thumb = THUMB_DIR / f"{source.stem}_{px}.png"
    if thumb.exists() and thumb.stat().st_mtime >= source.stat().st_mtime:
        return thumb
    from PIL import Image

    THUMB_DIR.mkdir(exist_ok=True)
    with Image.open(source) as img:
        img.thumbnail((px, px), Image.LANCZOS)
        img.save(thumb, "PNG", optimize=True)
    return thumb


def icon_source(name: str) -> Path | None:
    """``images/menu/<name>.png`` for a page key, the app logo for ``logo``, else None."""
    if name.lower() == "logo":
        return LOGO if LOGO.is_file() else None
    if ".." in name or not _SAFE_ID.match(name):
        return None
    path = MENU_DIR / f"{name.lower()}.png"
    return path if path.is_file() else None
