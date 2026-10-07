"""CRUD routes for the database tables, built from :mod:`core.repositories`."""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import (
    APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile, status,
)

from api.security import current_principal
from core import repositories as repos
from core import tables
from core import vessel_import as vimport
from core.auth import Principal
from core.serialize import jsonable

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
Names = Annotated[list[str] | None, Query()]


async def read_upload(file: UploadFile) -> bytes:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not raw:
        raise ValueError("The uploaded file is empty.")
    return raw


def _csv_response(df, filename: str) -> Response:
    return Response(tables.csv_bytes(df), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def table_router(repo: repos.Repository, prefix: str, tag: str) -> APIRouter:
    """List / search, get, create, update, delete, import and export for one table."""
    router = APIRouter(prefix=prefix, tags=[tag])
    noun = repo.label

    @router.get("", summary=f"List {noun}s (optionally filtered)")
    def list_records(q: str = "", field: str | None = None,
                     op: str = tables.SEARCH_CONTAINS) -> dict[str, Any]:
        df, note = repo.search(repo.load(), q, [field] if field else None, op)
        return {"records": jsonable(df), "count": len(df), "status": note}

    @router.get("/names", summary=f"{noun.capitalize()} names")
    def names() -> list[str]:
        return repo.names()

    @router.get("/export", summary="Download the table as CSV")
    def export() -> Response:
        return _csv_response(repo.load(), f"{repo.table}.csv")

    @router.get("/columns", summary="Column names and friendly labels")
    def columns() -> list[dict[str, str]]:
        return [{"column": c, "label": tables.friendly(c)} for c in repo.load().columns]

    @router.get("/{name:path}", summary=f"One {noun}")
    def get(name: str) -> dict[str, Any]:
        return jsonable(repo.get(name))

    @router.post("", status_code=status.HTTP_201_CREATED, summary=f"Add a {noun} (validated)")
    def create(data: dict[str, Any] = Body(...),
               principal: Principal = Depends(current_principal)) -> dict[str, Any]:
        df = repo.create(repo.load(), data, principal)
        return jsonable(df.iloc[-1].to_dict())

    @router.patch("/{name:path}", summary=f"Change fields of a {noun}")
    def update(name: str, changes: dict[str, Any] = Body(...),
               principal: Principal = Depends(current_principal)) -> dict[str, Any]:
        new_name = changes.get(repo.name_col, name)
        df = repo.update(repo.load(), name, changes, principal)
        return jsonable(repo.get(new_name, df))

    @router.delete("/{name:path}", status_code=status.HTTP_204_NO_CONTENT,
                   summary=f"Delete a {noun}")
    def delete(name: str, principal: Principal = Depends(current_principal)) -> Response:
        df = repo.load()
        repo.delete(df, {"index": repo.index_of(df, name)}, principal)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if isinstance(repo, repos.ReactorRepository):
        @router.post("/import/preview", summary="Reviewable changes in an uploaded vessel CSV")
        async def import_preview(file: UploadFile = File(...)) -> list[dict[str, Any]]:
            new_df = tables.read_upload_csv(await read_upload(file))
            changes = repo.import_changes(repo.load(), new_df)
            return [{"id": i, **jsonable(c)} for i, c in enumerate(changes)]

        @router.post("/import/apply", summary="Apply the accepted changes of an uploaded vessel CSV")
        async def import_apply(file: UploadFile = File(...),
                               accept: str = Form(..., description="JSON list of change ids"),
                               principal: Principal = Depends(current_principal)) -> dict:
            try:
                accepted = {int(i) for i in json.loads(accept)}
            except (TypeError, ValueError):
                raise ValueError("accept must be a JSON list of change ids.") from None
            new_df = tables.read_upload_csv(await read_upload(file))
            working = repo.load()
            changes = repo.import_changes(working, new_df)
            for i, change in enumerate(changes):
                if i in accepted:
                    working = vimport.apply_import_change(working, change)
            df, assigned = repo.apply_import(working, principal)
            return {"applied": len(accepted & set(range(len(changes)))),
                    "skipped": len(changes) - len(accepted & set(range(len(changes)))),
                    "new_reactor_ids": assigned, "count": len(df)}
    else:
        @router.put("/import", summary="Replace the table with an uploaded CSV")
        async def import_replace(file: UploadFile = File(...),
                                 principal: Principal = Depends(current_principal)) -> dict:
            df = repo.replace(tables.read_upload_csv(await read_upload(file)), principal)
            return {"count": len(df)}

    return router


def results_router() -> APIRouter:
    router = APIRouter(prefix="/results", tags=["Recorded results"])
    repo = repos.results

    def _filtered(reactor: list[str] | None, reaction: list[str] | None,
                  fluid: list[str] | None):
        return repos.filter_results(repo.load(), reactor, reaction, fluid)

    @router.get("", summary="Saved results (filter by reactor / reaction / fluid)")
    def list_results(reactor: Names = None, reaction: Names = None,
                     fluid: Names = None) -> dict[str, Any]:
        df = _filtered(reactor, reaction, fluid)
        safe, potential, limited = repos.result_counts(df)
        return {"records": jsonable(df), "count": len(df),
                "counts": {"reaction_limited": safe, "potentially_sensitive": potential,
                           "mixing_sensitive": limited}}

    @router.get("/export", summary="Download (filtered) results as CSV")
    def export(reactor: Names = None, reaction: Names = None, fluid: Names = None) -> Response:
        return _csv_response(_filtered(reactor, reaction, fluid), "mixing_lab_results.csv")

    @router.post("", status_code=status.HTTP_201_CREATED, summary="Save results")
    def append(rows: list[dict[str, Any]] = Body(..., min_length=1),
               principal: Principal = Depends(current_principal)) -> dict[str, int]:
        return {"count": repo.append(rows, principal)}

    @router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Clear all results")
    def clear(principal: Principal = Depends(current_principal)) -> Response:
        repo.clear(repo.load(), principal)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


ROUTERS = [
    table_router(repos.reactors, "/vessels", "Vessels"),
    table_router(repos.reactions, "/reactions", "Reactions"),
    table_router(repos.particles, "/particles", "Particles"),
    table_router(repos.fluids, "/fluids/custom", "Custom fluids"),
    results_router(),
]
