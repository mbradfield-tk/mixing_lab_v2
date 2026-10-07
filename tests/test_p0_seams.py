"""P0 back-end seams: auth policy, repositories, catalog, new services and the import boundaries."""
import ast
import dataclasses
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import auth, catalog, fluids, repositories as repos  # noqa: E402
from core import schemas as s  # noqa: E402
from core import sensitivity_rules as rules  # noqa: E402
from core import services as sv  # noqa: E402
from core.heat_transfer import compute_batch  # noqa: E402

ADMIN = auth.Principal("ops", is_admin=True)
ANON = auth.ANONYMOUS
REACTOR = "TMA EasyMax-102"


# --- auth -------------------------------------------------------------------
def test_login_needs_env_and_matching_credentials(monkeypatch):
    monkeypatch.delenv(auth.ADMIN_USER_ENV, raising=False)
    monkeypatch.delenv(auth.ADMIN_PW_ENV, raising=False)
    assert auth.login("admin", "admin_tak_2026") is None
    monkeypatch.setenv(auth.ADMIN_USER_ENV, "ops")
    monkeypatch.setenv(auth.ADMIN_PW_ENV, "pw")
    assert auth.login("ops", "pw") == ADMIN
    assert auth.login("ops", "nope") is None


def test_write_policy_protects_shared_tables_only():
    for table in ("reactors", "reactions", "particles", "fluids"):
        with pytest.raises(PermissionError):
            auth.authorize(ANON, table)
        auth.authorize(ADMIN, table)
    auth.authorize(ANON, "recorded_results")


@pytest.mark.parametrize("module", ["pages.reaction_database", "pages.vessel_database",
                                    "pages.particle_database", "pages.fluid_database"])
def test_page_unlock_and_lock_handlers(monkeypatch, module):
    import importlib
    from types import SimpleNamespace

    page = importlib.import_module(module)
    monkeypatch.setattr(page, "notify", lambda *a, **k: None)
    monkeypatch.setenv(auth.ADMIN_USER_ENV, "ops")
    monkeypatch.setenv(auth.ADMIN_PW_ENV, "pw")
    state = SimpleNamespace(admin_user="ops", admin_pw="bad", admin_authenticated=False,
                            admin_status="")
    page.on_admin_unlock(state)
    assert not state.admin_authenticated and "Invalid" in state.admin_status
    state.admin_pw = "pw"
    page.on_admin_unlock(state)
    assert state.admin_authenticated and state.admin_pw == "" and "unlocked" in state.admin_status
    page.on_admin_lock(state)
    assert not state.admin_authenticated and state.admin_user == ""
    monkeypatch.delenv(auth.ADMIN_PW_ENV)
    state.admin_user, state.admin_pw = "ops", "pw"
    page.on_admin_unlock(state)
    assert not state.admin_authenticated and "disabled" in state.admin_status


# --- repositories (on temp copies of the CSVs) ------------------------------
def _temp(repo, tmp_path):
    path = tmp_path / repo.path.name
    if repo.path.exists():
        path.write_bytes(repo.path.read_bytes())
    return dataclasses.replace(repo, path=path)


def test_particle_create_validates_and_persists(tmp_path):
    repo = _temp(repos.particles, tmp_path)
    df = repo.load()
    good = {"particle_name": " Test bead ", "rho_p_kg_m3": 2500, "d10_um": 10, "d50_um": 50,
            "d90_um": 90}
    with pytest.raises(PermissionError):
        repo.create(df, good, ANON)
    out = repo.create(df, good, ADMIN)
    assert len(out) == len(df) + 1 and out.iloc[-1]["particle_name"] == "Test bead"
    assert len(repo.load()) == len(out)
    with pytest.raises(ValueError, match="already exists"):
        repo.create(out, good, ADMIN)
    with pytest.raises(ValueError, match="d10 ≤ d50 ≤ d90"):
        repo.create(out, {**good, "particle_name": "B", "d50_um": 5}, ADMIN)
    with pytest.raises(ValueError, match="Particle Density"):
        repo.create(out, {**good, "particle_name": "C", "rho_p_kg_m3": "abc"}, ADMIN)
    with pytest.raises(ValueError, match="Enter a particle name"):
        repo.create(out, {**good, "particle_name": "  "}, ADMIN)


