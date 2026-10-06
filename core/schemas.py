"""JSON contracts (Pydantic v2) for the core calculations — the future HTTP API boundary.

Requests carry plain data (names, numbers, codes); :mod:`core.services` resolves
them against the databases and calls the core functions. Field names are
snake_case with the unit as a suffix. Result floats are ``None`` when not finite.
"""
from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from core.options import (
    BourneStatus, Competing, CorrSource, DhAction, FeedLocation, Kinetics, Mechanism, Phase,
)

Num = float | None
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
