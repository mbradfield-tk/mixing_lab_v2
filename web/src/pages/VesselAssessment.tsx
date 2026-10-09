import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, postForFile, unwrap, type Schemas } from "../api/client";
import type { Row } from "../api/tables";
import { Chart } from "../components/Chart";
import { NumberField, Segmented, SelectField, Switch } from "../components/Form";
import { Fader, InstrumentPanel, Knob, Selector, Setpoint } from "../components/Instrument";
import {
  InsightCard, InsightGrid, StatGrid, TableDetails, statsFromRows, stripIcon, toneOf, type Stat,
} from "../components/Insights";
import { MultiSelect } from "../components/MultiSelect";
import { NoticeBar, useNotice } from "../components/Notice";
import { PropertyTable } from "../components/PropertyTable";
import { Card, ErrorNote, MenuIcon, PageLink, PageTitle } from "../components/ui";
import { VesselViewer, type VesselMedia } from "../components/VesselViewer";
import { formatG } from "../format";
import { useDebounced } from "../hooks";
import {
  HYDRO_FEATURED, INITIAL, asOrder, autoTrxn, buildFilling, buildRequest, buildTemperature, defaultDose, downloadBlob,
  feedRateMlMin, fillingRows, fillingTiles, heatBalanceTone, isDamkohler, kineticModel, sliderStep, solveMessage,
  solveTiles, suspensionTone, temperatureTiles, transferTone, type FillingRequest, type FillingResult, type Inputs,
  type PointRequest, type SolveResult, type TemperatureRequest, type TemperatureResult,
} from "./assessment/model";

const FILLING_GROUPS: [string, string][] = [
  ["fluid", "Fill level & blended fluid properties"],
  ["hydrodynamics", "Hydrodynamics"],
  ["mass_transfer", "Mass transfer & suspension"],
  ["damkohler", "Damköhler numbers"],
  ["heat", "Heat transfer"],
];

type Figures = Schemas["ChartResult"]["figures"];
interface Filling {
  request: FillingRequest;
  result: FillingResult;
  figures: Figures;
  caption: string;
}
interface Temperature {
  request: TemperatureRequest;
  result: TemperatureResult;
  figures: Figures;
}

type Tables = Schemas["AssessmentTables"];
type OptionItem = Schemas["OptionItem"];

const DEFAULT_VESSEL = "TMA EasyMax-102";
const LITERATURE: OptionItem = { code: "Literature", label: "Empirical (literature)" };

const num = (v: unknown, fallback: number) => {
  const x = v === null || v === undefined || v === "" ? Number.NaN : Number(v);
  return Number.isFinite(x) ? x : fallback;
};

/** Parameter/Value/Units rows as tiles, colouring the row named ``statusRow`` with ``tone``. */
function toned(rows: Row[], statusRow: string, tone: (v: string) => Stat["tone"]): Stat[] {
  return statsFromRows(rows).map((s, i) =>
    rows[i].Parameter === statusRow ? { ...s, tone: tone(String(s.value)), wide: true } : s,
  );
}

function AssessmentInsights({ t, solids, stale }: { t: Tables; solids: boolean; stale: boolean }) {
  const hydro = statsFromRows(t.hydro);
  const featured = HYDRO_FEATURED.map((n) => hydro.find((s) => s.label === n)).filter((s): s is Stat => !!s);
  const rest = hydro.filter((s) => !featured.includes(s));
  return (
    <>
      <h3>Mixing sensitivity (Damköhler)</h3>
      {t.damkohler.length === 0 ? (
        <p className="muted">No reaction selected — Damköhler numbers do not apply (hydrodynamic assessment).</p>
      ) : (
        <>
          <InsightGrid>
            {t.damkohler.map((r, i) => {
              const regime = String(r.Regime ?? "");
              return (
                <InsightCard key={i} tone={toneOf(regime)} title={String(r.Type)} status={stripIcon(regime)}>
                  <div className="kpi-change">
                    {String(r["Damköhler"])} = {String(r.Value)}
                  </div>
                </InsightCard>
              );
            })}
          </InsightGrid>
          <TableDetails rows={t.damkohler} csvName="vessel_assessment_damkohler.csv" stale={stale} />
        </>
      )}

      <h3>Hydrodynamics</h3>
      <StatGrid stats={featured} />
      <StatGrid size="sm" stats={rest} />
      {t.applicability && (
        <details>
          <summary>Correlation applicability</summary>
          {md(t.applicability)}
        </details>
      )}
      <TableDetails rows={t.hydro} csvName="vessel_assessment_hydrodynamics.csv" stale={stale} />

      {t.mass_transfer.length > 0 && (
        <>
          <h3>Mass-transfer capacity vs reaction demand</h3>
          <p className="muted">
            Rough screen: kLa / (1/t<sub>rxn</sub>). Confirm with solubility and driving-force data.
          </p>
          <InsightGrid>
            {t.mass_transfer.map((r, i) => {
              const screening = String(r.Screening ?? "");
              return (
                <InsightCard key={i} tone={transferTone(screening)} title={String(r["Transfer path"])} status={screening}>
                  <div className="kpi-change">{String(r["Capacity / demand"])}×</div>
                  <div className="muted">
                    capacity / demand · kLa {String(r["kLa (1/s)"])} 1/s vs 1/t_rxn {String(r["Demand 1/t_rxn (1/s)"])} 1/s
                  </div>
                </InsightCard>
              );
            })}
          </InsightGrid>
          <TableDetails rows={t.mass_transfer} csvName="vessel_assessment_mass_transfer.csv" stale={stale} />
        </>
      )}

      {solids && (
        <>
          <h3>Solid suspension and dissolution</h3>
          <StatGrid size="sm" stats={toned(t.solids, "Suspension state", suspensionTone)} />
          <TableDetails rows={t.solids} csvName="vessel_assessment_solids.csv" stale={stale} />
        </>
      )}

      <h3>Heat balance</h3>
      {t.heat.length > 0 ? (
        <>
          <StatGrid size="sm" stats={toned(t.heat, "Balance", heatBalanceTone)} />
          <TableDetails rows={t.heat} csvName="vessel_assessment_heat_balance.csv" stale={stale} />
        </>
      ) : (
        <p className="muted">
          No heat load. Enter ΔH<sub>rxn</sub> (Section 4) or a dosing temperature different from the process temperature
          (Section 3).
        </p>
      )}
    </>
  );
}