def test_reaction_writes_need_admin_and_derive_t_rxn(tmp_path):
    repo = _temp(repos.reactions, tmp_path)
    df = repo.load()
    data = {"reaction_name": "Test rxn", "order": "2", "k_value": 0.5, "C0_mol_L": 2.0,
            "class": "yes"}
    with pytest.raises(PermissionError):
        repo.create(df, data, ANON)
    out = repo.create(df, data, ADMIN)
    row = out.iloc[-1]
    assert row["t_rxn_s"] == pytest.approx(1.0) and row["class"] == "yes"
    with pytest.raises(ValueError, match="rate constant k"):
        repo.create(out, {"reaction_name": "Zero", "order": "1"}, ADMIN)
    with pytest.raises(PermissionError):
        repo.delete(out, {"index": 0}, ANON)


def test_custom_fluid_cannot_shadow_a_library_solvent(tmp_path):
    repo = _temp(repos.fluids, tmp_path)
    with pytest.raises(ValueError, match="solvent library"):
        repo.create(repo.load(), {"fluid_name": "Water", "rho_kg_m3": 1000, "mu_Pa_s": 1e-3,
                                  "D_mol_m2_s": 1e-9, "surface_tension_N_m": 0.07}, ADMIN)


def test_reactor_add_blank_assigns_an_id(tmp_path):
    repo = _temp(repos.reactors, tmp_path)
    df = repo.load()
    out = repo.add_blank(df, ADMIN)
    assert len(out) == len(df) + 1
    assert str(out.iloc[-1]["reactor_id"]).startswith("RX-")
    assert list(out.columns) == list(df.columns)


def test_numeric_search_and_its_guidance():
    df = pd.DataFrame({"Name": ["a", "b", "c"], "V": ["1,000", "20", "5"]})
    hit, status = repos.particles.search(df, "10", ["V"], ">")
    assert list(hit["Name"]) == ["a", "b"] and status.startswith("2 of 3")
    _, status = repos.particles.search(df, "x", ["V"], ">")
    assert "Enter a number" in status
    _, status = repos.particles.search(df, "1", None, ">")
    assert "single field" in status


def test_results_append_and_clear(tmp_path):
    repo = _temp(repos.results, tmp_path)
    repo.path.write_text(",".join(repo.columns) + "\n")
    repo.append([{"reactor": "R1", "RPM": 300, "Re": "", "Assessment": "Potentially sensitive"}],
                ANON)
    df = repo.load()
    assert len(df) == 1 and repos.result_counts(df) == (0, 1, 0)
    assert list(df.columns) == repo.columns and df.at[0, "RPM"] == 300
    with pytest.raises(ValueError, match="^reactor: "):
        repo.append([{"reactor": ""}], ANON)
    with pytest.raises(ValueError):
        repo.append([{"reactor": "R2", "Unknown column": 1}], ANON)
    assert repo.clear(df, ANON).empty
    assert repo.path.read_text().strip() == ",".join(repo.columns)


# --- catalog / services -----------------------------------------------------
def test_catalog_lists_are_sorted_and_include_custom_fluids():
    names = catalog.fluid_names()
    assert names == sorted(set(names)) and "Water" in names
    assert set(catalog.custom_fluid_names()) <= set(names)
    assert REACTOR in catalog.reactor_names()


def test_heat_cool_service_matches_core_calculation():
    req = s.HeatCoolRequest(reactor=REACTOR, T_jacket_C=-10, T_target_C=5)
    res = sv.heat_cool(req)
    data, htm_db, _row, _ = sv.heat_cool_inputs(req)
    assert res.coefficients.U_W_m2K == pytest.approx(compute_batch(data, htm_db).u)
    assert sum(r.share_pct for r in res.resistances) == pytest.approx(100.0)
    assert res.resolved.wall_material and len(res.ua_vs_speed["N_rpm"]) == 40


