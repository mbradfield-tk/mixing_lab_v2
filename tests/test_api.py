"""HTTP API (FastAPI) tests: JSON over HTTP equals the service results (which
test_contracts ties to the page goldens), plus auth, uploads, errors and static files."""
import json
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi.testclient import TestClient

import api.main as api_main  # noqa: E402
from core import auth, repositories as repos  # noqa: E402
from core import schemas as s  # noqa: E402
from core import services as sv  # noqa: E402
from reports import charts  # noqa: E402

import test_contracts as contracts  # noqa: E402

V1 = "/api/v1"
REACTOR = "TMA EasyMax-102"


@pytest.fixture(autouse=True)
def _no_usage_log(monkeypatch):
    monkeypatch.setattr(api_main, "log_access", lambda **_kw: None)


@pytest.fixture
def client():
    return TestClient(api_main.create_app(), raise_server_exceptions=False)


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv(auth.ADMIN_USER_ENV, "ops")
    monkeypatch.setenv(auth.ADMIN_PW_ENV, "pw")


@pytest.fixture
def token(client, admin_env):
    res = client.post(f"{V1}/auth/login", json={"username": "ops", "password": "pw"})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def temp_tables(tmp_path, monkeypatch):
    """Point every repository at a temp copy of its CSV."""
    for repo in repos.REPOSITORIES.values():
        path = tmp_path / repo.path.name
        if repo.path.exists():
            path.write_bytes(repo.path.read_bytes())
        else:
            path.write_text(",".join(repo.columns) + "\n")
        monkeypatch.setattr(repo, "path", path)


def _json(model) -> dict:
    return json.loads(model.model_dump_json())


# --- parity with the services -----------------------------------------------
@pytest.mark.parametrize("full", [False, True])
def test_point_over_http_equals_service(client, full):
    req = contracts._va_request(full)
    res = client.post(f"{V1}/assessment/point", json=_json(req))
    assert res.status_code == 200
    assert res.json() == _json(sv.evaluate(req))


@pytest.mark.parametrize("path, req, service", [
    ("/heat-transfer/heat-cool", s.HeatCoolRequest(reactor=REACTOR, T_jacket_C=-10, T_target_C=5),
     sv.heat_cool),
    ("/bourne/plan", s.BournePlanRequest(reactor=REACTOR), sv.bourne_plan),
    ("/fluids/blend", s.BlendRequest(components=[s.BlendComponent(name="Water", amount=1),
                                                 s.BlendComponent(name="Toluene", amount=1)]),
     sv.blend),
    ("/comparison", s.ComparisonRequest(reactors=[REACTOR, "Cambrex R-101"]),
     sv.comparison_summary),
    ("/units/convert", s.UnitConversionRequest(property="Pressure", from_unit="bar", value=2),
     sv.convert_units),
])
def test_calculations_over_http_equal_services(client, path, req, service):
    res = client.post(V1 + path, json=_json(req))
    assert res.status_code == 200, res.text
    assert res.json() == _json(service(req))


def test_every_chart_kind_returns_plotly_json(client):
    payloads = {
        "assessment-envelope": {"point": _json(contracts._va_request())},
        "assessment-surfaces": {"point": _json(contracts._va_request()),
                                "envelope_parameters": ["P_V_W_L"]},
        "comparison-envelope": {"comparison": {"reactors": [REACTOR, "Cambrex R-101"]},
                                "parameters": ["P_V_W_L"]},
        "heat-cool": {"reactor": REACTOR, "T_jacket_C": -10, "T_target_C": 5},
        "reaction-profile": {"reactor": REACTOR, "T_jacket_C": 10,
                             "reaction": {"order": "2", "k": 0.5, "C0_mol_L": 1}},
        "ua-surface": {"reactor": REACTOR, "T_jacket_C": -10, "n_points": 5},
        "bourne-speed-plan": {"reactor": REACTOR},
        "solvent-properties": {"name": "Water", "T_C": 40},
        "blend-phases": {"components": [{"name": "Water", "amount": 1},
                                        {"name": "Toluene", "amount": 1}]},
    }
    assert set(payloads) == set(charts.CHARTS)
    for kind, payload in payloads.items():
        res = client.post(f"{V1}/charts/{kind}", json=payload)
        assert res.status_code == 200, (kind, res.text)
        figs = res.json()["figures"]
        assert figs and all("data" in f and "layout" in f for f in figs.values()), kind