function RateLaw({ order }: { order: string }) {
  const o = order.trim();
  return (
    <span className="rate-law">
      <i>r</i> = <i>k</i>{" "}
      {o === "1" || o === "pseudo-1" ? (
        <>
          <i>C</i>
          <sub>A</sub>
        </>
      ) : o === "2" || o === "pseudo-2" ? (
        <>
          <i>C</i>
          <sub>A</sub> <i>C</i>
          <sub>B</sub>
        </>
      ) : (
        <>
          <i>f</i>(<i>C</i>)
        </>
      )}
    </span>
  );
}

const md = (text: string) => <ReactMarkdown>{text}</ReactMarkdown>;

function TemperatureProfile({ temp, stale }: { temp: Temperature; stale: boolean }) {
  const r = temp.result;
  const reaction = r.Q_rxn_total_kJ !== 0;
  return (
    <Card title="Temperature Profile">
      {r.scenario === "dosed" ? (
        <p>
          <strong>Dosed</strong> over {formatG(r.time_min[r.time_min.length - 1], 3)} min
          {reaction ? ": heat is released as the co-reagent is dosed and reacts." : ", without reaction heat."} Includes the
          feed&apos;s sensible heat and the jacket duty, which grows as the vessel fills.
        </p>
      ) : (
        <p>
          <strong>Batch</strong>: all reagent reacts to 99% conversion against the jacket duty (as on the{" "}
          <PageLink pageKey="Heat_Transfer" /> page; no activation energy).
        </p>
      )}
      <p className="muted">
        <em>No-cooling end temperature</em>: the final temperature if the jacket removed no heat.
      </p>
      {stale && (
        <p className="stale-note">⚠️ Inputs changed since the simulation — click <em>Compute Assessment</em> to refresh.</p>
      )}
      <StatGrid size="sm" stats={temperatureTiles(r)} />
      <Chart figure={temp.figures.temperature} />
    </Card>
  );
}

function FillingDynamics({ filling, stale }: { filling: Filling; stale: boolean }) {
  const rows = fillingRows(filling.result);
  return (
    <Card title="Filling Dynamics">
      <p>
        Parameters at {filling.request.n_steps} steps as the vessel fills at constant speed (liquid = blend of the initial and
        dosed fluids).
      </p>
      {stale && (
        <p className="stale-note">⚠️ Inputs changed since the simulation — click <em>Compute Assessment</em> to refresh.</p>
      )}
      {md(filling.caption)}
      <StatGrid size="sm" stats={fillingTiles(filling.result)} />
      {FILLING_GROUPS.filter(([g]) => filling.figures[g]).map(([g, title]) => (
        <section key={g}>
          <h3>{title}</h3>
          <Chart figure={filling.figures[g]} />
        </section>
      ))}
      <TableDetails rows={rows} csvName="vessel_assessment_filling_dynamics.csv" stale={stale} summary="Show data table" />
    </Card>
  );
}

