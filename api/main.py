"""FastAPI application: ``uvicorn api.main:app`` (or ``create_app()``).

All routes live under ``/api/v1``. Domain errors map to HTTP status codes in one
place: ``LookupError`` 404, ``ValueError`` / pydantic validation 422,
``PermissionError`` 403. Unexpected errors return a generic 500 (details only
in the server log). Vessel media and the 3D-viewer script are served as static
files under the same ``/vimages`` / ``/vassets`` URLs the Taipy app uses.

Environment: ``MIXING_LAB_ADMIN_USER`` / ``MIXING_LAB_ADMIN_PW`` (admin login),
``MIXING_LAB_API_SECRET`` (token signing), ``MIXING_LAB_CORS_ORIGINS``
(comma-separated origins allowed to call the API from a browser).
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api import security
from api.routers import calculations, databases, outputs
from core import auth, media
from core import schemas as s
from core.version import APP_VERSION, RELEASE_DATE
from utils.usage import log_access

API_PREFIX = "/api/v1"
WEB_PREFIX = "/app"
WEB_DIST = media.BASE_DIR / "web" / "dist"
CORS_ENV = "MIXING_LAB_CORS_ORIGINS"
STATIC_MAX_AGE_S = 86400

log = logging.getLogger("mixing_lab.api")

meta = APIRouter(tags=["Meta"])
auth_router = APIRouter(prefix="/auth", tags=["Auth"])


@meta.get("/health", summary="Liveness check")
def health() -> dict[str, str]:
    return {"status": "ok"}


@meta.get("/version", summary="App version")
def version() -> dict[str, str]:
    return {"version": APP_VERSION, "release_date": RELEASE_DATE, "api": API_PREFIX}


@auth_router.post("/login", summary="Exchange admin credentials for a bearer token")
def login(req: s.LoginRequest) -> s.TokenResult:
    if not auth.admin_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, auth.NOT_CONFIGURED_MSG)
    principal = auth.login(req.username, req.password)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin credentials.",
                            headers={"WWW-Authenticate": "Bearer"})
    return s.TokenResult(access_token=security.issue_token(principal),
                         expires_in_s=security.TOKEN_TTL_S)


def _error(code: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=code)


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LookupError)
    async def _not_found(_request: Request, exc: LookupError):
        return _error(status.HTTP_404_NOT_FOUND, str(exc).strip("'\""))

    @app.exception_handler(PermissionError)
    async def _forbidden(_request: Request, exc: PermissionError):
        return _error(status.HTTP_403_FORBIDDEN, str(exc))

    @app.exception_handler(ValueError)
    async def _unprocessable(_request: Request, exc: ValueError):
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    @app.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error.")


def _install_middleware(app: FastAPI) -> None:
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    origins = [o.strip() for o in os.environ.get(CORS_ENV, "").split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                           allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def _cache_and_usage(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith((media.IMAGES_URL_PREFIX + "/", media.ASSETS_URL_PREFIX + "/")):
            if response.status_code == 200:
                response.headers["Cache-Control"] = f"public, max-age={STATIC_MAX_AGE_S}"
        elif (path.startswith(API_PREFIX) and not path.endswith(("/health", "/version"))
              or path == WEB_PREFIX or (path.startswith(WEB_PREFIX + "/")
                                        and not path.startswith(WEB_PREFIX + "/assets/"))):
            xff = request.headers.get("X-Forwarded-For")
            ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client
                                                         else None)
            page = (f"api:{request.method} {path[len(API_PREFIX):]}" if path.startswith(API_PREFIX)
                    else f"app:{path[len(WEB_PREFIX):] or '/'}")
            log_access(client_ip=ip, forwarded_for=xff,
                       user_agent=request.headers.get("User-Agent"), page=page)
        return response


def _mount_web(app: FastAPI) -> None:
    """Serve the built React app (web/dist) at /app; unknown paths get index.html so
    client-side routes survive a reload."""
    app.mount(f"{WEB_PREFIX}/assets", StaticFiles(directory=WEB_DIST / "assets"), name="web-assets")
    index = WEB_DIST / "index.html"

    @app.get(WEB_PREFIX, include_in_schema=False)
    @app.get(WEB_PREFIX + "/{path:path}", include_in_schema=False)
    def web(path: str = "") -> FileResponse:
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    app = FastAPI(title="Mixing Lab API", version=APP_VERSION,
                  description="Mixing and reactor-engineering calculations, databases, reports "
                              "and charts for the Mixing Lab front end.",
                  openapi_url=f"{API_PREFIX}/openapi.json", docs_url=f"{API_PREFIX}/docs",
                  redoc_url=None)
    _install_error_handlers(app)
    _install_middleware(app)
    for router in [meta, auth_router, *databases.ROUTERS, *calculations.ROUTERS,
                   *outputs.ROUTERS]:
        app.include_router(router, prefix=API_PREFIX)
    app.mount(media.IMAGES_URL_PREFIX, StaticFiles(directory=media.IMAGES_ROOT), name="vimages")
    app.mount(media.ASSETS_URL_PREFIX, StaticFiles(directory=media.ASSETS_DIR), name="vassets")
    web_built = (WEB_DIST / "index.html").is_file()
    if web_built:
        _mount_web(app)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(f"{WEB_PREFIX}/" if web_built else f"{API_PREFIX}/docs")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(media.thumbnail(media.LOGO, 48), media_type="image/png")

    return app


app = create_app()
