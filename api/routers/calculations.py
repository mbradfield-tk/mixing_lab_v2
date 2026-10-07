"""Calculation routes: thin wrappers over :mod:`core.services` (request model in,
result model out; errors are mapped centrally in :mod:`api.main`)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from api import cache
from core import fluids, units
from core import schemas as s
from core import services as sv
from core.serialize import jsonable
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


@heat.post("/heat-cool", summary="Batch heat-up / cool-down")
def heat_cool(req: s.HeatCoolRequest) -> s.HeatCoolResult:
    return sv.heat_cool(req)


@heat.post("/reaction-profile", summary="Batch temperature driven by a reaction")
def reaction_profile(req: s.ReactionProfileRequest) -> s.ReactionProfileResult:
    return sv.reaction_profile(req)


@heat.post("/ua-surface", summary="U and UA over two swept inputs")
def ua_surface(req: s.UaSurfaceRequest) -> s.UaSurfaceResult:
    return cache.cached("ua-surface", req, lambda: sv.ua_surface(req))


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
