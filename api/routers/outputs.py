"""Report (PDF), chart (Plotly JSON), media and reference routes."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool

from core import media, records
from core import schemas as s
from core.vessel_capacity import fill_summary
from reports import charts, service
from viz.vessel_schematic import build_vessel_schematic

outputs = APIRouter(tags=["Reports & charts"])
reference = APIRouter(tags=["Reference"])

EQUATIONS_JSON = records.DATA_DIR / "equations_reference.json"


@outputs.post("/reports/{kind}", summary="Build a PDF report",
              responses={200: {"content": {"application/pdf": {}}}},
              description="kind: " + ", ".join(service.REPORTS))
async def report(kind: str, payload: dict[str, Any] = Body(...)) -> Response:
    if kind not in service.REPORTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown report '{kind}'.")
    pdf = await run_in_threadpool(service.render_report, kind, payload)
    return Response(pdf.content, media_type=pdf.media_type,
                    headers={"Content-Disposition": f'attachment; filename="{pdf.filename}"'})


@outputs.post("/charts/{kind}", summary="Plotly figure JSON for react-plotly.js",
              description="kind: " + ", ".join(charts.CHARTS))
def chart(kind: str, payload: dict[str, Any] = Body(...)) -> s.ChartResult:
    if kind not in charts.CHARTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown chart '{kind}'.")
    return charts.render_chart(kind, payload)


def _reactor(name: str):
    row = records.reactor_row(name)
    if row.empty:
        raise LookupError(f"Unknown vessel '{name}'.")
    return row


@reference.get("/media/vessels/{name}", summary="Best 3D model / image of a vessel")
def vessel_media(name: str) -> dict[str, Any]:
    _reactor(name)
    found = media.vessel_media(records.reactor_id(name))
    if found is None:
        raise LookupError(f"No imagery for vessel '{name}'.")
    return found


@reference.get("/media/vessels/{name}/fill", summary="Liquid level and warnings at a fill volume")
def vessel_fill(name: str, fill_L: float | None = Query(None, ge=0)) -> dict[str, Any]:
    return fill_summary(_reactor(name), fill_L)


@reference.get("/media/vessels/{name}/schematic.png", summary="2D cross-section drawing",
               responses={200: {"content": {"image/png": {}}}})
def vessel_schematic(name: str, fill_L: float | None = Query(None, ge=0)) -> Response:
    res = build_vessel_schematic(_reactor(name), fill_L, as_png=True)
    return Response(res["png"], media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@lru_cache(maxsize=1)
def _equations(mtime: float) -> dict:
    return json.loads(EQUATIONS_JSON.read_text(encoding="utf-8"))


@reference.get("/equations", summary="Equations reference (sections with pre-rendered images)")
def equations() -> dict:
    return _equations(EQUATIONS_JSON.stat().st_mtime)


ROUTERS = [outputs, reference]