def test_assessment_envelope_chart_matches_report_figure(client):
    from reports.service import assessment_envelope, figure_json

    req = s.AssessmentReportRequest(point=contracts._va_request())
    res = client.post(f"{V1}/charts/assessment-envelope", json=_json(req)).json()
    assert res["figures"]["envelope"] == figure_json(assessment_envelope(req)[0])


def test_report_endpoint_returns_a_pdf(client, monkeypatch):
    monkeypatch.setenv("MIXING_LAB_CHART_RENDERER", "matplotlib")
    res = client.post(f"{V1}/reports/heat-cool",
                      json={"reactor": REACTOR, "T_jacket_C": -10, "T_target_C": 5})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF") and "attachment" in res.headers["content-disposition"]
    assert client.post(f"{V1}/reports/nope", json={}).status_code == 404


# --- databases --------------------------------------------------------------
def test_reads_need_no_login(client):
    res = client.get(f"{V1}/vessels", params={"q": "100", "field": "V_L_max", "op": ">"})
    assert res.status_code == 200 and res.json()["status"].endswith("V_L_max > 100.")
    assert client.get(f"{V1}/vessels/{REACTOR}").json()["reactor_name"] == REACTOR
    assert client.get(f"{V1}/vessels/Nope").status_code == 404
    assert client.get(f"{V1}/fluids/custom/columns").status_code == 200
    assert client.get(f"{V1}/vessels/export").headers["content-type"].startswith("text/csv")


def test_login_and_protected_writes(client, temp_tables, token, admin_env):
    bead = {"particle_name": "API bead", "rho_p_kg_m3": 2500, "d10_um": 10, "d50_um": 50,
            "d90_um": 90}
    assert client.post(f"{V1}/particles", json=bead).status_code == 403
    res = client.post(f"{V1}/particles", json=bead, headers=token)
    assert res.status_code == 201 and res.json()["particle_name"] == "API bead"
    assert client.post(f"{V1}/particles", json=bead, headers=token).status_code == 422
    res = client.patch(f"{V1}/particles/API bead", json={"notes": "edited"}, headers=token)
    assert res.json()["notes"] == "edited"
    assert client.patch(f"{V1}/particles/API bead", json={"bogus": 1},
                        headers=token).status_code == 422
    assert client.delete(f"{V1}/particles/API bead", headers=token).status_code == 204
    assert client.get(f"{V1}/particles/API bead").status_code == 404
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.post(f"{V1}/particles", json=bead, headers=bad).status_code == 401


def test_login_failures(client, monkeypatch):
    monkeypatch.delenv(auth.ADMIN_USER_ENV, raising=False)
    monkeypatch.delenv(auth.ADMIN_PW_ENV, raising=False)
    body = {"username": "admin", "password": "admin_tak_2026"}
    assert client.post(f"{V1}/auth/login", json=body).status_code == 503
    monkeypatch.setenv(auth.ADMIN_USER_ENV, "ops")
    monkeypatch.setenv(auth.ADMIN_PW_ENV, "pw")
    assert client.post(f"{V1}/auth/login", json=body).status_code == 401


def test_results_are_open_to_the_local_user(client, temp_tables):
    row = {"reactor": REACTOR, "RPM": 300, "Assessment": "Potentially sensitive"}
    assert client.post(f"{V1}/results", json=[row]).status_code == 201
    res = client.get(f"{V1}/results", params={"reactor": [REACTOR]}).json()
    assert res["count"] == 1 and res["counts"]["potentially_sensitive"] == 1
    assert client.delete(f"{V1}/results").status_code == 204
    assert client.get(f"{V1}/results").json()["count"] == 0


