"""Resolve and render vessel imagery (3D .glb/.gltf preferred, else 2D .png).

Builds a self-contained HTML document that can be served by Taipy's ``part``
element (``content`` property) and shown inside an iframe.  3D models use
Google's ``<model-viewer>`` web component, vendored locally and inlined so the
viewer works offline.  Both the model and 2D images are embedded as base64
data URIs, so no static file server is required.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "images" / "reactors"
MODEL_VIEWER_JS = BASE_DIR / "assets" / "model-viewer-umd.min.js"
MODEL_VIEWER_CDN = "https://ajax.googleapis.com/ajax/libs/model-viewer/3.5.0/model-viewer.min.js"

IMG_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
MODEL_SUFFIXES = (".glb", ".gltf")


def find_vessel_media(reactor_id: str) -> tuple[str, Path] | None:
    """Return ``(kind, path)`` for a vessel's best available media.

    ``kind`` is ``"3d"`` for a navigable model or ``"image"`` for a 2D picture.
    3D ``.glb`` is preferred (self-contained binary), then ``.gltf``, then the
    ``_iso`` image, then ``_side``, then any other matching image.
    """
    rid = str(reactor_id).strip()
    if not rid or rid.lower() == "nan" or not IMG_DIR.exists():
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


@lru_cache(maxsize=64)
def _data_uri(path_str: str, mime: str) -> str:
    raw = Path(path_str).read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


@lru_cache(maxsize=1)
def _model_viewer_script() -> str:
    if MODEL_VIEWER_JS.is_file():
        js = MODEL_VIEWER_JS.read_text(encoding="utf-8").replace("</script>", "<\\/script>")
        return f"<script>{js}</script>"
    return f'<script type="module" src="{MODEL_VIEWER_CDN}"></script>'


def _placeholder_html(message: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style=\"margin:0;display:flex;align-items:center;justify-content:center;"
        "height:100%;font-family:sans-serif;color:#666;background:#f5f5f5;\">"
        f"<div>{message}</div></body></html>"
    )


def build_vessel_viewer_html(reactor_id: str, height: int = 360) -> str:
    """Build a self-contained HTML document showing the vessel's best media."""
    media = find_vessel_media(reactor_id)
    if media is None:
        return _placeholder_html("No image or 3D model available for this vessel.")

    kind, path = media
    if kind == "3d":
        mime = "model/gltf-binary" if path.suffix.lower() == ".glb" else "model/gltf+json"
        src = _data_uri(str(path), mime)
        script = _model_viewer_script()
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"{script}</head>"
            "<body style='margin:0;'>"
            f"<model-viewer src=\"{src}\" camera-controls auto-rotate "
            "rotation-per-second=\"20deg\" interaction-prompt=\"none\" "
            "shadow-intensity=\"1\" exposure=\"1\" "
            f"style=\"width:100%;height:{height}px;background:#f5f5f5;border-radius:4px;\">"
            "</model-viewer></body></html>"
        )

    suffix = path.suffix.lower().lstrip(".")
    mime = f"image/{'jpeg' if suffix in ('jpg', 'jpeg') else suffix}"
    src = _data_uri(str(path), mime)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;display:flex;align-items:center;justify-content:center;"
        "background:#f5f5f5;'>"
        f"<img src=\"{src}\" alt=\"vessel\" "
        f"style=\"max-width:100%;max-height:{height}px;object-fit:contain;border-radius:4px;\"/>"
        "</body></html>"
    )


def media_caption(reactor_id: str) -> str:
    media = find_vessel_media(reactor_id)
    if media is None:
        return "No vessel imagery found."
    kind, path = media
    label = "Interactive 3D model" if kind == "3d" else "Image"
    return f"{label}: {path.name}"


def build_image_html(image_path, alt: str = "diagram", background: str = "#ffffff") -> str:
    """Return a self-contained HTML document embedding a local image (base64).

    Scales to the container width (``height:auto``) so tall diagrams stay
    readable; shown inside a Taipy ``part`` ``content`` iframe.
    """
    p = Path(image_path)
    if not p.is_file():
        return _placeholder_html(f"Image not found: {p.name}")
    suffix = p.suffix.lower().lstrip(".")
    mime = f"image/{'jpeg' if suffix in ('jpg', 'jpeg') else suffix}"
    src = _data_uri(str(p), mime)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        f"<body style='margin:0;display:flex;justify-content:center;"
        f"align-items:flex-start;background:{background};'>"
        f"<img src=\"{src}\" alt=\"{alt}\" style=\"max-width:100%;height:auto;\"/>"
        "</body></html>"
    )



def _viewer_card_body(name: str, reactor_id: str, height: int) -> str:
    """Return the inner HTML (title + media) for one vessel card."""
    media = find_vessel_media(reactor_id)
    title = (f"<div style=\"font-weight:600;color:#333;margin-bottom:6px;"
             f"font-family:sans-serif;font-size:14px;\">{name}</div>")
    if media is None:
        body = (f"<div style=\"height:{height}px;display:flex;align-items:center;"
                "justify-content:center;color:#999;background:#f5f5f5;border-radius:4px;"
                "font-family:sans-serif;font-size:13px;\">No image available</div>")
        return title + body
    kind, path = media
    if kind == "3d":
        mime = "model/gltf-binary" if path.suffix.lower() == ".glb" else "model/gltf+json"
        src = _data_uri(str(path), mime)
        body = (
            f"<model-viewer src=\"{src}\" camera-controls auto-rotate "
            "rotation-per-second=\"20deg\" interaction-prompt=\"none\" "
            "shadow-intensity=\"1\" exposure=\"1\" "
            f"style=\"width:100%;height:{height}px;background:#f5f5f5;border-radius:4px;\">"
            "</model-viewer>")
        return title + body
    suffix = path.suffix.lower().lstrip(".")
    mime = f"image/{'jpeg' if suffix in ('jpg', 'jpeg') else suffix}"
    src = _data_uri(str(path), mime)
    body = (f"<div style=\"height:{height}px;display:flex;align-items:center;"
            "justify-content:center;background:#f5f5f5;border-radius:4px;\">"
            f"<img src=\"{src}\" alt=\"{name}\" "
            f"style=\"max-width:100%;max-height:{height}px;object-fit:contain;\"/></div>")
    return title + body


def build_multi_vessel_viewer_html(items: list[tuple[str, str]], height: int = 280) -> str:
    """Build one HTML document showing several vessels side-by-side.

    ``items`` is a list of ``(display_name, reactor_id)`` tuples. 3D models are
    navigable; otherwise the best 2D image (or a placeholder) is shown. The row
    scrolls horizontally when it overflows.
    """
    if not items:
        return _placeholder_html("Select one or more vessels to preview.")
    needs_3d = any((find_vessel_media(rid) or ("", None))[0] == "3d" for _n, rid in items)
    script = _model_viewer_script() if needs_3d else ""
    cards = "".join(
        "<div style=\"flex:0 0 auto;width:260px;border:1px solid #E6E6E6;"
        "border-radius:8px;padding:8px;background:#ffffff;\">"
        f"{_viewer_card_body(name, rid, height)}</div>"
        for name, rid in items
    )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"{script}</head>"
        "<body style='margin:0;background:transparent;'>"
        "<div style=\"display:flex;gap:12px;overflow-x:auto;padding:6px 4px 12px;\">"
        f"{cards}</div></body></html>"
    )
