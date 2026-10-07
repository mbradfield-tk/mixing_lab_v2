"""JSON contracts (Pydantic v2) for the core calculations — the future HTTP API boundary.

Requests carry plain data (names, numbers, codes); :mod:`core.services` resolves
them against the databases and calls the core functions. Field names are
snake_case with the unit as a suffix. Result floats are ``None`` when not finite.
"""
from __future__ import annotations

from typing import Literal

from pydantic import (
    AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator,
)

from core.options import (
    BourneStatus, CenterMode, Competing, CorrSource, DhAction, FeedBasis, FeedLocation, Kinetics,
    Mechanism, Phase,
)
from core.tables import friendly

Num = float | None
Row = dict[str, float | int | str | None]
Series = list[Num]
ReactionOrder = Literal["0", "1", "2", "pseudo-1", "pseudo-2"]
Kind = Literal["critical", "warning", "caution", "ok", "unknown"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", ser_json_inf_nan="null")


# ---------------------------------------------------------------------------
# Operating point
# ---------------------------------------------------------------------------
class FluidSpec(Contract):
    name: str = Field("Water", description="Library solvent or Fluid Database name")
    T_C: float = 25.0
    P_atm: float = Field(1.0, gt=0)
    rho_kg_m3: float | None = Field(None, gt=0, description="Overrides the looked-up density")
    mu_Pa_s: float | None = Field(None, gt=0, description="Overrides the looked-up viscosity")
    D_mol_m2_s: float | None = Field(None, gt=0, description="Overrides the looked-up diffusivity")


class ReactionSpec(Contract):
    order: ReactionOrder = "1"
    k: float = Field(0.0, ge=0, description="Rate constant; units follow the order "
                     "(1/s first order, L/(mol·s) second order)")
    C0_mol_L: float = Field(0.0, ge=0)
    t_rxn_s: float = Field(0.0, ge=0, description="Specified reaction time; 0 = derive from k and C0")
    dH_kJ_mol: float = Field(0.0, description="Reaction enthalpy (negative = exothermic)")


class GasSpec(Contract):
    present: bool = Field(False, description="A gas phase is part of the process (headspace or "
                          "sparged); adds the gas-liquid rows to the assessment tables")
    v_s_m_s: float = Field(0.0, ge=0, description="Superficial gas velocity (0 = surface aeration only)")
    coalescing: bool = True


class SolidsSpec(Contract):
    rho_p_kg_m3: float = Field(gt=0)
    d50_um: float = Field(gt=0)
    sphericity: float = Field(1.0, gt=0, le=1)
    loading_g_per_100g: float = Field(5.0, ge=0, description="g solid per 100 g liquid (Zwietering X)")
    zwietering_S: float = Field(5.5, gt=0)
    gmb_z: float = Field(3.0, gt=0)
    clearance_ratio: float = Field(0.33, gt=0, description="Impeller clearance / tank diameter (C/D)")


class FeedSpec(Contract):
    location: FeedLocation = FeedLocation.BULK
    d_pipe_mm: float = Field(3.0, gt=0)


class HeatSpec(Contract):
    T_process_C: float
    T_coolant_C: float


class GeometryOverrides(Contract):
    D_tank_m: float | None = Field(None, gt=0)
    D_imp_m: float | None = Field(None, gt=0)
    Np: float | None = Field(None, gt=0, description="Power number")
    Nq: float | None = Field(None, gt=0, description="Pumping number")


class PointRequest(Contract):
    reactor: str = Field(min_length=1, description="Vessel Database reactor_name")
    N_rpm: float = Field(gt=0)
    V_L: float = Field(gt=0)
    corr_source: CorrSource = CorrSource.LITERATURE
    fluid: FluidSpec = Field(default_factory=FluidSpec)
    reaction: ReactionSpec = Field(default_factory=ReactionSpec)
    gas: GasSpec = Field(default_factory=GasSpec)
    solids: SolidsSpec | None = None
    feed: FeedSpec | None = None
    heat: HeatSpec | None = None
    geometry: GeometryOverrides = Field(default_factory=GeometryOverrides)


def _hydro(alias: str, description: str = "", default=...):
    return Field(default, validation_alias=AliasChoices(alias), description=description or alias)


class PointResult(Contract):
    """Hydrodynamics, Damköhler numbers and (when requested) solids, mesomixing and heat balance."""
    model_config = ConfigDict(extra="forbid", ser_json_inf_nan="null", populate_by_name=True)

    Re: Num = _hydro("Re", "Impeller Reynolds number (–)")
    Np: Num = _hydro("Np", "Power number (–)")
    Nq: Num = _hydro("Nq", "Pumping number (–)", None)
    power_W: Num = _hydro("Power (W)")
    torque_N_m: Num = _hydro("Torque (N·m)")
    torque_per_volume_N_m_m3: Num = _hydro("Torque/V (N·m/m³)")
    P_V_W_m3: Num = _hydro("P/V (W/m³)")
    P_V_W_L: Num = _hydro("P/V (W/L)")
    P_V_W_kg: Num = _hydro("P/V (W/kg)")
    tip_speed_m_s: Num = _hydro("Tip speed (m/s)")
    froude: Num = _hydro("Froude number", "Froude number (–)")
    pumping_rate_m3_s: Num = _hydro("Pumping rate (m³/s)")
    circulation_time_s: Num = _hydro("Circulation time (s)")
    blend_time_95_s: Num = _hydro("Blend time 95% (s)")
    t_E_s: Num = _hydro("Micromix time t_E (s)", "Engulfment micromixing time, bulk ε (s)")
    t_E_local_s: Num = _hydro("Micromix time t_E_local (s)", "Engulfment time at ε_max (s)")
    eps_max_W_kg: Num = _hydro("ε_max (W/kg)")
    kolmogorov_um: Num = _hydro("Kolmogorov η (µm)")
    nu_m2_s: Num = _hydro("ν (m²/s)")
    avg_shear_rate_1_s: Num = _hydro("Avg shear rate (1/s)")
    max_shear_rate_1_s: Num = _hydro("Max shear rate (1/s)")
    avg_shear_stress_Pa: Num = _hydro("Avg shear stress (Pa)")
    edcf_W_kg_s: Num = _hydro("EDCF (W/kg/s)")
    volume_L: Num = _hydro("Volume (L)")
    kLa_1_s: Num = _hydro("kLa (1/s)")
    kLa_surface_1_s: Num = _hydro("kLa_surface (1/s)")
    Da_macro: Num = _hydro("Da_macro", "Blend time / t_rxn (–)")
    Da_micro: Num = _hydro("Da_micro", "Engulfment time / t_rxn (–)")
    Da_GL: Num = _hydro("Da_GL", "Gas–liquid: (1/kLa) / t_rxn (–)")
    Da_SL: Num = _hydro("Da_SL", "Solid–liquid: (1/kLa_SL) / t_rxn (–)")
    assessment: str = _hydro("Assessment", "Text summary of the Damköhler regimes")
    N_js_rpm: Num = _hydro("N_js (RPM)", "Just-suspended speed, max(Zwietering, GMB)", None)
    N_over_N_js: Num = _hydro("N/N_js", "", None)
    v_t_m_s: Num = _hydro("v_t (m/s)", "Particle settling velocity", None)
    Re_p: Num = _hydro("Re_p", "Particle Reynolds number (–)", None)
    k_SL_m_s: Num = _hydro("k_SL (m/s)", "", None)
    kLa_SL_1_s: Num = _hydro("kLa_SL (1/s)", "", None)
    Da_meso: Num = _hydro("Da_meso", "Feed mesomixing time / t_rxn (–)", None)
    Q_gen_W: Num = _hydro("Q_gen (W)", "", None)
    Q_cool_W: Num = _hydro("Q_cool (W)", "", None)
    U_W_m2K: Num = _hydro("U (W/m²·K)", "", None)
    A_ht_m2: Num = _hydro("A_ht (m²)", "", None)
    Q_gen_over_Q_cool_pct: Num = _hydro("Q_gen/Q_cool (%)", "None when Q_cool = 0", None)
    extra: dict[str, float | str | None] = Field(
        default_factory=dict, description="Correlation-specific values without a fixed field")


def core_key(field: str) -> str:
    """Core result-dict key (display label) of a :class:`PointResult` field."""
    return PointResult.model_fields[field].validation_alias.choices[0]


CORE_KEYS = {core_key(f): f for f in PointResult.model_fields if f != "extra"}
NUMERIC_FIELDS = [f for f in CORE_KEYS.values() if f != "assessment"]


class _NeedsParameters(Contract):
    @staticmethod
    def _check(names: list[str]) -> list[str]:
        bad = [p for p in names if p not in NUMERIC_FIELDS]
        if bad:
            raise ValueError(f"unknown parameter(s) {bad}; choose from PointResult numeric fields")
        return names


class SolveRequest(_NeedsParameters):
    point: PointRequest
    parameter: str = Field(description="PointResult field, e.g. 'P_V_W_L' or 'Da_micro'")
    target: float
    solve_for: Literal["N_rpm", "V_L"] = "N_rpm"

    @field_validator("parameter")
    @classmethod
    def _known(cls, v: str) -> str:
        return cls._check([v])[0]


class SolveRoot(Contract):
    value: float
    achieved: Num
    in_vessel_range: bool


class SolveResult(Contract):
    parameter: str
    target: float
    solve_for: Literal["N_rpm", "V_L"]
    status: Literal["solved", "outside_vessel_range", "unreachable"]
    best: Num = Field(description="First solution inside the vessel range")
    solutions: list[SolveRoot]
    search_range: tuple[float, float]
    vessel_range: tuple[float, float]
    achievable_span: tuple[Num, Num] | None = Field(
        description="Min/max of the parameter over the search range")


class SweepRequest(_NeedsParameters):
    point: PointRequest
    parameters: list[str] = Field(min_length=1)
    n_points: int = Field(40, ge=2, le=400)
    volumes_L: list[float] | None = Field(None, description="Default: vessel V_min and V_max")

    @field_validator("parameters")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        return cls._check(v)

    @field_validator("volumes_L")
    @classmethod
    def _positive(cls, v):
        if v is not None and (not v or any(x <= 0 for x in v)):
            raise ValueError("volumes_L must be a non-empty list of positive volumes")
        return v


class SweepCurve(Contract):
    V_L: float
    parameter: str
    values: list[Num]


class SweepResult(Contract):
    N_rpm: list[float]
    vessel_V_range_L: tuple[float, float]
    curves: list[SweepCurve]


class SurfaceRequest(_NeedsParameters):
    point: PointRequest
    parameters: list[str] = Field(min_length=1)
    n_points: int = Field(25, ge=2, le=100)
    v_points: int = Field(15, ge=2, le=100)

    @field_validator("parameters")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        return cls._check(v)


class SurfaceResult(Contract):
    N_rpm: list[float]
    V_L: list[float]
    z: dict[str, list[list[Num]]] = Field(description="parameter -> rows along V_L, columns along N_rpm")


class ParameterOption(Contract):
    field: str = Field(description="PointResult field name (send this)")
    label: str = Field(description="Display label")
    default: bool = Field(False, description="Plotted by default on the operating envelope")


class AssessmentTables(Contract):
    """The Vessel Assessment result tables, formatted as on the page and in the PDF."""
    point: PointResult
    t_rxn_s: float
    hydro: list[Row]
    damkohler: list[Row]
    mass_transfer: list[Row]
    solids: list[Row]
    heat: list[Row]
    assessment: str = Field(description="Markdown")
    applicability: str = Field(description="Markdown: correlation applicability checks")


class VesselDefaults(Contract):
    reactor: str
    D_tank_m: float
    D_imp_m: float
    N_rpm: float
    V_L: float
    Np: float
    Nq: float
    corr_sources: list["OptionItem"]
    corr_status: str


class FluidProperties(Contract):
    name: str = Field(description="Resolved name (library aliases mapped)")
    found: bool = Field(description="A library solvent or custom fluid (else water defaults)")
    library: bool = Field(description="Library solvent: properties depend on T and P")
    T_C: float
    P_atm: float
    rho_kg_m3: float
    mu_Pa_s: float
    D_mol_m2_s: float
    surface_tension_N_m: float
    in_range: bool
    note: str


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class ProjectInfo(Contract):
    project_name: str = ""
    step_number: str = ""
    unit_operation: str = ""
    process_version: str = ""


class AssessmentReportRequest(_NeedsParameters):
    point: PointRequest
    envelope_parameters: list[str] = Field(
        default_factory=lambda: ["Da_macro", "Da_micro", "P_V_W_L", "blend_time_95_s",
                                 "tip_speed_m_s", "Re"], min_length=1)
    reaction_name: str = ""

    @field_validator("envelope_parameters")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        return cls._check(v)


# ---------------------------------------------------------------------------
# Reaction Sensitivity Protocol
# ---------------------------------------------------------------------------
class BourneTestRow(Contract):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    test: str = Field(validation_alias=AliasChoices("test", "Test"))
    finding: str = Field(validation_alias=AliasChoices("finding", "Finding"))
    sensitive_kpis: str = Field("", validation_alias=AliasChoices("sensitive_kpis", "Sensitive KPI(s)"))


class ScreeningVessel(Contract):
    reactor: str = Field(min_length=1)
    N_rpm: float = Field(gt=0)
    V_L: float = Field(gt=0)
    solvent: str = Field("", description="Library solvent; water when blank or unknown")
    T_C: float = 25.0


class ProtocolRequest(Contract):
    reaction: ReactionSpec
    reaction_type: str = Field("", description="e.g. 'Nitration' — flags commonly hot chemistry")
    kinetics: Kinetics = Kinetics.AVAILABLE
    bourne: BourneStatus = BourneStatus.SKIP
    bourne_mechanism: Mechanism | None = None
    bourne_tests_done: list[Literal[1, 2, 3]] = Field(default_factory=list)
    bourne_results: list[BourneTestRow] = Field(default_factory=list)
    semi_batch: bool = False
    phases: list[Phase] = Field(default_factory=lambda: [Phase.LIQUID])
    competing: Competing | None = None
    dh_override_kJ_mol: float = Field(0.0, description="0 = use reaction.dH_kJ_mol")
    dh_override_measured: bool = False
    dh_action: DhAction | None = Field(
        None, description="How to proceed when no ΔH is known")
    dh_reference_kJ_mol: float = Field(0.0, description="ΔH of a similar reaction (dh_action='estimate')")
    c0_heat_mol_L: float = Field(1.0, ge=0, description="Concentration for the adiabatic rise")
    rho_cp_kJ_m3K: float = Field(1800.0, ge=0, description="Volumetric heat capacity ρ·Cp")
    screening_vessel: ScreeningVessel | None = Field(
        None, description="Vessel for the reactor-specific Da_macro / Da_micro screen")


class MessageOut(Contract):
    kind: Kind
    code: str
    text: str = Field(description="Inline Markdown (**bold** only)")


class FindingOut(Contract):
    area: str
    kind: Kind
    status: str
    detail: str
    code: str


class ActionOut(Contract):
    area: str
    action: str
    code: str


class KineticsOut(Contract):
    order: str
    rate_law: str
    t_rxn_s: Num = Field(description="Initial-rate characteristic time (used for Da)")
    t_90_s: Num = Field(description="Time to 90% conversion (information only)")
    basis: str


class HeatOut(Contract):
    has_enthalpy: bool
    resolved: bool
    dH_eff_kJ_mol: Num
    dT_ad_K: Num
    estimated: bool
    summary: str | None = Field(description="Thermal-severity narrative (plain text)")


class ScreeningDamkohler(Contract):
    reactor: str
    N_rpm: float
    V_L: float
    fluid: str
    t_blend_s: Num
    t_E_s: Num
    Re: Num
    P_V_W_L: Num
    Da_macro: Num
    Da_micro: Num


class ProtocolResult(Contract):
    ready: bool = Field(description="False until Steps 1–4 are answered; verdict is provisional")
    verdict: MessageOut
    steps: list[MessageOut | None] = Field(description="Steps 0–5 (Bourne, kinetics, phases, "
                                           "competing, heat, timescales)")
    findings: list[FindingOut]
    next_steps: list[ActionOut]
    kinetics: KineticsOut
    heat: HeatOut
    damkohler: ScreeningDamkohler | None
    bourne_sensitive: bool | None
    bourne_mechanisms: list[str]


class ProtocolReportRequest(Contract):
    protocol: ProtocolRequest
    reaction_name: str = ""
    project: ProjectInfo = Field(default_factory=ProjectInfo)


# ---------------------------------------------------------------------------
# Vessel Comparison
# ---------------------------------------------------------------------------
class ComparisonFeed(Contract):
    location: FeedLocation = FeedLocation.BULK
    pipe_id_mm: dict[str, float] = Field(
        default_factory=dict, description="Feed-pipe ID per vessel; missing/0 = Vessel Database "
        "value, else 3 mm")


class ComparisonRequest(Contract):
    reactors: list[str] = Field(min_length=1, description="Vessel Database reactor_names")
    fluid: FluidSpec = Field(default_factory=FluidSpec)
    reaction: ReactionSpec = Field(default_factory=ReactionSpec)
    reaction_name: str = ""
    corr_source: CorrSource = CorrSource.LITERATURE
    gas: GasSpec = Field(default_factory=GasSpec)
    solids: SolidsSpec | None = None
    feed: ComparisonFeed | None = None
    T_coolant_C: float = Field(15.0, description="Jacket coolant (heat balance when dH != 0)")
    scale_param: str = Field("", description="Scale-up matching parameter named in the report")
    scale_basis_reactor: str = ""


class ScaleUpRequest(_NeedsParameters):
    comparison: ComparisonRequest
    basis_reactor: str = Field(min_length=1)
    parameter: str = Field(description="PointResult field matched on every vessel, e.g. 'P_V_W_L'")
    basis_N_rpm: float = Field(gt=0)
    basis_V_L: float = Field(gt=0)
    solve_for: Literal["N_rpm", "V_L"] = "N_rpm"
    fixed: dict[str, float] = Field(
        default_factory=dict, description="Per target vessel: the fixed V_L (solve_for=N_rpm) or "
        "N_rpm (solve_for=V_L); default = middle of the vessel range")

    @field_validator("parameter")
    @classmethod
    def _known(cls, v: str) -> str:
        return cls._check([v])[0]


class ScaleUpRow(Contract):
    reactor: str
    role: Literal["basis", "target"]
    N_rpm: Num
    V_L: Num
    value: Num
    status: str
    hydro: Row = Field(description="Hydrodynamics at the point (PointResult field names)")


class ScaleUpResult(Contract):
    parameter: str
    target: Num
    rows: list[ScaleUpRow]


class ComparisonChartRequest(_NeedsParameters):
    comparison: ComparisonRequest
    parameters: list[str] = Field(default_factory=list,
                                  description="PointResult fields; default: the first available")

    @field_validator("parameters")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        return cls._check(v)


class ChartResult(Contract):
    figures: dict[str, dict] = Field(description="name -> Plotly figure JSON for react-plotly.js")
    captions: dict[str, str] = Field(default_factory=dict, description="Markdown captions")
    rows: dict[str, int] = Field(default_factory=dict, description="Subplot rows (sizing hint)")


class ComparisonResult(Contract):
    parameters: list[str] = Field(description="Result keys present for every vessel")
    corners: list[Row] = Field(description="Min/max RPM x min/max volume points per vessel")
    ranges: list[Row] = Field(description="Per-vessel min/max of each parameter")
    heat: list[Row] = Field(description="Heat balance at max RPM / max volume (dH != 0)")
    impact_ratios: list[Row]
    skipped: list[str] = Field(description="Vessels without usable geometry / speed data")


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
class UnitConversionRequest(Contract):
    property: str = Field(min_length=1, description="e.g. 'Pressure', 'Gas flow rate'")
    from_unit: str = Field(min_length=1)
    value: float
    gas_T_C: float = Field(25.0, description="Actual gas temperature (gas flow only)")
    gas_P_atm: float = Field(1.0, gt=0, description="Actual gas pressure (gas flow only)")


class UnitConversionResult(Contract):
    property: str
    from_unit: str
    value: float
    converted: dict[str, Num]


# ---------------------------------------------------------------------------
# Equations reference
# ---------------------------------------------------------------------------
class EquationItem(Contract):
    type: Literal["header", "latex", "md"]
    text: str | None = Field(None, description="header / md: Markdown with inline $LaTeX$")
    latex: str | None = Field(None, description="latex: a display equation")
    level: int | None = Field(None, description="header: 3 or 4")


class EquationSection(Contract):
    title: str
    items: list[EquationItem]


class EquationsResult(Contract):
    sections: list[EquationSection]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(Contract):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class TokenResult(Contract):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_s: int


# ---------------------------------------------------------------------------
# Fluids
# ---------------------------------------------------------------------------
class SolventStateRequest(Contract):
    name: str = Field(min_length=1, description="Library solvent")
    T_C: float = 25.0
    P_atm: float = Field(1.0, gt=0)


class BlendComponent(Contract):
    name: str = Field(min_length=1, description="Library solvent or custom fluid")
    amount: float = Field(ge=0)


class BlendRequest(Contract):
    components: list[BlendComponent] = Field(min_length=1)
    basis: Literal["volume", "mass"] = "volume"
    T_C: float = 25.0
    dispersion_speed_1_s: float = Field(5.0, ge=0)
    dispersion_D_imp_m: float = Field(0.05, ge=0)
    dispersion_H_m: float = Field(1.0, ge=0)
    interfacial_tension_N_m: float = Field(0.01, ge=0)


class BlendPair(Contract):
    label: str
    a: str
    b: str
    classification: Literal["miscible", "immiscible", "unknown", "reactive"]
    assessment: str
    Ra_MPa05: Num
    source: str


class BlendResult(Contract):
    status: Literal["single_phase", "unknown", "immiscible", "reactive"]
    components: list[Row]
    blend: Row
    pairs: list[BlendPair]
    phases: list[Row] | None = Field(description="Settled phases, densest first; None if a pair reacts")
    phases_unknown_split: bool
    dispersion: list[Row]


# ---------------------------------------------------------------------------
# Option lists
# ---------------------------------------------------------------------------
class OptionItem(Contract):
    code: str
    label: str


class OptionsResult(Contract):
    reactors: list[str]
    reactions_measured: list[str]
    reaction_classes: list[str]
    fluids: list[str]
    particles: list[str]
    enums: dict[str, list[OptionItem]] = Field(description="Coded choices from core.options")


VesselDefaults.model_rebuild()


# ---------------------------------------------------------------------------
# Vessel Comparison page
# ---------------------------------------------------------------------------
class FeedSchedule(Contract):
    basis_reactor: str = Field(min_length=1, description="Vessel whose feed volume is given")
    volume_mL: float = Field(100.0, ge=0)
    time_h: float = Field(1.0, gt=0)


class ScaleUpSpec(_NeedsParameters):
    basis_reactor: str = Field(min_length=1)
    parameter: str = Field(description="PointResult field held constant, e.g. 'P_V_W_L'")
    basis_N_rpm: float = Field(gt=0)
    basis_V_L: float = Field(gt=0)
    solve_for: Literal["N_rpm", "V_L"] = "N_rpm"
    fixed: dict[str, float] = Field(default_factory=dict,
                                    description="Per target vessel: fixed V_L or N_rpm")

    @field_validator("parameter")
    @classmethod
    def _known(cls, v: str) -> str:
        return cls._check([v])[0]


class ComparisonPageRequest(Contract):
    comparison: ComparisonRequest
    scale_up: ScaleUpSpec | None = None
    feed_schedule: FeedSchedule | None = Field(None, description="Fed-batch feed plan (needs comparison.feed)")


class ComparisonTables(Contract):
    """The Vessel Comparison result tables, formatted as on the page."""
    status: str
    feed_ok: bool = Field(description="False when a scaled feed would overflow a vessel")
    feed_warning: str
    parameters: list[ParameterOption] = Field(description="Plottable parameters for this comparison")
    summary: list[Row]
    detail: list[Row]
    rpm_ref: list[Row]
    heat: list[Row]
    scale: list[Row]
    scale_full: list[Row]
    scale_pct: list[Row]
    impact: list[Row]
    feed_plan: list[Row]
    skipped: list[str]


class ComparisonSetupRequest(Contract):
    reactors: list[str] = Field(min_length=1)
    basis_reactor: str = ""
    solve_for: Literal["N_rpm", "V_L"] = "N_rpm"


class ComparisonSetup(Contract):
    corr_sources: list[OptionItem] = Field(description="Sources registered for every vessel")
    corr_status: str
    feed_pipe_mm: dict[str, float] = Field(description="Recorded feed-pipe ID per vessel (0 = none)")
    basis_reactor: str
    basis_N_rpm: float
    basis_V_L: float
    fixed: dict[str, float] = Field(description="Default known value per target vessel")
    scalable: list[ParameterOption]


class KineticsDefaults(Contract):
    order: ReactionOrder
    k: float
    C0_mol_L: float
    t_rxn_s: float = Field(description="Specified time from the database (0 = derive from k)")
    T_C: float
    dH_kJ_mol: float
    fluid: str | None = Field(description="The reaction's solvent when it is a known fluid")


# ---------------------------------------------------------------------------
# Bourne Protocol
# ---------------------------------------------------------------------------
class KpiResponse(Contract):
    name: str = Field(min_length=1)
    unit: str = ""
    low: float = Field(description="Response at the low setting (low speed / slow feed / surface)")
    centre: float
    high: float = Field(description="Response at the high setting (high speed / fast feed / impeller)")
    std_dev: float | None = Field(None, ge=0, description="Replicate standard deviation")
    replicates: int | None = Field(None, ge=1)


class BournePlanRequest(Contract):
    reactor: str = Field(min_length=1)
    fluid: str = "Water"
    T_C: float = 25.0
    P_atm: float = Field(1.0, gt=0)
    V_L: float | None = Field(None, gt=0, description="Working volume; default mid fill range")
    D_imp_m: float | None = Field(None, gt=0)
    Np: float | None = Field(None, gt=0)
    centre: CenterMode = CenterMode.DEFAULT
    centre_pm_W_kg: float = Field(0.2, gt=0, description="Used when centre = custom_pm")
    centre_rpm: float | None = Field(None, gt=0, description="Used when centre = custom_rpm")
    fed_batch_volumes_L: list[float] = Field(
        default_factory=list, description="Fill volumes at which Test 1 speeds are re-set")
    feed_volume_mL: float = Field(100.0, gt=0)
    feed_basis: FeedBasis = FeedBasis.RATE
    feed_rate_mL_min: float = Field(5.0, gt=0)
    feed_time_min: float = Field(20.0, gt=0)
    surface_ratio: float = Field(0.1, gt=0, description="ε_loc/ε_avg at the surface feed")
    mid_ratio: float = Field(1.0, gt=0)
    impeller_ratio: float = Field(3.0, gt=0)


class SpeedSetpoint(Contract):
    step: str
    V_L: float
    low_rpm: float
    centre_rpm: float
    high_rpm: float
    clamped: list[str] = Field(description="Conditions clamped to the vessel speed range")


class BournePlanResult(Contract):
    centre_pm_W_kg: float
    centre_info: str = Field(description="Markdown caption of the centre-point choice")
    centerpoint: Row
    test1: list[Row] = Field(description="Low / centre / high P/m conditions after RPM clamping")
    test1_pm_span: float = Field(description="Achieved high/low P/m ratio (100 intended)")
    speed_plan: dict | None = Field(description="Iso-P/m speed lines over the fill range")
    setpoints: list[SpeedSetpoint]
    test2: list[Row]
    test3: list[Row]


class BourneAssessRequest(BournePlanRequest):
    test1: list[KpiResponse] = Field(min_length=1)
    test2: list[KpiResponse] | None = None
    test3: list[KpiResponse] | None = None


class BourneTestOut(Contract):
    test: Literal[1, 2, 3]
    status: Literal["sensitive", "not_sensitive", "inconclusive"]
    verdict: str = Field(description="Markdown")
    run_next_test: bool
    kpis: list[Row]


class BourneAssessResult(Contract):
    tests: list[BourneTestOut]
    dominant: str = Field(description="Mixing-insensitive | Micromixing | Mesomixing | "
                          "Macromixing | Inconclusive | Incomplete")
    tentative: bool
    next_test: int = Field(description="0 = none")
    summary: str = Field(description="Decision-tree conclusion (Markdown)")


class BourneReportRequest(BourneAssessRequest):
    project: ProjectInfo = Field(default_factory=ProjectInfo)


# ---------------------------------------------------------------------------
# Heat Transfer
# ---------------------------------------------------------------------------
class HeatTransferRequest(Contract):
    reactor: str = Field(min_length=1)
    fluid: str = "Water"
    N_rpm: float | None = Field(None, gt=0, description="Default: mid speed range")
    V_L: float | None = Field(None, gt=0, description="Default: mid fill range")
    D_tank_m: float | None = Field(None, gt=0)
    D_imp_m: float | None = Field(None, gt=0)
    Np: float | None = Field(None, gt=0)
    A_ht_m2: float | None = Field(None, gt=0, description="Default: wetted jacket area at V_L")
    T_start_C: float = 25.0
    T_jacket_C: float = Field(description="Jacket inlet temperature")
    htm: str | None = Field(None, description="Heat-transfer medium (data/HTM.csv); default first")
    nusselt_correlation: str | None = None
    v_jacket_m_s: float = Field(1.0, gt=0)
    d_hyd_jacket_m: float = Field(0.05, gt=0)
    m_dot_jacket_kg_s: float = Field(1.0, gt=0)
    wall_material: str | None = Field(None, description="Default: the vessel's shell material")
    wall_thickness_mm: float | None = Field(None, gt=0)
    lining_material: str | None = Field(None, description="'None' for unlined; default: vessel record")
    fouling_m2K_W: float = Field(0.0002, ge=0)
    include_agitator: bool = True
    mu_wall_Pa_s: float = Field(0.0, ge=0, description="0 = no wall-viscosity correction")
    time_unit: Literal["Seconds", "Minutes", "Hours"] = "Minutes"
    project: ProjectInfo = Field(default_factory=ProjectInfo)


class HeatCoolRequest(HeatTransferRequest):
    T_target_C: float
    q_rxn_W: float = Field(0.0, description="Constant heat release inside the batch")


class ReactionProfileRequest(HeatTransferRequest):
    reaction: ReactionSpec


SweepKey = Literal["n_rpm", "v_l", "d_imp", "d_tank", "rho", "mu", "cp", "k_fluid", "v_jacket",
                   "d_hyd_jacket", "wall_k", "wall_thickness_mm", "lining_k",
                   "lining_thickness_mm", "fouling", "mu_wall"]


class Coefficients(Contract):
    Re: Num
    Pr: Num
    Nu: Num
    h_i_W_m2K: Num = Field(description="Process-side film coefficient")
    h_o_W_m2K: Num = Field(description="Jacket-side film coefficient")
    U_W_m2K: Num
    A_ht_m2: Num
    UA_W_K: Num
    agitator_power_W: Num


class Resistance(Contract):
    name: str
    R_m2K_W: Num
    share_pct: Num


class HeatTransferResolved(Contract):
    """Inputs the service filled in from the vessel record and the page defaults."""
    N_rpm: float
    V_L: float
    D_tank_m: float
    D_imp_m: float
    A_ht_m2: float
    wall_material: str
    lining_material: str
    htm: str
    nusselt_correlation: str


class HeatCoolResult(Contract):
    resolved: HeatTransferResolved
    coefficients: Coefficients
    q_max_W: Num
    dT_dt_C_per_min: Num
    time_analytical_s: Num = Field(description="None when the target is never reached")
    time_constant_jacket_s: Num
    time_variable_jacket_s: Num
    constant_jacket: dict[str, Series] = Field(description="t_s, T_C, q_W")
    variable_jacket: dict[str, Series] = Field(description="t_s, T_C, q_W, T_jacket_out_C")
    correlations: list[Row]
    media: list[Row]
    summary: list[Row]
    resistances: list[Resistance]
    ua_vs_speed: dict[str, Series] = Field(description="N_rpm, UA_W_K (area fixed)")
    ua_vs_volume: dict[str, Series] = Field(description="V_L, UA_W_K (U fixed)")


class ReactionProfileResult(Contract):
    resolved: HeatTransferResolved
    coefficients: Coefficients
    profile: dict[str, Series] = Field(
        description="t_s, T_C, conversion, q_rxn_W (+ = release), q_jacket_W (+ = into batch)")
    T_peak_C: Num
    t_peak_s: Num
    T_adiabatic_C: Num
    t_complete_s: Num = Field(description="Time to 99% conversion; None when not reached")
    q_rxn_max_W: Num
    final_conversion: Num
    summary: list[Row]


class UaSurfaceRequest(HeatTransferRequest):
    x_parameter: SweepKey = "n_rpm"
    y_parameter: SweepKey = "v_l"
    x_range: tuple[float, float] | None = Field(None, description="Default: vessel range or ±50%")
    y_range: tuple[float, float] | None = None
    n_points: int = Field(30, ge=2, le=100)
    color_theme: Literal["Turbo", "Viridis", "Cool/Warm", "X-ray"] = "Turbo"

    @model_validator(mode="after")
    def _distinct(self):
        if self.x_parameter == self.y_parameter:
            raise ValueError("Choose two different parameters for the sweep.")
        for rng in (self.x_range, self.y_range):
            if rng is not None and not rng[1] > rng[0]:
                raise ValueError("Each sweep maximum must be greater than its minimum.")
        return self


class UaSurfaceResult(Contract):
    x_parameter: str
    y_parameter: str
    x: Series
    y: Series
    U_W_m2K: list[Series] = Field(description="Rows along y, columns along x")
    UA_W_K: list[Series]
    U_limits: tuple[Num, Num]
    UA_limits: tuple[Num, Num]


# ---------------------------------------------------------------------------
# Database records (field names = CSV columns)
# ---------------------------------------------------------------------------
class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class ParticleRecord(Record):
    particle_name: str = Field(min_length=1)
    rho_p_kg_m3: float = Field(gt=0)
    d10_um: float = Field(gt=0)
    d50_um: float = Field(gt=0)
    d90_um: float = Field(gt=0)
    shape_description: str = ""
    shape_factor: float = Field(1.0, gt=0)
    notes: str = ""

    @model_validator(mode="after")
    def _sizes_ordered(self):
        if not (self.d10_um <= self.d50_um <= self.d90_um):
            raise ValueError("Particle sizes must satisfy d10 ≤ d50 ≤ d90.")
        return self


class ReactionRecord(Record):
    reaction_name: str = Field(min_length=1)
    type: str = ""
    order: Literal["1", "2", "pseudo-1", "pseudo-2", "n/a"] = "1"
    k_value: float = 0.0
    k_units: str = ""
    C0_mol_L: float = 0.0
    t_rxn_s: float = Field(0.0, description="0 = derive from k (and C0 for 2nd order)")
    T_C: float = 25.0
    solvent: str = ""
    delta_H_kJ_mol: float = 0.0
    reaction_class: Literal["yes", "no"] = Field("no", alias="class")
    notes: str = ""
    reaction_scheme: str = ""

    @model_validator(mode="after")
    def _derive_t_rxn(self):
        k, c0 = self.k_value, self.C0_mol_L
        if self.t_rxn_s == 0 and k > 0:
            if self.order in ("1", "pseudo-1"):
                self.t_rxn_s = 1.0 / k
            elif self.order in ("2", "pseudo-2") and c0 > 0:
                self.t_rxn_s = 1.0 / (k * c0)
        if k <= 0 and self.t_rxn_s <= 0:
            raise ValueError("Enter a rate constant k (> 0) or a reaction time (> 0).")
        return self


class FluidRecord(Record):
    fluid_name: str = Field(min_length=1)
    rho_kg_m3: float = Field(gt=0)
    mu_Pa_s: float = Field(gt=0)
    D_mol_m2_s: float = Field(gt=0)
    surface_tension_N_m: float = Field(ge=0)
    notes: str = ""
    Cp_J_per_kgK: float = Field(4182.0, gt=0)
    k_W_per_mK: float = Field(0.607, gt=0)
    hsp_d: float = Field(0.0, ge=0)
    hsp_p: float = Field(0.0, ge=0)
    hsp_h: float = Field(0.0, ge=0)


class ReactorRecord(Record):
    """Core geometry of a vessel; any other reactors.csv column is accepted as-is."""
    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)
    reactor_name: str = Field(min_length=1)
    D_tank_m: float | None = Field(None, gt=0)
    D_imp_m: float | None = Field(None, gt=0)
    Np: float | None = Field(None, gt=0)
    N_rpm_min: float | None = Field(None, ge=0)
    N_rpm_max: float | None = Field(None, gt=0)
    V_L_min: float | None = Field(None, ge=0)
    V_L_max: float | None = Field(None, gt=0)