export function VesselAssessment() {
  const { notice, setNotice, run } = useNotice();
  const [inputs, setInputs] = useState<Inputs>(INITIAL);
  const set = (patch: Partial<Inputs>) => setInputs((i) => ({ ...i, ...patch }));
  const [corrSources, setCorrSources] = useState<OptionItem[]>([LITERATURE]);
  const [corrStatus, setCorrStatus] = useState("");
  const [rxnInfo, setRxnInfo] = useState<{ model: string; scheme: string } | null>(null);
  const [fluidLibrary, setFluidLibrary] = useState(true);
  const [fluidNote, setFluidNote] = useState("");
  const [ranges, setRanges] = useState<{ N: [number, number]; V: [number, number] } | null>(null);

  const options = useQuery({
    queryKey: ["options"],
    queryFn: async () => unwrap(await api.GET("/api/v1/options")),
  });
  const parameters = useQuery({
    queryKey: ["assessment-parameters"],
    queryFn: async () => unwrap(await api.GET("/api/v1/assessment/parameters")),
    staleTime: Infinity,
  });
  const htOptions = useQuery({
    queryKey: ["heat-transfer-options"],
    queryFn: async () => unwrap(await api.GET("/api/v1/heat-transfer/options")),
    staleTime: Infinity,
  });
  const htmList = Object.keys(htOptions.data?.media ?? {});
  useEffect(() => {
    if (htmList.length && !inputs.htm) set({ htm: htmList.includes("Water") ? "Water" : htmList[0] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [htOptions.data]);
  const labelOf = useMemo(
    () => new Map((parameters.data ?? []).map((p) => [p.field, p.label])),
    [parameters.data],
  );
  const enums = options.data?.enums ?? {};
  const rxnOn = inputs.reactionSource !== "none";
  const reactionList =
    (inputs.reactionSource === "classes"
      ? options.data?.reaction_classes
      : rxnOn
        ? options.data?.reactions_measured
        : []) ?? [];

  // --- loaders (each mirrors a Taipy on_change handler) -----------------------
  async function loadVessel(name: string) {
    const d = unwrap(await api.GET("/api/v1/assessment/vessel-defaults/{name}", { params: { path: { name } } }));
    const sources = d.corr_sources.length ? d.corr_sources : [LITERATURE];
    setInputs((i) => ({
      ...i,
      reactor: name,
      dTank: String(d.D_tank_m),
      dImp: String(d.D_imp_m),
      N: String(d.N_rpm),
      V: String(d.V_L),
      Np: String(d.Np),
      Nq: String(d.Nq),
      dosingAmount: String(defaultDose(d.V_L, d.V_L_range[1])),
      corr: sources.some((s) => s.code === i.corr) ? i.corr : sources[0].code,
    }));
    setRanges({ N: [d.N_rpm_range[0], d.N_rpm_range[1]], V: [d.V_L_range[0], d.V_L_range[1]] });
    setCorrSources(sources);
    setCorrStatus(d.corr_status);
  }

  async function fluidProps(name: string, T: string, P: string) {
    return unwrap(
      await api.GET("/api/v1/fluids/properties", {
        params: { query: { name, T_C: num(T, 25), P_atm: num(P, 1) } },
      }),
    );
  }

  function applyFluid(f: Schemas["FluidProperties"]) {
    set({
      fluid: f.name,
      rho: String(f.rho_kg_m3),
      mu: String(f.mu_Pa_s),
      dmol: String(f.D_mol_m2_s),
      sigma: String(f.surface_tension_N_m),
    });
    setFluidLibrary(f.library);
    setFluidNote(f.note);
  }

  async function loadFluid(name: string) {
    applyFluid(await fluidProps(name, inputs.T, inputs.P));
  }

  async function loadReaction(name: string, switchFluid: boolean) {
    if (!name) return;
    const r = unwrap(await api.GET("/api/v1/reactions/{name}", { params: { path: { name } } })) as Row;
    const order = asOrder(r.order);
    const k = num(r.k_value, num(inputs.k, 0.01));
    const c0 = num(r.C0_mol_L, num(inputs.c0, 0.1));
    const dH = num(r.delta_H_kJ_mol, 0);
    set({
      reaction: name,
      order,
      k: String(k),
      c0: String(c0),
      trxn: String(autoTrxn(order, k, c0, num(r.t_rxn_s, 0))),
      dH: String(dH),
    });
    setRxnInfo({
      model: kineticModel(String(r.order ?? "1"), k, String(r.k_units ?? ""), dH),
      scheme: String(r.reaction_scheme ?? ""),
    });
    const solvent = String(r.solvent ?? "").trim();
    if (switchFluid && solvent) {
      const f = await fluidProps(solvent, inputs.T, inputs.P);
      if (f.found) applyFluid(f);
    }
  }

  async function loadParticle(name: string) {
    if (!name) return;
    const p = unwrap(await api.GET("/api/v1/particles/{name}", { params: { path: { name } } })) as Row;
    setInputs((i) => ({
      ...i,
      particle: name,
      rhoP: String(num(p.rho_p_kg_m3, num(i.rhoP, 1500))),
      d50: String(num(p.d50_um, num(i.d50, 50))),
      phi: String(num(p.shape_factor, num(i.phi, 1))),
    }));
  }

  const report = (p: Promise<unknown>) => void p.catch((e: Error) => setNotice({ kind: "error", text: e.message }));

  // Initial selections once the option lists arrive.
  const initialised = useRef(false);
  useEffect(() => {
    const o = options.data;
    if (!o || initialised.current) return;
    initialised.current = true;
    const reactor = o.reactors.includes(DEFAULT_VESSEL) ? DEFAULT_VESSEL : (o.reactors[0] ?? "");
    const measured = o.reactions_measured.length ? o.reactions_measured : o.reaction_classes;
    report(loadVessel(reactor));
    report(loadReaction(measured[0] ?? "", false));
    report(loadParticle(o.particles[0] ?? ""));
    report(loadFluid(o.fluids.includes("Water") ? "Water" : (o.fluids[0] ?? "Water")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.data]);

  // T / P changes refresh library-solvent properties (custom fluids are fixed).
  const tp = useDebounced(`${inputs.T}|${inputs.P}`, 400);
  const firstTp = useRef(true);
  useEffect(() => {
    if (firstTp.current) {
      firstTp.current = false;
      return;
    }
    if (fluidLibrary && initialised.current) report(loadFluid(inputs.fluid));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tp]);

  const media = useQuery({
    queryKey: ["vessel-media", inputs.reactor],
    queryFn: async () => {
      const res = await api.GET("/api/v1/media/vessels/{name}", { params: { path: { name: inputs.reactor } } });
      if (res.response.status === 404) return null;
      return unwrap(res) as unknown as VesselMedia;
    },
    enabled: !!inputs.reactor,
  });

  // --- compute ------------------------------------------------------------
  const built = useMemo(() => buildRequest(inputs), [inputs]);
  const builtFilling = useMemo(
    () => ("request" in built ? buildFilling(inputs, built.request) : { filling: null }),
    [inputs, built],
  );
  const builtTemperature = useMemo(
    () => ("request" in built ? buildTemperature(inputs, built.request) : null),
    [inputs, built],
  );
  const currentKey =
    "request" in built && "filling" in builtFilling
      ? JSON.stringify({ point: built.request, filling: builtFilling.filling, temperature: builtTemperature })
      : null;
  const [last, setLast] = useState<{
    key: string;
    request: PointRequest;
    reaction: string;
    tables: Tables;
    filling: Filling | null;
    temperature: Temperature | null;
  } | null>(null);
  const stale = !!last && currentKey !== last.key;
  const corrLabel = (code: string) => corrSources.find((c) => c.code === code)?.label ?? code;

  const compute = useMutation({
    mutationFn: async ({
      request,
      filling,
      temperature,
    }: {
      request: PointRequest;
      filling: FillingRequest | null;
      temperature: TemperatureRequest | null;
    }) => {
      const [tables, sim, temp] = await Promise.all([
        api.POST("/api/v1/assessment/tables", { body: request }).then(unwrap),
        filling
          ? Promise.all([
              api.POST("/api/v1/assessment/filling", { body: filling }).then(unwrap),
              api
                .POST("/api/v1/charts/{kind}", { params: { path: { kind: "assessment-filling" } }, body: filling })
                .then(unwrap),
            ])
          : null,
        temperature
          ? Promise.all([
              api.POST("/api/v1/assessment/temperature", { body: temperature }).then(unwrap),
              api
                .POST("/api/v1/charts/{kind}", { params: { path: { kind: "assessment-temperature" } }, body: temperature })
                .then(unwrap),
            ])
          : null,
      ]);
      const sim2: Filling | null =
        filling && sim
          ? { request: filling, result: sim[0], figures: sim[1].figures, caption: sim[1].captions?.filling ?? "" }
          : null;
      const temp2: Temperature | null =
        temperature && temp ? { request: temperature, result: temp[0], figures: temp[1].figures } : null;
      return { tables, filling: sim2, temperature: temp2 };
    },
  });

  function onCompute() {
    if ("error" in built) {
      setNotice({ kind: "error", text: built.error });
      return;
    }
    if ("error" in builtFilling) {
      setNotice({ kind: "error", text: builtFilling.error });
      return;
    }
    const request = built.request;
    const filling = builtFilling.filling;
    const temperature = builtTemperature;
    void run(
      compute.mutateAsync({ request, filling, temperature }),
      filling ? "Assessment and filling simulation computed." : "Assessment computed.",
    )
      .then((res) =>
        setLast({
          key: JSON.stringify({ point: request, filling, temperature }),
          request,
          reaction: rxnOn ? inputs.reaction : "No reaction",
          tables: res.tables,
          filling: res.filling,
          temperature: res.temperature,
        }),
      )
      .catch(() => undefined);
  }

  const status = last
    ? `Computed at ${last.request.N_rpm.toFixed(0)} RPM, ${formatG(last.request.V_L, 3)} L (${corrLabel(
        last.request.corr_source ?? "Literature",
      )}) — Re = ${Math.round(last.tables.point.Re ?? 0).toLocaleString("en-US")}, P/V = ${formatG(
        last.tables.point.P_V_W_L ?? 0,
        3,
      )} W/L.`
    : "Set inputs and click Compute Assessment.";

  // --- envelope and surfaces ------------------------------------------------
  const [envParams, setEnvParams] = useState<string[] | null>(null);
  const envSelected = (envParams ?? (parameters.data ?? []).filter((p) => p.default).map((p) => p.field)).filter(
    (f) => rxnOn || !isDamkohler(f),
  );
  const envKey = envSelected.join("|");
  const envelope = useQuery({
    queryKey: ["chart", "assessment-envelope", last?.key, envKey],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/charts/{kind}", {
          params: { path: { kind: "assessment-envelope" } },
          body: { point: last!.request, envelope_parameters: envSelected },
        }),
      ),
    enabled: !!last && envSelected.length > 0,
    placeholderData: keepPreviousData,
  });

  const surfaces = useMutation({
    mutationFn: async (vars: { request: PointRequest; params: string[] }) =>
      unwrap(
        await api.POST("/api/v1/charts/{kind}", {
          params: { path: { kind: "assessment-surfaces" } },
          body: { point: vars.request, envelope_parameters: vars.params },
        }),
      ),
  });
  const [surfaceKey, setSurfaceKey] = useState<string | null>(null);
  const surfacesStale = !!surfaceKey && surfaceKey !== `${last?.key}#${envKey}`;

  function onSurfaces() {
    if (!last || stale) {
      setNotice({ kind: "error", text: "Compute the assessment before generating 3D surfaces." });
      return;
    }
    void run(surfaces.mutateAsync({ request: last.request, params: envSelected }), "3D response surfaces generated.")
      .then(() => setSurfaceKey(`${last.key}#${envKey}`))
      .catch(() => undefined);
  }

  // --- export & save --------------------------------------------------------
  const pdf = useMutation({
    mutationFn: () =>
      postForFile("/api/v1/reports/assessment", {
        point: last!.request,
        envelope_parameters: envSelected,
        reaction_name: last!.reaction,
      }),
  });
  const save = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/assessment/save", { body: { point: last!.request, reaction_name: last!.reaction } })),
  });

  // --- solve for -------------------------------------------------------------
  const [solveFor, setSolveFor] = useState<"N_rpm" | "V_L">("N_rpm");
  const [solveParam, setSolveParam] = useState("P_V_W_L");
  const [solveTarget, setSolveTarget] = useState("0.5");
  const [solved, setSolved] = useState<{
    res: SolveResult;
    text: string;
    kind: string;
    applied: boolean;
    fixed: { N_rpm: number; V_L: number };
  } | null>(null);
  const solve = useMutation({
    mutationFn: async (vars: { request: PointRequest; parameter: string; target: number; solve_for: "N_rpm" | "V_L" }) =>
      unwrap(
        await api.POST("/api/v1/assessment/solve", {
          body: { point: vars.request, parameter: vars.parameter, target: vars.target, solve_for: vars.solve_for },
        }),
      ),
  });

  function onSolve() {
    const target = Number(solveTarget);
    if (!Number.isFinite(target) || solveTarget.trim() === "") {
      setNotice({ kind: "error", text: "Choose a parameter and a numeric target value." });
      return;
    }
    if ("error" in built) {
      setNotice({ kind: "error", text: built.error });
      return;
    }
    const request = built.request;
    solve
      .mutateAsync({ request, parameter: solveParam, target, solve_for: solveFor })
      .then((res) => {
        const msg = solveMessage(res, labelOf.get(solveParam) ?? solveParam, {
          N_rpm: request.N_rpm,
          V_L: request.V_L,
          corrLabel: corrLabel(request.corr_source ?? "Literature"),
        });
        setSolved({ res, ...msg, applied: false, fixed: { N_rpm: request.N_rpm, V_L: request.V_L } });
        setNotice({
          kind: msg.kind,
          text:
            res.status === "solved"
              ? `Solved: ${solveFor === "N_rpm" ? "N" : "V"} = ${formatG(res.best as number, 4)} ${solveFor === "N_rpm" ? "RPM" : "L"}.`
              : res.status === "unreachable"
                ? "Target not reachable."
                : "Solution lies outside the vessel operating range.",
        });
      })
      .catch((e: Error) => setNotice({ kind: "error", text: `Solve failed: ${e.message}` }));
  }

  function applySolution() {
    if (!solved || solved.res.best === null || solved.res.best === undefined) return;
    const best = solved.res.best;
    if (solved.res.solve_for === "N_rpm") set({ N: String(Math.round(best * 10) / 10) });
    else set({ V: String(Math.round(best * 1e4) / 1e4) });
    setSolved({ ...solved, applied: true });
    setNotice({ kind: "info", text: "Solution applied to the operating inputs." });
  }

  const t = last?.tables;
  const paramOptions = (parameters.data ?? [])
    .filter((p) => rxnOn || !isDamkohler(p.field))
    .map((p) => ({ code: p.field, label: p.label }));

  return (
    <>
      <PageTitle pageKey="Vessel_Assessment">Vessel Assessment</PageTitle>
      <p>{status}</p>
      {options.isError && <ErrorNote error={options.error} />}

      <Card title="1. Vessel">
        <div className="grid-2 va-top">
          <div>
            <SelectField
              label="Vessel"
              value={inputs.reactor}
              options={options.data?.reactors ?? []}
              onChange={(v) => {
                report(loadVessel(v));
                setNotice({ kind: "info", text: "Vessel geometry loaded." });
              }}
            />
            <InstrumentPanel title="Operating point">
              {ranges ? (
                <>
                  <Knob
                    label="Stir speed"
                    value={inputs.N}
                    onChange={(N) => set({ N })}
                    min={ranges.N[0]}
                    max={ranges.N[1]}
                    step={sliderStep(ranges.N[1] - ranges.N[0])}
                    unit="RPM"
                  />
                  <Fader
                    label="Fill volume"
                    value={inputs.V}
                    onChange={(V) => set({ V })}
                    min={ranges.V[0]}
                    max={ranges.V[1]}
                    step={sliderStep(ranges.V[1] - ranges.V[0])}
                    unit="L"
                  />
                </>
              ) : (
                <>
                  <NumberField label="Agitation speed N (RPM)" value={inputs.N} onChange={(N) => set({ N })} />
                  <NumberField label="Fill volume (L)" value={inputs.V} onChange={(V) => set({ V })} />
                </>
              )}
              <Setpoint label="Temperature" value={inputs.T} onChange={(T) => set({ T })} unit="°C" />
              <Setpoint label="Pressure" value={inputs.P} onChange={(P) => set({ P })} unit="atm" step={0.1} min={0} />
              <Setpoint label="Coolant temp" value={inputs.Tcool} onChange={(Tcool) => set({ Tcool })} unit="°C" />
              <Selector
                label="Coolant"
                value={inputs.htm}
                options={[{ code: "", label: "Typical jacket" }, ...htmList.map((m) => ({ code: m, label: m }))]}
                onChange={(htm) => set({ htm })}
              />
            </InstrumentPanel>
            <details>
              <summary>Advanced: vessel geometry overrides</summary>
              <PropertyTable
                groups={[
                  {
                    title: "Geometry",
                    rows: [
                      { label: "Tank diameter D_tank", unit: "m", value: inputs.dTank, onChange: (dTank) => set({ dTank }) },
                      { label: "Impeller diameter D_imp", unit: "m", value: inputs.dImp, onChange: (dImp) => set({ dImp }) },
                      { label: "Power number Np", unit: "–", value: inputs.Np, onChange: (Np) => set({ Np }) },
                      { label: "Flow number Nq", unit: "–", value: inputs.Nq, onChange: (Nq) => set({ Nq }) },
                    ],
                  },
                ]}
              />
            </details>
          </div>
          <div className="media-box">
            {media.data ? (
              <VesselViewer media={media.data} name={inputs.reactor} />
            ) : media.isSuccess ? (
              <p className="muted placeholder">No image or 3D model available for this vessel.</p>
            ) : null}
          </div>
        </div>
      </Card>

      <Card title="2. Phases">
        <div className="phase-grid">
          <section className="phase-panel">
            <h3>
              <MenuIcon pageKey="Fluid_Database" /> Liquid / Solvent
            </h3>
            <SelectField
              label="Solvent / fluid"
              value={inputs.fluid}
              options={options.data?.fluids ?? []}
              onChange={(v) => {
                report(loadFluid(v));
                setNotice({ kind: "info", text: "Fluid properties loaded." });
              }}
            />
            <PropertyTable
              groups={[
                {
                  title: "Properties",
                  rows: [
                    { label: "Density ρ", unit: "kg/m³", value: inputs.rho, onChange: (rho) => set({ rho }) },
                    { label: "Viscosity μ", unit: "Pa·s", value: inputs.mu, onChange: (mu) => set({ mu }) },
                    { label: "Diffusivity D_mol", unit: "m²/s", value: inputs.dmol, onChange: (dmol) => set({ dmol }) },
                    { label: "Surface tension σ", unit: "N/m", value: inputs.sigma, onChange: (sigma) => set({ sigma }) },
                  ],
                },
              ]}
            />
            {fluidNote && <p className="muted">{fluidNote}</p>}
          </section>

          <section className="phase-panel">
            <h3>
              <MenuIcon pageKey="Particle_Database" /> Solid
            </h3>
            <Switch label="Include solid particles" checked={inputs.solids} onChange={(solids) => set({ solids })} />
            {inputs.solids ? (
              <>
                <SelectField
                  label="Particle"
                  value={inputs.particle}
                  options={options.data?.particles ?? []}
                  onChange={(v) => report(loadParticle(v))}
                />
                <PropertyTable
                  groups={[
                    {
                      title: "Particle",
                      rows: [
                        { label: "Density ρ_p", unit: "kg/m³", value: inputs.rhoP, onChange: (rhoP) => set({ rhoP }) },
                        { label: "Size d50", unit: "µm", value: inputs.d50, onChange: (d50) => set({ d50 }) },
                        { label: "Shape factor φ", unit: "–", value: inputs.phi, onChange: (phi) => set({ phi }) },
                        { label: "Solids loading", unit: "wt-%", value: inputs.xWt, onChange: (xWt) => set({ xWt }) },
                      ],
                    },
                    {
                      title: "Suspension constants",
                      rows: [
                        { label: "Zwietering S", unit: "–", value: inputs.szw, onChange: (szw) => set({ szw }) },
                        { label: "GMB z", unit: "–", value: inputs.gmbZ, onChange: (gmbZ) => set({ gmbZ }) },
                        { label: "Clearance C/D", unit: "–", value: inputs.cd, onChange: (cd) => set({ cd }) },
                      ],
                    },
                  ]}
                />
              </>
            ) : (
              <p className="muted">
                Enable to check off-bottom suspension (just-suspended speed) and solid–liquid mass transfer.
              </p>
            )}
          </section>

          <section className="phase-panel">
            <h3>🫧 Gas</h3>
            <Switch label="Include gas phase" checked={inputs.gas} onChange={(gas) => set({ gas })} />
            {inputs.gas ? (
              <>
                <Segmented
                  label="Mass-transfer mode"
                  value={inputs.gasTransfer}
                  options={enums.GasTransfer ?? []}
                  onChange={(gasTransfer) => set({ gasTransfer })}
                />
                {inputs.gasTransfer === "sparging" ? (
                  <>
                    <NumberField label="Superficial gas velocity v_s (m/s)" value={inputs.vs} onChange={(vs) => set({ vs })} />
                    <Segmented
                      label="Coalescence"
                      value={inputs.coalescing}
                      options={enums.Coalescence ?? []}
                      onChange={(coalescing) => set({ coalescing })}
                    />
                  </>
                ) : (
                  <p className="muted">Gas–liquid transfer through the free surface (surface kLa).</p>
                )}
              </>
            ) : (
              <p className="muted">
                Enable to include gas–liquid mass transfer (headspace or sparged) in the Damköhler screen.
              </p>
            )}
          </section>
        </div>
      </Card>

      <Card title="3. Dosing">
        <Switch label="Fed-batch" checked={inputs.fed} onChange={(fed) => set({ fed })} />
        {inputs.fed ? (
          <>
            <p className="muted">
              Adds the <strong>mesomixing</strong> check and the feed&apos;s sensible heat to the heat balance.
            </p>
            <div className="prop-narrow">
              <PropertyTable
                groups={[
                  {
                    title: "Feed",
                    rows: [
                      { label: "Dosed fluid", value: inputs.feedFluid, options: options.data?.fluids ?? [], onChange: (feedFluid) => set({ feedFluid }) },
                      { label: "Dosing time", unit: "h", value: inputs.dosingTime, onChange: (dosingTime) => set({ dosingTime }) },
                      { label: "Dosing amount", unit: "L", value: inputs.dosingAmount, onChange: (dosingAmount) => set({ dosingAmount }) },
                      {
                        label: "Feed rate (calculated)",
                        unit: "mL/min",
                        readOnly: true,
                        value: (() => {
                          const r = feedRateMlMin(inputs.dosingAmount, inputs.dosingTime);
                          return Number.isFinite(r) ? formatG(r, 4) : "—";
                        })(),
                      },
                      { label: "Dosing temperature", unit: "°C", value: inputs.feedT, onChange: (feedT) => set({ feedT }) },
                      { label: "Feed pipe ID", unit: "mm", value: inputs.feedDiam, onChange: (feedDiam) => set({ feedDiam }) },
                      {
                        label: "Feed location",
                        value: inputs.feedLocation,
                        options: enums.FeedLocation ?? [],
                        onChange: (feedLocation) => set({ feedLocation }),
                      },
                    ],
                  },
                ]}
              />
            </div>
            <Switch
              label="Simulate Filling"
              checked={inputs.simulateFilling}
              onChange={(simulateFilling) => set({ simulateFilling })}
            />
            {inputs.simulateFilling && (
              <p className="muted">
                Computes all parameters at 50 steps from {inputs.V || "?"} L to{" "}
                {(() => {
                  const end = Number(inputs.V) + Number(inputs.dosingAmount);
                  return Number.isFinite(end) ? formatG(end, 4) : "?";
                })()}{" "}
                L.
              </p>
            )}
          </>
        ) : (
          <p className="muted">Enable to define a fed (semi-batch) second fluid.</p>
        )}
      </Card>

      <Card title="4. Reaction">
        <div className="form-row">
          <SelectField
            label="Reaction source"
            value={inputs.reactionSource}
            options={[
              { code: "measured", label: "Measured kinetics" },
              { code: "classes", label: "Reaction classes" },
              { code: "none", label: "No reaction" },
            ]}
            onChange={(v) => {
              const source = v as Inputs["reactionSource"];
              set({ reactionSource: source });
              if (source === "none") return;
              const list = (source === "classes" ? options.data?.reaction_classes : options.data?.reactions_measured) ?? [];
              const next = list.includes(inputs.reaction) ? inputs.reaction : list[0];
              if (next) report(loadReaction(next, true));
            }}
          />
          {rxnOn && (
            <SelectField
              label="Reaction"
              value={inputs.reaction}
              options={reactionList}
              onChange={(v) => {
                report(loadReaction(v, true));
                setNotice({ kind: "info", text: "Reaction kinetics loaded." });
              }}
            />
          )}
        </div>
        {!rxnOn ? (
          <p className="muted">No reaction: hydrodynamics only (plus filling and heat with dosing). No Damköhler numbers.</p>
        ) : (
          <>
            {rxnInfo ? (
              <>
                <p>
                  <strong>{rxnInfo.model.split(" · ")[0]}</strong> · {rxnInfo.model.split(" · ").slice(1).join(" · ")}
                </p>
                <p>
                  <strong>Rate law:</strong> <RateLaw order={inputs.order} />
                </p>
                {rxnInfo.scheme && <p className="scheme-box">{rxnInfo.scheme}</p>}
              </>
            ) : (
              <p className="muted">No reaction selected.</p>
            )}
            <div className="prop-narrow">
              <PropertyTable
                groups={[
                  {
                    title: "Kinetics (editable)",
                    rows: [
                      { label: "Rate constant k", unit: "1/s or L/mol·s", value: inputs.k, onChange: (k) => set({ k }) },
                      { label: "Initial concentration C₀", unit: "mol/L", value: inputs.c0, onChange: (c0) => set({ c0 }) },
                      { label: "Reaction time t_rxn", unit: "s (0 = auto)", value: inputs.trxn, onChange: (trxn) => set({ trxn }) },
                      { label: "Heat of reaction ΔH", unit: "kJ/mol (− = exo)", value: inputs.dH, onChange: (dH) => set({ dH }) },
                    ],
                  },
                ]}
              />
            </div>
          </>
        )}
      </Card>

      <Card title="5. Correlations">
        <p>Only sources available for this vessel are listed.</p>
        <div className="form-row">
          <SelectField label="Correlation source" value={inputs.corr} options={corrSources} onChange={(corr) => set({ corr })} />
          <p className="muted">{corrStatus}</p>
        </div>
      </Card>

      <button
        type="button"
        className={`compute-btn ${!last || stale ? "primary" : "done"}`}
        disabled={compute.isPending}
        onClick={onCompute}
      >
        {compute.isPending ? "Computing…" : "Compute Assessment"}
      </button>
      {stale && (
        <p className="stale-note">⚠️ Inputs changed - click <em>Compute Assessment</em> to refresh.</p>
      )}

      {t && last && (
        <>
          <Card title="Results">
            <AssessmentInsights t={t} solids={!!last.request.solids} stale={stale} />
          </Card>

          {last.temperature && <TemperatureProfile temp={last.temperature} stale={stale} />}

          {last.filling && <FillingDynamics filling={last.filling} stale={stale} />}

          <Card title="Operating Envelope">
            <p className="muted">
              Each parameter across the vessel&apos;s speed range. Solid line: max fill; dotted: min fill; shaded: reachable
              region; red ★: current point; dashed (Da panels): 0.1 and 1 thresholds.
            </p>
            <MultiSelect
              label="Parameters to plot"
              options={paramOptions.map((p) => p.label)}
              value={envSelected.map((f) => labelOf.get(f) ?? f)}
              onChange={(labels) =>
                setEnvParams(paramOptions.filter((p) => labels.includes(p.label)).map((p) => p.code))
              }
              placeholder="Select parameters"
            />
            {envelope.isError && <ErrorNote error={envelope.error} />}
            {envelope.data?.captions?.envelope && md(envelope.data.captions.envelope)}
            <Chart figure={envelope.data?.figures.envelope} />
          </Card>

          <Card title="Response Surfaces (3D)">
            <p className="muted">
              The parameters above over the full speed × fill window (drag to rotate). Red ◆: current point; planes: Da 0.1 and 1
              thresholds, and the Re 10 / 10⁴ flow-regime transitions.
            </p>
            <button
              type="button"
              className={`compute-btn ${!surfaceKey || surfacesStale ? "primary" : "done"}`}
              disabled={surfaces.isPending}
              onClick={onSurfaces}
            >
              {surfaces.isPending ? "Generating…" : "Generate 3D surfaces"}
            </button>
            {surfacesStale && (
              <p className="stale-note">
                ⚠️ Results changed - click <em>Generate 3D surfaces</em> to refresh.
              </p>
            )}
            {surfaceKey && surfaces.data && (
              <>
                {md(surfaces.data.captions?.surfaces ?? "")}
                <Chart figure={surfaces.data.figures.surfaces} />
              </>
            )}
          </Card>

          <Card title="Export & Save">
            <p>
              Download a PDF of this assessment, or save it to <PageLink pageKey="Recorded_Results" />.
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="primary"
                disabled={stale || pdf.isPending}
                onClick={() =>
                  void run(pdf.mutateAsync(), "PDF report downloaded.")
                    .then(({ blob, filename }) => downloadBlob(blob, filename))
                    .catch(() => undefined)
                }
              >
                {pdf.isPending ? "Building PDF…" : "Download PDF report"}
              </button>
              <button
                type="button"
                disabled={stale || save.isPending}
                onClick={() =>
                  void run(save.mutateAsync(), "Saved 1 result — view it on the Recorded Results page.").catch(
                    () => undefined,
                  )
                }
              >
                Save results to Recorded Results
              </button>
            </div>
          </Card>
        </>
      )}

      <Card title="Solve for">
        <p>
          Find the speed (or fill volume) that gives a target value. The other variable stays at its Section 1 input.
        </p>
        <div className="prop-narrow">
          <PropertyTable
            groups={[
              {
                title: "Target",
                rows: [
                  {
                    label: "Solve for",
                    value: solveFor,
                    options: [
                      { code: "N_rpm", label: "Agitation speed N (RPM)" },
                      { code: "V_L", label: "Fill volume V (L)" },
                    ],
                    onChange: (v) => setSolveFor(v as "N_rpm" | "V_L"),
                  },
                  { label: "Target parameter", value: solveParam, options: paramOptions, onChange: setSolveParam },
                  { label: "Target value", value: solveTarget, onChange: setSolveTarget },
                ],
              },
            ]}
          />
        </div>
        <button type="button" className="compute-btn primary" disabled={solve.isPending} onClick={onSolve}>
          {solve.isPending ? "Solving…" : "Solve"}
        </button>
        {solved && (
          <>
            <StatGrid
              stats={solveTiles(solved.res, labelOf.get(solved.res.parameter) ?? solved.res.parameter, solved.fixed)}
            />
            <p className={`status status-${solved.kind}`}>
              <strong>{solved.text.split(":")[0]}:</strong>
              {solved.text.slice(solved.text.indexOf(":") + 1)}
            </p>
            {solved.res.solutions.length > 1 && (
              <table className="results">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Solved variable</th>
                    <th>Value</th>
                    <th>Achieved</th>
                    <th>Within vessel range</th>
                  </tr>
                </thead>
                <tbody>
                  {solved.res.solutions.map((s, i) => (
                    <tr key={i}>
                      <td>{i + 1}</td>
                      <td>{solved.res.solve_for === "N_rpm" ? "N (RPM)" : "V (L)"}</td>
                      <td className="num">{formatG(s.value, 4, true)}</td>
                      <td>
                        {labelOf.get(solved.res.parameter) ?? solved.res.parameter} ={" "}
                        {s.achieved === null ? "—" : formatG(s.achieved, 4)}
                      </td>
                      <td>{s.in_vessel_range ? "Yes" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {solved.res.status === "solved" && !solved.applied && (
              <button type="button" onClick={applySolution}>
                Apply solution to operating inputs
              </button>
            )}
          </>
        )}
      </Card>

      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