def test_vessel_import_preview_and_apply(client, temp_tables, token):
    df = repos.reactors.load()
    csv = df.head(1).assign(owner="API test owner").to_csv(index=False).encode()
    files = {"file": ("v.csv", csv, "text/csv")}
    changes = client.post(f"{V1}/vessels/import/preview", files=files).json()
    owner = [c for c in changes if "API test owner" in json.dumps(c)]
    assert owner
    res = client.post(f"{V1}/vessels/import/apply", files=files,
                      data={"accept": json.dumps([owner[0]["id"]])}, headers=token)
    assert res.status_code == 200 and res.json()["applied"] == 1
    assert repos.reactors.load().iloc[0]["owner"] == "API test owner"


def test_upload_limits(client, temp_tables, token, monkeypatch):
    import api.routers.databases as dbr

    monkeypatch.setattr(dbr, "MAX_UPLOAD_BYTES", 10)
    files = {"file": ("p.csv", b"particle_name\n" + b"x" * 50, "text/csv")}
    assert client.put(f"{V1}/particles/import", files=files, headers=token).status_code == 413


# --- errors, media, static --------------------------------------------------
def test_unexpected_errors_hide_details(client, monkeypatch):
    def boom(_req):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(sv, "evaluate", boom)
    res = client.post(f"{V1}/assessment/point", json=_json(contracts._va_request()))
    assert res.status_code == 500 and "secret" not in res.text


def test_validation_and_lookup_errors(client):
    assert client.post(f"{V1}/assessment/point",
                       json={"reactor": REACTOR, "N_rpm": -1, "V_L": 1}).status_code == 422
    assert client.post(f"{V1}/assessment/point",
                       json={"reactor": "Nope", "N_rpm": 100, "V_L": 1}).status_code == 404
    assert client.post(f"{V1}/units/convert", json={"property": "Pressure", "from_unit": "x",
                                                    "value": 1}).status_code == 404


def test_vessel_media_schematic_and_static_files(client):
    media = client.get(f"{V1}/media/vessels/{REACTOR}").json()
    assert media["kind"] in ("3d", "image")
    static = client.get(media["url"])
    assert static.status_code == 200 and "max-age" in static.headers["cache-control"]
    png = client.get(f"{V1}/media/vessels/{REACTOR}/schematic.png", params={"fill_L": 0.1})
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    fill = client.get(f"{V1}/media/vessels/{REACTOR}/fill", params={"fill_L": 0.1}).json()
    assert fill["total_L"] > 0 and fill["level_mm"] is not None
    for path in ("/vimages/../data/reactors.csv", "/vimages/%2e%2e/data/reactors.csv",
                 "/vassets/../app.py"):
        assert client.get(path).status_code == 404


def test_reference_endpoints(client):
    assert client.get(f"{V1}/equations").status_code == 200
    assert "Pressure" in client.get(f"{V1}/units").json()["properties"]
    o = client.get(f"{V1}/options").json()
    assert REACTOR in o["reactors"] and o["enums"]["CorrSource"]
    assert client.get(f"{V1}/health").json() == {"status": "ok"}
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307 and root.headers["location"] == f"{V1}/docs"
    assert client.get("/favicon.ico").headers["content-type"] == "image/png"


# --- OpenAPI snapshot -------------------------------------------------------
def test_openapi_snapshot_is_current(client):
    """api/openapi.json is what the React types are generated from; regenerate with
    ``python scripts/export_openapi.py`` after changing a route or contract."""
    current = client.get(f"{V1}/openapi.json").json()
    committed = json.loads((ROOT / "api" / "openapi.json").read_text())
    assert current == committed, "OpenAPI changed: run python scripts/export_openapi.py"


def test_cors_is_off_unless_configured(monkeypatch):
    monkeypatch.delenv(api_main.CORS_ENV, raising=False)
    plain = TestClient(api_main.create_app())
    assert "access-control-allow-origin" not in plain.get(
        f"{V1}/health", headers={"Origin": "http://evil.example"}).headers
    monkeypatch.setenv(api_main.CORS_ENV, "http://localhost:5173")
    cors = TestClient(api_main.create_app())
    res = cors.get(f"{V1}/health", headers={"Origin": "http://localhost:5173"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
