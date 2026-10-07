import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, postForFile, unwrap, type Schemas } from "../api/client";
import type { Row } from "../api/tables";
import { Chart } from "../components/Chart";
import { NumberField, Segmented, SelectField, Switch } from "../components/Form";
import {
  InsightCard, InsightGrid, StatGrid, TableDetails, statsFromRows, stripIcon, toneOf, type Stat,
} from "../components/Insights";
import { MultiSelect } from "../components/MultiSelect";
import { NoticeBar, useNotice } from "../components/Notice";
import { Card, ErrorNote, MenuIcon, PageLink, PageTitle } from "../components/ui";
import { VesselViewer, type VesselMedia } from "../components/VesselViewer";
import { formatG } from "../format";
import { useDebounced } from "../hooks";
import {
  HYDRO_FEATURED, INITIAL, asOrder, autoTrxn, buildRequest, downloadBlob, heatBalanceTone, kineticModel, solveMessage,
  solveTiles, suspensionTone, transferTone, type Inputs, type PointRequest, type SolveResult,
} from "./assessment/model";

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

      <h3>Hydrodynamics</h3>
      <StatGrid stats={featured} />
      <StatGrid size="sm" stats={rest} />
      {md(t.applicability)}
      <TableDetails rows={t.hydro} csvName="vessel_assessment_hydrodynamics.csv" stale={stale} />

      {t.mass_transfer.length > 0 && (
        <>
          <h3>Mass-transfer capacity versus kinetic demand</h3>
          <p>
            The capacity ratio is a preliminary screen using <strong>kLa / (1/t<sub>rxn</sub>)</strong>. Confirm the
            result with solubility, phase composition, and concentration driving-force data.
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
          No heat of reaction set (ΔH = 0) — enter ΔH<sub>rxn</sub> in Section 3 to run the heat-balance check.
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

export function VesselAssessment() {
  const { notice, setNotice, run } = useNotice();
  const [inputs, setInputs] = useState<Inputs>(INITIAL);
  const set = (patch: Partial<Inputs>) => setInputs((i) => ({ ...i, ...patch }));
  const [corrSources, setCorrSources] = useState<OptionItem[]>([LITERATURE]);
  const [corrStatus, setCorrStatus] = useState("");
  const [rxnInfo, setRxnInfo] = useState<{ model: string; scheme: string } | null>(null);
  const [fluidLibrary, setFluidLibrary] = useState(true);
  const [fluidNote, setFluidNote] = useState("");

  const options = useQuery({
    queryKey: ["options"],
    queryFn: async () => unwrap(await api.GET("/api/v1/options")),
  });
  const parameters = useQuery({
    queryKey: ["assessment-parameters"],
    queryFn: async () => unwrap(await api.GET("/api/v1/assessment/parameters")),
    staleTime: Infinity,
  });
  const labelOf = useMemo(
    () => new Map((parameters.data ?? []).map((p) => [p.field, p.label])),
    [parameters.data],
  );
  const enums = options.data?.enums ?? {};
  const reactionList =
    (inputs.reactionSource === "classes" ? options.data?.reaction_classes : options.data?.reactions_measured) ?? [];

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
      corr: sources.some((s) => s.code === i.corr) ? i.corr : sources[0].code,
    }));
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
  const currentKey = "request" in built ? JSON.stringify(built.request) : null;
  const [last, setLast] = useState<{ key: string; request: PointRequest; reaction: string; tables: Tables } | null>(null);
  const stale = !!last && currentKey !== last.key;
  const corrLabel = (code: string) => corrSources.find((c) => c.code === code)?.label ?? code;

  const compute = useMutation({
    mutationFn: async (request: PointRequest) =>
      unwrap(await api.POST("/api/v1/assessment/tables", { body: request })),
  });

  function onCompute() {
    if ("error" in built) {
      setNotice({ kind: "error", text: built.error });
      return;
    }
    const request = built.request;
    void run(compute.mutateAsync(request), "Assessment computed.")
      .then((tables) => setLast({ key: JSON.stringify(request), request, reaction: inputs.reaction, tables }))
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
  const envSelected = envParams ?? (parameters.data ?? []).filter((p) => p.default).map((p) => p.field);
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
  const paramOptions = (parameters.data ?? []).map((p) => ({ code: p.field, label: p.label }));

  return (
    <>
      <PageTitle pageKey="Vessel_Assessment">Vessel Assessment</PageTitle>
      <p>{status}</p>
      {options.isError && <ErrorNote error={options.error} />}

      <Card title="1. Vessel & System">
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
            <div className="form-row">
              <NumberField label="Temperature (°C)" value={inputs.T} onChange={(T) => set({ T })} />
              <NumberField label="Pressure (atm)" value={inputs.P} onChange={(P) => set({ P })} />
              <NumberField label="Coolant temp (°C)" value={inputs.Tcool} onChange={(Tcool) => set({ Tcool })} />
            </div>
            <div className="form-row">
              <NumberField label="Agitation speed N (RPM)" value={inputs.N} onChange={(N) => set({ N })} />
              <NumberField label="Working volume (L)" value={inputs.V} onChange={(V) => set({ V })} />
            </div>
            <Switch label="Fed-batch" checked={inputs.fed} onChange={(fed) => set({ fed })} />
            {inputs.fed && (
              <>
                <p className="muted">
                  Feed inputs unlock the <strong>mesomixing</strong> assessment (feed-plume dispersion).
                </p>
                <div className="form-row">
                  <NumberField label="Feed rate (mL/min)" value={inputs.feedRate} onChange={(feedRate) => set({ feedRate })} />
                  <NumberField label="Feed pipe ID (mm)" value={inputs.feedDiam} onChange={(feedDiam) => set({ feedDiam })} />
                  <SelectField
                    label="Feed location"
                    value={inputs.feedLocation}
                    options={enums.FeedLocation ?? []}
                    onChange={(feedLocation) => set({ feedLocation })}
                  />
                </div>
              </>
            )}
            <details>
              <summary>Advanced: vessel geometry overrides</summary>
              <div className="form-row">
                <NumberField label="D_tank (m)" value={inputs.dTank} onChange={(dTank) => set({ dTank })} />
                <NumberField label="D_imp (m)" value={inputs.dImp} onChange={(dImp) => set({ dImp })} />
                <NumberField label="Np" value={inputs.Np} onChange={(Np) => set({ Np })} />
                <NumberField label="Nq" value={inputs.Nq} onChange={(Nq) => set({ Nq })} />
              </div>
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
            <div className="form-row two">
              <NumberField label="ρ (kg/m³)" value={inputs.rho} onChange={(rho) => set({ rho })} />
              <NumberField label="μ (Pa·s)" value={inputs.mu} onChange={(mu) => set({ mu })} />
              <NumberField label="D_mol (m²/s)" value={inputs.dmol} onChange={(dmol) => set({ dmol })} />
              <NumberField label="σ (N/m)" value={inputs.sigma} onChange={(sigma) => set({ sigma })} />
            </div>
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
                <div className="form-row two">
                  <NumberField label="ρ_p (kg/m³)" value={inputs.rhoP} onChange={(rhoP) => set({ rhoP })} />
                  <NumberField label="d50 (µm)" value={inputs.d50} onChange={(d50) => set({ d50 })} />
                  <NumberField label="Shape factor φ" value={inputs.phi} onChange={(phi) => set({ phi })} />
                  <NumberField label="Solids loading (wt-%)" value={inputs.xWt} onChange={(xWt) => set({ xWt })} />
                </div>
                <div className="form-row three">
                  <NumberField label="Zwietering S" value={inputs.szw} onChange={(szw) => set({ szw })} />
                  <NumberField label="GMB z" value={inputs.gmbZ} onChange={(gmbZ) => set({ gmbZ })} />
                  <NumberField label="C/D" value={inputs.cd} onChange={(cd) => set({ cd })} />
                </div>
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

      <Card title="3. Reaction">
        <div className="form-row">
          <SelectField
            label="Reaction source"
            value={inputs.reactionSource}
            options={[
              { code: "measured", label: "Measured kinetics" },
              { code: "classes", label: "Reaction classes" },
            ]}
            onChange={(v) => {
              const source = v as Inputs["reactionSource"];
              const list = (source === "classes" ? options.data?.reaction_classes : options.data?.reactions_measured) ?? [];
              set({ reactionSource: source });
              const next = list.includes(inputs.reaction) ? inputs.reaction : list[0];
              if (next) report(loadReaction(next, true));
            }}
          />
          <SelectField
            label="Reaction"
            value={inputs.reaction}
            options={reactionList}
            onChange={(v) => {
              report(loadReaction(v, true));
              setNotice({ kind: "info", text: "Reaction kinetics loaded." });
            }}
          />
        </div>
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
        <h4>Kinetics (editable)</h4>
        <div className="form-row">
          <NumberField label="Rate constant k" value={inputs.k} onChange={(k) => set({ k })} />
          <NumberField label="C0 (mol/L)" value={inputs.c0} onChange={(c0) => set({ c0 })} />
          <NumberField label="t_rxn (s, 0 = auto)" value={inputs.trxn} onChange={(trxn) => set({ trxn })} />
          <NumberField label="ΔH_rxn (kJ/mol)" value={inputs.dH} onChange={(dH) => set({ dH })} />
        </div>
      </Card>

      <Card title="4. Correlations">
        <p>
          Choose the correlation source used for the assessment. Only sources registered for the
          selected vessel are offered.
        </p>
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
        <p className="stale-note">
          ⚠️ Inputs changed since the last run — click <em>Compute Assessment</em> to refresh the results.
        </p>
      )}

      {t && last && (
        <>
          <Card title="Results">
            <AssessmentInsights t={t} solids={!!last.request.solids} stale={stale} />
          </Card>

          <Card title="Operating Envelope">
            <p>
              Each parameter is swept across the vessel's RPM range to form an <strong>operating region</strong>: the
              solid line is the boundary at maximum fill volume, the dotted line at minimum fill volume, and the
              shaded band is the reachable envelope between them. The red ★ marks the current operating point.
              Dashed lines on the Damköhler panels mark the 0.1 and 1.0 mixing-sensitivity thresholds.
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
            <p>
              Each parameter selected above is evaluated over the full <strong>agitation speed × fill volume</strong>{" "}
              window of the vessel as an interactive 3D surface (drag to rotate, scroll to zoom, hover for values).
              The red ◆ marks the current operating point; translucent planes on the Damköhler panels mark the 0.1
              and 1.0 mixing-sensitivity thresholds. Surfaces are generated on demand because the N × V grid is
              computationally heavier than the envelope sweep.
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
                ⚠️ Results or parameter selection changed since the surfaces were built — click{" "}
                <em>Generate 3D surfaces</em> to refresh.
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
              Generate a PDF capturing the system configuration, hydrodynamics, Damköhler mixing-sensitivity,
              optional solid-suspension / heat balance, and the operating envelope chart — or save the computed
              case to the <PageLink pageKey="Recorded_Results" /> page for bulk export and comparison.
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
          Find the agitation speed (or working volume) that gives a target value of a hydrodynamic or
          mass-transfer parameter in the selected vessel. The other variable is held at its Section 1 input;
          fluid, phase, reaction and correlation settings above are used. Speed is scanned from 0.25× the minimum
          to 2× the maximum rated speed; volume is scanned across the vessel fill range.
        </p>
        <div className="form-row">
          <SelectField
            label="Solve for"
            value={solveFor}
            options={[
              { code: "N_rpm", label: "Agitation speed N (RPM)" },
              { code: "V_L", label: "Working volume V (L)" },
            ]}
            onChange={(v) => setSolveFor(v as "N_rpm" | "V_L")}
          />
          <SelectField label="Target parameter" value={solveParam} options={paramOptions} onChange={setSolveParam} />
          <NumberField label="Target value" value={solveTarget} onChange={setSolveTarget} />
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