def _col(column: str, default=None):
    return Field(default, validation_alias=AliasChoices(column), serialization_alias=column)


class RecordedResult(Record):
    """One saved assessment (a row of recorded_results.csv; aliases are the CSV headers)."""
    reactor: str = Field(min_length=1)
    reaction: str = ""
    fluid: str = ""
    fluid_T_C: Num = None
    N_rpm: Num = _col("RPM")
    V_L: Num = _col("Volume (L)")
    Re: Num = None
    P_V_W_L: Num = _col("P/V (W/L)")
    tip_speed_m_s: Num = _col("Tip speed (m/s)")
    blend_time_s: Num = _col("Blend time (s)")
    circulation_time_s: Num = _col("Circulation time (s)")
    t_E_s: Num = _col("Micromix t_E (s)")
    t_E_local_s: Num = _col("Micromix t_E_local (s)")
    kolmogorov_um: Num = _col("Kolmogorov η (µm)")
    edcf_W_kg_s: Num = _col("EDCF (W/kg/s)")
    torque_N_m: Num = _col("Torque (N·m)")
    froude: Num = _col("Froude number")
    avg_shear_rate_1_s: Num = _col("Avg shear rate (1/s)")
    max_shear_rate_1_s: Num = _col("Max shear rate (1/s)")
    avg_shear_stress_Pa: Num = _col("Avg shear stress (Pa)")
    kLa_1_s: Num = _col("kLa (1/s)")
    kLa_surface_1_s: Num = _col("kLa_surface (1/s)")
    t_rxn_s: Num = _col("t_rxn (s)")
    Da_macro: Num = None
    Da_micro: Num = None
    Da_GL: Num = None
    Da_SL: Num = None
    assessment: str = _col("Assessment", "")

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, v, info):
        if v == "" and info.field_name not in ("reaction", "fluid", "assessment"):
            return None
        if isinstance(v, float) and v != v:  # NaN read back from the CSV
            return None
        return v


RESULT_COLUMNS = [RecordedResult.model_fields[f].serialization_alias or f
                  for f in RecordedResult.model_fields]


def validation_message(exc: ValidationError) -> str:
    """One readable line for the first validation error (field label + reason)."""
    err = exc.errors()[0]
    msg = str(err.get("msg", "invalid value")).removeprefix("Value error, ")
    loc = [str(p) for p in err.get("loc", ())]
    return f"{friendly(loc[0])}: {msg}" if loc else msg