def test_ua_surface_rejects_identical_axes():
    with pytest.raises(ValueError, match="two different"):
        s.UaSurfaceRequest(reactor=REACTOR, T_jacket_C=0, x_parameter="mu", y_parameter="mu")


def test_bourne_assess_uses_the_page_verdicts():
    kpi = [{"name": "Yield", "low": 80, "centre": 85, "high": 90}]
    flat = [{"name": "Yield", "low": 85, "centre": 85, "high": 85.1}]
    res = sv.bourne_assess(s.BourneAssessRequest(reactor=REACTOR, test1=kpi, test2=flat))
    assert [t.status for t in res.tests] == ["sensitive", "not_sensitive"]
    assert res.dominant == "Micromixing" and "MICROMIXING" in res.summary
    assert res.tests[1].verdict.endswith("(match P/V near the feed point).")


def test_bourne_plan_flags_clamped_fed_batch_speeds():
    res = sv.bourne_plan(s.BournePlanRequest(reactor=REACTOR, fed_batch_volumes_L=[0.08]))
    assert [r["Condition"].split()[0] for r in res.test1] == ["Low", "Centre", "High"]
    assert len(res.setpoints) == 2 and len(res.test2) == 3 and len(res.test3) == 3


def test_scale_up_service_matches_the_basis_value():
    res = sv.scale_up_match(s.ScaleUpRequest(
        comparison=s.ComparisonRequest(reactors=[REACTOR, "Cambrex R-101"]),
        basis_reactor=REACTOR, parameter="P_V_W_L", basis_N_rpm=300, basis_V_L=0.08))
    target = res.rows[1]
    assert target.role == "target" and target.status == "Matched"
    assert target.value == pytest.approx(res.target, rel=1e-3)


def test_blend_service_classifies_pairs_and_phases():
    res = sv.blend(s.BlendRequest(components=[
        s.BlendComponent(name="Water", amount=1), s.BlendComponent(name="Toluene", amount=1)]))
    assert res.status == "immiscible" and len(res.phases) == 2 and len(res.dispersion) == 1
    with pytest.raises(ValueError, match="No properties"):
        fluids.blend({"Nope": 1.0}, True, 25.0, pd.DataFrame(columns=["fluid_name"]))


def test_options_expose_codes_and_labels():
    o = sv.options()
    corr = {i.code: i.label for i in o.enums["CorrSource"]}
    assert "Literature" in corr and corr["Literature"]
    assert REACTOR in o.reactors


def test_bourne_summary_for_incomplete_protocol():
    o = rules.bourne_outcome("sensitive", "", "", 100.0)
    assert rules.bourne_summary_md(o).endswith("— and Test 3 if needed.")


# --- import boundaries ------------------------------------------------------
ENGINE = ("utils.calculations", "utils.rom_registry", "utils.solvent_properties")


def _imports(path: Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


@pytest.mark.parametrize("folder,banned", [
    ("pages", ENGINE + ("plotly", "matplotlib", "fastapi")),
    ("core", ("taipy", "plotly", "matplotlib", "pages", "viz", "reports", "api", "fastapi")),
    ("viz", ("taipy", "pages", "api", "fastapi")),
    ("reports", ("taipy", "pages", "api", "fastapi")),
    ("api", ("taipy", "pages")),
    ("utils", ("taipy", "plotly", "pages", "viz", "reports", "api", "fastapi")),
])
def test_layer_boundaries(folder, banned):
    bad = {f"{p.relative_to(ROOT)}: {m}" for p in (ROOT / folder).rglob("*.py")
           for m in _imports(p) if any(m == b or m.startswith(b + ".") for b in banned)}
    assert not bad, sorted(bad)


def test_no_default_admin_password_in_source():
    for path in list((ROOT / "pages").glob("*.py")) + list((ROOT / "core").glob("*.py")):
        assert "admin_tak_2026" not in path.read_text(), path.name
