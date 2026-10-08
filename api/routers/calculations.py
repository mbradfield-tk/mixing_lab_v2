"""Calculation routes: thin wrappers over :mod:`core.services` (request model in,
result model out; errors are mapped centrally in :mod:`api.main`)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Query, Response, UploadFile

from api import cache
from api.routers.databases import read_upload
from core import fluids, units
from core import schemas as s
from core import services as sv
from core.serialize import jsonable
from reports import service as report_service
from reports.service import assessment_result, comparison_page

assessment = APIRouter(prefix="/assessment", tags=["Vessel Assessment"])
sensitivity = APIRouter(prefix="/sensitivity", tags=["Reaction Sensitivity"])
comparison = APIRouter(prefix="/comparison", tags=["Vessel Comparison"])
bourne = APIRouter(prefix="/bourne", tags=["Bourne Protocol"])
heat = APIRouter(prefix="/heat-transfer", tags=["Heat Transfer"])
fluid = APIRouter(prefix="/fluids", tags=["Fluids"])
unit = APIRouter(prefix="/units", tags=["Units"])
options = APIRouter(tags=["Options"])
kinetics = APIRouter(prefix="/kinetics", tags=["Kinetics"])


@assessment.post("/point", summary="Hydrodynamics + Damköhler numbers at one operating point")
def point(req: s.PointRequest) -> s.PointResult:
    return sv.evaluate(req)


@assessment.post("/solve", summary="N_rpm or V_L that gives a target parameter value")
def solve(req: s.SolveRequest) -> s.SolveResult:
    return sv.solve(req)


@assessment.post("/sweep", summary="Parameters vs N_rpm at fixed volumes")
def sweep(req: s.SweepRequest) -> s.SweepResult:
    return sv.sweep(req)


@assessment.post("/surface", summary="Parameters over the vessel's N x V window")
def surface(req: s.SurfaceRequest) -> s.SurfaceResult:
    return cache.cached("surface", req, lambda: sv.surface(req))


@assessment.post("/filling", summary="Operating point along a fed-batch fill (vs dosing time)")
def filling(req: s.FillingRequest) -> s.FillingResult:
    return cache.cached("filling", req, lambda: sv.filling(req))


@assessment.post("/temperature", summary="Batch temperature vs time (batch or dosed scenario)")
def temperature(req: s.TemperatureRequest) -> s.TemperatureResult:
    return cache.cached("temperature", req, lambda: sv.temperature(req))


@assessment.post("/tables", summary="Result tables for one point, formatted as on the page and PDF")
def tables(req: s.PointRequest) -> s.AssessmentTables:
    return assessment_result(req)


@assessment.get("/parameters", summary="Parameters for the envelope, surfaces and Solve-for")
def parameters() -> list[s.ParameterOption]:
    return sv.envelope_parameters()


@assessment.get("/vessel-defaults/{name:path}", summary="Inputs a vessel loads when selected")
def vessel_defaults(name: str) -> s.VesselDefaults:
    return sv.vessel_defaults(name)


@assessment.post("/save", status_code=201, summary="Save the point to Recorded Results")
def save(req: s.AssessmentReportRequest) -> dict[str, int]:
    return {"count": sv.save_assessment(req)}


@sensitivity.post("/assess", summary="Reaction Sensitivity Protocol verdict and findings")
def assess(req: s.ProtocolRequest) -> s.ProtocolResult:
    return sv.assess(req)


@sensitivity.post("/page", summary="Protocol results formatted as on the page (Markdown)")
def sensitivity_page(req: s.ProtocolRequest) -> s.ProtocolPage:
    return report_service.protocol_page(req)


@sensitivity.get("/options", summary="Reaction orders, ΔH reference reactions, unit operations")
def sensitivity_options() -> s.SensitivityOptions:
    return sv.sensitivity_options()


@sensitivity.get("/reaction-defaults", summary="Kinetics and solvent ρ·Cp of a reaction")
def sensitivity_reaction_defaults(
        reaction: str = Query(..., description="Reactions Database name (may contain '/')"),
        T_C: float | None = Query(None, description="ρ·Cp temperature; default the "
                                             "reaction's")) -> s.SensitivityReactionDefaults:
    return sv.sensitivity_reaction_defaults(reaction, T_C)


@sensitivity.post("/bourne-import", summary="Parse a Bourne Protocol results CSV")
async def sensitivity_bourne_import(file: UploadFile = File(...)) -> s.BourneImport:
    return sv.bourne_import(await read_upload(file))


@comparison.post("", summary="Operating envelopes of several vessels (tables)")
def compare(req: s.ComparisonRequest) -> s.ComparisonResult:
    return cache.cached("comparison", req, lambda: sv.comparison_summary(req))


@comparison.post("/scale-up", summary="Match a basis vessel's parameter on the other vessels")
def scale_up(req: s.ScaleUpRequest) -> s.ScaleUpResult:
    return cache.cached("scale-up", req, lambda: sv.scale_up_match(req))


@comparison.post("/setup", summary="Inputs the comparison page loads for a vessel selection")
def comparison_setup(req: s.ComparisonSetupRequest) -> s.ComparisonSetup:
    return sv.comparison_setup(req)


@comparison.post("/tables", summary="All comparison result tables, formatted as on the page")
def comparison_tables(req: s.ComparisonPageRequest) -> s.ComparisonTables:
    return cache.cached("comparison-tables", req, lambda: comparison_page(req))


@comparison.post("/save", status_code=201, summary="Save each vessel's max corner to Recorded Results")
def comparison_save(req: s.ComparisonRequest) -> dict[str, int]:
    saved, count = sv.save_comparison(req)
    return {"saved": saved, "count": count}


@kinetics.get("/defaults", summary="Database kinetics of a reaction (and its solvent)")
def kinetics_defaults(reaction: str) -> s.KineticsDefaults:
    return sv.kinetics_defaults(reaction)


@bourne.post("/plan", summary="Test 1-3 operating conditions")
def bourne_plan(req: s.BournePlanRequest) -> s.BournePlanResult:
    return sv.bourne_plan(req)


@bourne.post("/assess", summary="KPI verdicts and decision-tree outcome")
def bourne_assess(req: s.BourneAssessRequest) -> s.BourneAssessResult:
    return sv.bourne_assess(req)


@bourne.post("/plan/tables", summary="Test 1-3 conditions formatted as on the page")
def bourne_plan_tables(req: s.BournePlanRequest) -> s.BournePlanTables:
    return report_service.bourne_plan_tables(req)


@bourne.get("/options", summary="KPI column names, suggested metrics and units")
def bourne_options() -> s.BourneOptions:
    return sv.bourne_options()


@bourne.get("/defaults/{name}", summary="Working-volume and centre-RPM defaults for a vessel")
def bourne_defaults(name: str) -> s.BourneDefaults:
    return report_service.bourne_defaults(name)


@bourne.post("/sensitivity-csv", summary="Outcome CSV for the Reaction Sensitivity Protocol",
             responses={200: {"content": {"text/csv": {}}}})
def bourne_sensitivity_csv(req: s.BourneReportRequest) -> Response:
    f = report_service.bourne_sensitivity_csv(req)
    return Response(f.content, media_type=f.media_type,
                    headers={"Content-Disposition": f'attachment; filename="{f.filename}"'})


@heat.post("/heat-cool", summary="Batch heat-up / cool-down")
def heat_cool(req: s.HeatCoolRequest) -> s.HeatCoolResult:
    return sv.heat_cool(req)


@heat.post("/reaction-profile", summary="Batch temperature driven by a reaction")
def reaction_profile(req: s.ReactionProfileRequest) -> s.ReactionProfileResult:
    return sv.reaction_profile(req)


@heat.post("/ua-surface", summary="U and UA over two swept inputs")
def ua_surface(req: s.UaSurfaceRequest) -> s.UaSurfaceResult:
    return cache.cached("ua-surface", req, lambda: sv.ua_surface(req))


@heat.get("/options", summary="Media, correlations, materials and sweep parameters")
def heat_options() -> s.HeatTransferOptions:
    return sv.heat_transfer_options()


@heat.get("/defaults/{name:path}", summary="Inputs the Heat Transfer page loads for a vessel")
def heat_defaults(name: str) -> s.HeatTransferDefaults:
    return sv.heat_transfer_defaults(name)


@heat.get("/area", summary="Wetted jacket area at a fill volume")
def heat_area(reactor: str, D_tank_m: float = Query(gt=0), V_L: float = Query(gt=0)) -> dict[str, float]:
    return {"A_ht_m2": sv.jacket_area(reactor, D_tank_m, V_L)}


@fluid.get("/thermal", summary="rho, mu, Cp and k of a fluid at T (heat-transfer inputs)")
def fluid_thermal(name: str, T_C: float = 25.0) -> s.ThermalProperties:
    return sv.thermal_properties(name, T_C)


@fluid.get("/library", summary="Built-in solvent library at 25 °C / 1 atm")
def library() -> list[dict[str, Any]]:
    return jsonable(fluids.library_table())


@fluid.get("/properties", summary="Liquid properties of a solvent or custom fluid at T and P")
def fluid_properties(name: str, T_C: float = 25.0,
                     P_atm: float = Query(1.0, gt=0)) -> s.FluidProperties:
    return sv.fluid_properties(name, T_C, P_atm)


@fluid.post("/solvent-state", summary="Library solvent properties at T and P")
def solvent_state(req: s.SolventStateRequest) -> dict[str, Any]:
    return sv.solvent_state(req)


@fluid.post("/blend", summary="Blend properties, miscibility, phases and dispersion screen")
def blend(req: s.BlendRequest) -> s.BlendResult:
    return sv.blend(req)


@unit.get("", summary="Properties and their units")
def unit_table() -> dict[str, Any]:
    return {"properties": {p: units.units_for(p) for p in units.PROPERTIES},
            "gas_reference": units.GAS_REFERENCE}


@unit.post("/convert", summary="Convert a value to every unit of its property")
def convert(req: s.UnitConversionRequest) -> s.UnitConversionResult:
    return sv.convert_units(req)


@options.get("/options", summary="Dropdown lists and coded choices")
def option_lists() -> s.OptionsResult:
    return sv.options()


ROUTERS = [assessment, sensitivity, comparison, bourne, heat, fluid, unit, options, kinetics]
