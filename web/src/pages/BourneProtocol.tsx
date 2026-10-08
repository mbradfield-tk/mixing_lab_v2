import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, postForFile, unwrap, type Schemas } from "../api/client";
import { Chart } from "../components/Chart";
import { NumberField, Segmented, SelectField, SliderField, Switch } from "../components/Form";
import {
  InsightCard, InsightGrid, Pill, Stages, StatGrid, TableDetails, ThresholdBar, VerdictBanner, stripIcon,
} from "../components/Insights";
import { Markdown } from "../components/Markdown";
import { NoticeBar, useNotice } from "../components/Notice";
import { ResultTable } from "../components/ResultTable";
import { Card, ErrorNote, PageTitle } from "../components/ui";
import { VesselViewer, type VesselMedia } from "../components/VesselViewer";
import { useDebounced } from "../hooks";
import { downloadBlob, sliderStep } from "./assessment/model";
import {
  CENTRE_MODES, FEED_BASES, INITIAL, STATUS_LABEL, STATUS_TONE, TEST_TITLES, blankKpi, buildPlan, completeKpis,
  dominantTone, kpiStatus, kpiWarning, mirrorKpis, nextVolume, parse, round3, seedKpi, testKey, testScope, testStages,
  type Inputs, type KpiRow, type TestNo,
} from "./bourne/model";

type AssessResult = Schemas["BourneAssessResult"];
type AssessBody = Schemas["BourneAssessRequest"];
interface Assessed {
  key: string;
  scope: string;
  out: AssessResult;
  request: AssessBody;
}

const TESTS: TestNo[] = [1, 2, 3];
const DEFAULT_COLUMNS: Record<TestNo, string[]> = {
  1: ["Low speed", "Centre", "High speed"],
  2: ["Slow feed", "Centre", "Fast feed"],
  3: ["Surface", "Mid", "Impeller"],
};
const NOT_STARTED = "Define the system, then click Start Protocol.";
const STARTED = "Protocol started. Run Test 1 conditions and enter the responses.";
const INVALIDATED =
  "System or response inputs changed — previous Bourne assessments are invalid. " +
  "Reassessment required: please redo the protocol from Test 1.";

interface Project {
  projectName: string;
  step: string;
  unitOperation: string;
  processVersion: string;
}

const fmt = (x: number) => (Math.abs(x) >= 1000 || x === Math.round(x) ? String(x) : x.toPrecision(4).replace(/\.?0+$/, ""));

/** One test's verdict banner and a card per KPI (change vs threshold). */
function TestResult({ n, out, columns }: { n: TestNo; out: Schemas["BourneTestOut"]; columns: string[] }) {
  return (
    <>
      <VerdictBanner tone={STATUS_TONE[out.status]} eyebrow={`Test ${n} result · ${TEST_TITLES[n]}`} title={STATUS_LABEL[out.status]}>
        <Markdown>{stripIcon(out.verdict).replace(/^\*\*[^*]+\*\*\s*—\s*(\S)/, (_, c: string) => c.toUpperCase())}</Markdown>
      </VerdictBanner>
      <InsightGrid>
        {out.kpi_details.map((k, i) => {
          const st = kpiStatus(k);
          return (
            <InsightCard
              key={i}
              tone={st.tone}
              title={
                <>
                  {k.name}
                  {k.critical && (
                    <>
                      {" "}
                      <Pill tone="info">critical KPI</Pill>
                    </>
                  )}
                </>
              }
              status={st.label}
            >
              <div className="kpi-change">{k.max_change_pct.toFixed(1)}%</div>
              <div className="muted">max change from centre · threshold {k.threshold_pct.toFixed(0)}%</div>
              <ThresholdBar value={k.max_change_pct} threshold={k.threshold_pct} tone={st.tone} />
              <div className="kpi-values">
                {[k.low, k.centre, k.high].map((v, j) => (
                  <span key={j}>
                    {columns[j]}: <strong>{fmt(v)}</strong>
                    {k.unit && ` ${k.unit}`}
                  </span>
                ))}
              </div>
            </InsightCard>
          );
        })}
      </InsightGrid>
      <TableDetails rows={out.kpis} csvName={`bourne_test_${n}_kpi_results.csv`} />
    </>
  );
}

/** Decision-tree outcome: dominant regime, test tracker and key figures. */
function OutcomeDashboard({ out }: { out: Schemas["BourneAssessResult"] }) {
  const last = out.tests[out.tests.length - 1];
  const nSens = last.kpi_details.filter((k) => k.sensitive).length;
  return (
    <>
      <VerdictBanner
        tone={dominantTone(out.dominant, out.tentative)}
        eyebrow="Dominant mixing regime"
        title={out.tentative ? `${out.dominant} (tentative)` : out.dominant}
      >
        <Markdown>{stripIcon(out.conclusion)}</Markdown>
      </VerdictBanner>
      <Stages
        items={testStages(out).map((s) => ({ ...s, detail: s.detail ? <Markdown>{s.detail}</Markdown> : undefined }))}
      />
      <StatGrid
        size="sm"
        stats={[
          { label: "Tests assessed", value: `${out.tests.length} / 3` },
          {
            label: "Test 1 P/m span",
            value: `${out.pm_span.toFixed(out.pm_span < 100 ? 1 : 0)}×`,
            tone: out.pm_span >= 100 ? "ok" : "warning",
            hint: out.pm_span >= 100 ? "Full 100× range" : "Below the 100× intended",
          },
          {
            label: `Sensitive KPIs (Test ${last.test})`,
            value: `${nSens} / ${last.kpi_details.length}`,
            tone: nSens ? "critical" : "ok",
          },
          {
            label: "Next step",
            value: out.next_test ? `Run Test ${out.next_test}` : "Protocol complete",
            tone: out.next_test ? "info" : "ok",
          },
        ]}
      />
    </>
  );
}

/** Editable KPI response table (KPI / Unit suggestions, three responses, noise columns). */
function KpiEditor({
  test,
  rows,
  columns,
  metrics,
  units,
  onChange,
}: {
  test: TestNo;
  rows: KpiRow[];
  columns: string[];
  metrics: string[];
  units: string[];
  onChange: (rows: KpiRow[]) => void;
}) {
  const edit = (k: number, patch: Partial<KpiRow>) => onChange(rows.map((r, j) => (j === k ? { ...r, ...patch } : r)));
  const fields: (keyof KpiRow)[] = ["low", "centre", "high", "stdDev", "replicates"];
  const heads = [...columns, "Std dev", "Replicates"];
  return (
    <div className="table-scroll">
      <datalist id={`bp-metrics-${test}`}>
        {metrics.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>
      <datalist id={`bp-units-${test}`}>
        {units.map((u) => (
          <option key={u} value={u} />
        ))}
      </datalist>
      <table className="data-table kpi-editor" aria-label={`Test ${test} KPI responses`}>
        <thead>
          <tr>
            <th>KPI</th>
            <th>Unit</th>
            {heads.map((h) => (
              <th key={h}>{h}</th>
            ))}
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, k) => (
            <tr key={k}>
              <td>
                <input aria-label="KPI" list={`bp-metrics-${test}`} value={r.name} onChange={(e) => edit(k, { name: e.target.value })} />
              </td>
              <td>
                <input aria-label="Unit" list={`bp-units-${test}`} value={r.unit} onChange={(e) => edit(k, { unit: e.target.value })} />
              </td>
              {fields.map((f, j) => (
                <td key={f}>
                  <input
                    aria-label={heads[j]}
                    type="number"
                    step="any"
                    value={r[f]}
                    onChange={(e) => edit(k, { [f]: e.target.value })}
                  />
                </td>
              ))}
              <td>
                <button type="button" className="icon-btn" title="Delete row" onClick={() => onChange(rows.filter((_, j) => j !== k))}>
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={() => onChange([...rows, blankKpi()])}>
        Add KPI
      </button>
    </div>
  );
}

export function BourneProtocol() {
  const { notice, setNotice } = useNotice();
  const [tab, setTab] = useState<"Protocol" | "Plan">("Protocol");
  const [inputs, setInputs] = useState<Inputs>(INITIAL);
  const set = (patch: Partial<Inputs>) => setInputs((i) => ({ ...i, ...patch }));
  const [project, setProject] = useState<Project>({ projectName: "", step: "", unitOperation: "", processVersion: "" });
  const [started, setStarted] = useState(false);
  const [kpis, setKpis] = useState<Record<TestNo, KpiRow[]>>({ 1: [seedKpi()], 2: [seedKpi()], 3: [seedKpi()] });
  const [results, setResults] = useState<Partial<Record<TestNo, Assessed>>>({});
  const [limits, setLimits] = useState<Schemas["BourneDefaults"]["reactor_limits"] | null>(null);
  const [vRange, setVRange] = useState<[number, number] | null>(null);

  const options = useQuery({ queryKey: ["options"], queryFn: async () => unwrap(await api.GET("/api/v1/options")) });
  const bourneOptions = useQuery({
    queryKey: ["bourne-options"],
    queryFn: async () => unwrap(await api.GET("/api/v1/bourne/options")),
    staleTime: Infinity,
  });
  const columns = (n: TestNo) => bourneOptions.data?.kpi_columns[String(n)] ?? DEFAULT_COLUMNS[n];
  const metrics = bourneOptions.data?.response_metrics ?? [];
  const units = bourneOptions.data?.units ?? [];

  async function loadReactor(name: string) {
    const d = unwrap(await api.GET("/api/v1/bourne/defaults/{name}", { params: { path: { name } } }));
    set({ reactor: name, V_L: String(round3(d.V_L)), rpmCentre: String(d.centre_rpm) });
    setLimits(d.reactor_limits);
    setVRange([d.V_L_range[0], d.V_L_range[1]]);
  }
  const report = (p: Promise<unknown>) => void p.catch((e: Error) => setNotice({ kind: "error", text: e.message }));

  const initialised = useRef(false);
  useEffect(() => {
    const o = options.data;
    if (!o || initialised.current) return;
    initialised.current = true;
    const reactors = [...o.reactors].sort();
    set({ fluid: o.fluids.includes("Water") ? "Water" : (o.fluids[0] ?? "Water") });
    report(loadReactor(reactors.includes("TMA EasyMax-102") ? "TMA EasyMax-102" : (reactors[0] ?? "")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.data]);

  const media = useQuery({
    queryKey: ["vessel-media", inputs.reactor],
    queryFn: async () => {
      const res = await api.GET("/api/v1/media/vessels/{name}", { params: { path: { name: inputs.reactor } } });
      if (res.response.status === 404) return null;
      return unwrap(res) as unknown as VesselMedia;
    },
    enabled: !!inputs.reactor,
  });

  // --- plan tables (both tabs) --------------------------------------------------
  const built = buildPlan(inputs);
  const body = "body" in built ? built.body : null;
  const planBody = useDebounced(body, 300);
  const planWanted = !!planBody && (started || tab === "Plan");
  const plan = useQuery({
    queryKey: ["bourne-plan", planBody],
    queryFn: async () => unwrap(await api.POST("/api/v1/bourne/plan/tables", { body: planBody! })),
    enabled: planWanted,
    placeholderData: (prev) => prev,
  });
  const chart = useQuery({
    queryKey: ["bourne-speed-plan", planBody],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/charts/{kind}", { params: { path: { kind: "bourne-speed-plan" } }, body: planBody! }),
      ).figures.speed_plan,
    enabled: started && !!planBody && !!plan.data?.has_speed_plan,
  });
  const tables = plan.data;
  const planStale = !!tables && JSON.stringify(planBody) !== JSON.stringify(body);

  // --- assessments ---------------------------------------------------------------
  function valid(n: TestNo): Assessed | null {
    const r = results[n];
    if (!r || !body || r.key !== testKey(body, kpis, n)) return null;
    if (n > 1) {
      const prev = valid((n - 1) as TestNo);
      if (!prev?.out.tests.find((t) => t.test === n - 1)?.run_next_test) return null;
    }
    return r;
  }
  const outOf = (n: TestNo) => valid(n)?.out.tests.find((t) => t.test === n) ?? null;
  const show = (n: TestNo) => (n === 1 ? started : !!outOf((n - 1) as TestNo)?.run_next_test);
  const latest = [...TESTS].reverse().map(valid).find((r) => r) ?? null;
  const systemChanged = !!results[1] && !!body && results[1].scope !== JSON.stringify(testScope(body, 1));
  const status = !started ? NOT_STARTED : systemChanged ? INVALIDATED : STARTED;

  const assess = useMutation({
    mutationFn: async (n: TestNo) => {
      if (!body) throw new Error("error" in built ? built.error : "Check the inputs.");
      const request: AssessBody = { ...body, test1: [] };
      let warning: string | null = null;
      for (const t of TESTS.filter((t) => t <= n)) {
        const c = completeKpis(kpis[t], columns(t));
        if (t === n) {
          const w = kpiWarning(c);
          if (w?.block) throw new Error(w.text);
          warning = w?.text ?? null;
        }
        request[`test${t}`] = c.kpis;
      }
      const key = testKey(body, kpis, n);
      const scope = JSON.stringify(testScope(body, 1));
      const out = unwrap(await api.POST("/api/v1/bourne/assess", { body: request }));
      return { n, warning, assessed: { key, scope, out, request } };
    },
  });

  function onAssess(n: TestNo) {
    assess
      .mutateAsync(n)
      .then(({ warning, assessed }) => {
        setResults((r) => ({ ...r, [n]: assessed }));
        const t = assessed.out.tests.find((x) => x.test === n);
        if (t?.run_next_test && n < 3) {
          const next = (n + 1) as TestNo;
          setKpis((k) => ({ ...k, [next]: mirrorKpis(k[n], k[next]) }));
        }
        setNotice(warning ? { kind: "warning", text: warning } : { kind: "success", text: `Test ${n} assessed.` });
      })
      .catch((e: Error) => setNotice({ kind: "warning", text: e.message }));
  }

  const projectInfo = {
    project_name: project.projectName,
    step_number: project.step,
    unit_operation: project.unitOperation,
    process_version: project.processVersion,
  };
  const download = useMutation({
    mutationFn: async (kind: "pdf" | "csv") => {
      if (!latest) throw new Error("Assess at least Test 1 before exporting.");
      const url = kind === "pdf" ? "/api/v1/reports/bourne" : "/api/v1/bourne/sensitivity-csv";
      return postForFile(url, { ...latest.request, project: projectInfo });
    },
    onSuccess: ({ blob, filename }) => downloadBlob(blob, filename),
    onError: (e: Error) => setNotice({ kind: "error", text: e.message }),
  });

  // --- shared input blocks ------------------------------------------------------
  const vesselSelect = (
    <SelectField
      label="Vessel"
      value={inputs.reactor}
      options={[...(options.data?.reactors ?? [])].sort()}
      onChange={(v) => report(loadReactor(v))}
    />
  );
  const fluidSelect = (
    <SelectField label="Fluid" value={inputs.fluid} options={options.data?.fluids ?? []} onChange={(fluid) => set({ fluid })} />
  );
  const tField = <NumberField label="Temperature (°C)" value={inputs.T} onChange={(T) => set({ T })} />;
  const pField = <NumberField label="Pressure (atm)" value={inputs.P} onChange={(P) => set({ P })} />;
  const vField =
    vRange && vRange[1] > vRange[0] ? (
      <SliderField
        label="Working volume (L)"
        value={inputs.V_L}
        onChange={(V_L) => set({ V_L })}
        min={vRange[0]}
        max={vRange[1]}
        step={sliderStep(vRange[1] - vRange[0])}
        unit="L"
      />
    ) : (
      <NumberField label="Working volume (L)" value={inputs.V_L} onChange={(V_L) => set({ V_L })} />
    );
  const centreFields = (
    <div className="form-row">
      <SelectField
        label="Centre-point method"
        value={inputs.centreMode}
        options={CENTRE_MODES}
        onChange={(m) => set({ centreMode: m as Inputs["centreMode"] })}
      />
      <label>
        Centre P/m (W/kg)
        <input type="number" step="any" value={inputs.pmCentre} disabled={inputs.centreMode !== "custom_pm"} onChange={(e) => set({ pmCentre: e.target.value })} />
      </label>
      <label>
        Centre RPM
        <input type="number" step="any" value={inputs.rpmCentre} disabled={inputs.centreMode !== "custom_rpm"} onChange={(e) => set({ rpmCentre: e.target.value })} />
      </label>
    </div>
  );
  const feedFields = (
    <div className="form-row">
      <NumberField label="Total feed volume (mL)" value={inputs.feedVolume} onChange={(feedVolume) => set({ feedVolume })} />
      <Segmented label="Define by" value={inputs.feedBasis} options={FEED_BASES} onChange={(b) => set({ feedBasis: b as Inputs["feedBasis"] })} />
      <label>
        Feed rate (mL/min)
        <input type="number" step="any" value={inputs.feedRate} disabled={inputs.feedBasis !== "rate"} onChange={(e) => set({ feedRate: e.target.value })} />
      </label>
      <label>
        Feed time (min)
        <input type="number" step="any" value={inputs.feedTime} disabled={inputs.feedBasis !== "time"} onChange={(e) => set({ feedTime: e.target.value })} />
      </label>
    </div>
  );
  const ratioFields = (
    <div className="form-row">
      <NumberField label="Surface ε_loc/ε_avg" value={inputs.surface} onChange={(surface) => set({ surface })} />
      <NumberField label="Mid ε_loc/ε_avg" value={inputs.mid} onChange={(mid) => set({ mid })} />
      <NumberField label="Impeller ε_loc/ε_avg" value={inputs.impeller} onChange={(impeller) => set({ impeller })} />
    </div>
  );
  const inputError = "error" in built ? <p className="stale-note">{built.error}</p> : null;
  const conditions = (rows: Schemas["BournePlanTables"]["test1"] | undefined, csvName: string) =>
    rows ? <ResultTable rows={rows} csvName={csvName} stale={planStale} /> : plan.isFetching ? <p className="muted">Calculating…</p> : null;
  const test1Conditions = (
    <>
      {tables?.test1_speed_warning && (
        <VerdictBanner tone="warning" title="Stir-speed limit reached">
          <Markdown>{tables.test1_speed_warning}</Markdown>
        </VerdictBanner>
      )}
      {conditions(tables?.test1_summary, "bourne_test_1_conditions.csv")}
      {tables && (
        <details>
          <summary>All hydrodynamic parameters per condition</summary>
          <p className="muted">
            Literature correlations at each condition: power and torque, mean and maximum energy dissipation rate (EDR),
            tip speed, Re, Froude number, pumping, circulation and blend times, micromixing times, Kolmogorov scale, shear
            rates and stress, EDCF and surface kLa.
          </p>
          <ResultTable rows={tables.test1_detail} csvName="bourne_test_1_conditions_detail.csv" stale={planStale} />
        </details>
      )}
    </>
  );

  function kpiSection(n: TestNo) {
    const out = outOf(n);
    return (
      <>
        <KpiEditor test={n} rows={kpis[n]} columns={columns(n)} metrics={metrics} units={units} onChange={(rows) => setKpis((k) => ({ ...k, [n]: rows }))} />
        <p>
          <button type="button" className="primary" disabled={assess.isPending} onClick={() => onAssess(n)}>
            Assess Test {n}
          </button>
        </p>
        {out && <TestResult n={n} out={out} columns={columns(n)} />}
      </>
    );
  }

  return (
    <>
      <PageTitle pageKey="Bourne_Protocol">Bourne Protocol</PageTitle>
      {(options.isError || bourneOptions.isError) && <ErrorNote error={options.error ?? bourneOptions.error} />}
      <Segmented
        label="View"
        value={tab}
        options={[
          { code: "Protocol", label: "Protocol" },
          { code: "Plan", label: "Plan" },
        ]}
        onChange={(t) => setTab(t as "Protocol" | "Plan")}
      />

      {tab === "Protocol" ? (
        <>
          <p>{status}</p>
          <p>
            A structured mixing-sensitivity screen (Bourne, 2003). Three gated tests reveal whether mixing matters and, if so,
            which scale — <strong>micro</strong>, <strong>meso</strong>, or <strong>macro</strong> — controls the outcome.
          </p>
          <details>
            <summary>Decision-tree flowsheet</summary>
            <img className="decision-tree" src="/vimages/general/bourne_protocol_decision_tree.png" alt="Bourne Protocol decision tree" />
          </details>

          <Card title="Project Information">
            <div className="form-row">
              <label>
                Project name
                <input value={project.projectName} onChange={(e) => setProject({ ...project, projectName: e.target.value })} />
              </label>
              <label>
                Step
                <input value={project.step} onChange={(e) => setProject({ ...project, step: e.target.value })} />
              </label>
              <SelectField
                label="Unit operation"
                value={project.unitOperation}
                options={[{ code: "", label: "- select -" }, ...(bourneOptions.data?.unit_operations ?? []).map((u) => ({ code: u, label: u }))]}
                onChange={(unitOperation) => setProject({ ...project, unitOperation })}
              />
              <label>
                Process version
                <input value={project.processVersion} onChange={(e) => setProject({ ...project, processVersion: e.target.value })} />
              </label>
            </div>
          </Card>

          <Card title="System Definition">
            <div className="grid-2 va-top">
              <div>
                {vesselSelect}
                <div className="form-row">
                  {fluidSelect}
                  {tField}
                  {pField}
                </div>
                <div className="form-row">{vField}</div>
                {inputError}
                <p>
                  <strong>Reactor limits</strong>
                </p>
                {limits && <ResultTable rows={limits} />}
                <p>
                  <button
                    type="button"
                    className="primary"
                    onClick={() => {
                      setStarted(true);
                      setNotice({ kind: "success", text: "Protocol started." });
                    }}
                  >
                    Start Protocol
                  </button>
                </p>
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

          {started && (
            <Card title="Test 1 — Impeller Speed">
              <p>
                Vary the specific power <strong>P/m</strong> over a 100× range (0.1× → 10× the centre) at fixed volume. If the
                response barely moves, mixing is not rate-limiting.
              </p>
              <section className="sub-section">
                <h3>
                  <span className="sub-step">1.1</span> Centre point &amp; test conditions
                </h3>
                {centreFields}
                {tables && <Markdown>{tables.centre_info}</Markdown>}
                {test1Conditions}
              </section>

              <section className="sub-section">
                <h3>
                  <span className="sub-step">1.2</span> Discrete speed adjustments (fed-batch)
                </h3>
                <p>
                Step the impeller speed at volume milestones to hold <strong>P/m constant</strong> as the working volume grows.
                Enter one row per milestone volume (L).
              </p>
              <Switch
                label="Fed-batch speed adjustments"
                checked={inputs.fedBatch}
                onChange={(on) =>
                  set({
                    fedBatch: on,
                    volumes: on && !inputs.volumes.length ? [String(round3(parse(inputs.V_L) * 2))] : inputs.volumes,
                  })
                }
              />
              {inputs.fedBatch && (
                <div className="grid-2 va-top">
                  <div>
                    <table className="data-table kpi-editor" aria-label="Milestone volumes">
                      <thead>
                        <tr>
                          <th>Volume (L)</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {inputs.volumes.map((v, k) => (
                          <tr key={k}>
                            <td>
                              <input
                                aria-label="Volume (L)"
                                type="number"
                                step="any"
                                value={v}
                                onChange={(e) => set({ volumes: inputs.volumes.map((x, j) => (j === k ? e.target.value : x)) })}
                              />
                            </td>
                            <td>
                              <button type="button" className="icon-btn" title="Delete row" onClick={() => set({ volumes: inputs.volumes.filter((_, j) => j !== k) })}>
                                ✕
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <button type="button" onClick={() => set({ volumes: [...inputs.volumes, nextVolume(inputs.volumes, parse(inputs.V_L))] })}>
                      Add volume
                    </button>
                  </div>
                  <div>
                    {tables && <ResultTable rows={tables.setpoints} csvName="bourne_test_1_speed_adjustments.csv" stale={planStale} />}
                    {tables?.setpoints_caption && <Markdown>{tables.setpoints_caption}</Markdown>}
                  </div>
                </div>
              )}
              </section>

              <section className="sub-section">
                <h3>
                  <span className="sub-step">1.3</span> Impeller speed vs fill volume
                </h3>
              {tables && !tables.has_speed_plan ? (
                <p>
                  <em>This vessel has a single working volume, so the speed-vs-volume plot is not applicable.</em>
                </p>
              ) : (
                <>
                  <p>
                    Iso-<strong>P/m</strong> lines show the impeller speed needed to hold each condition&apos;s specific power
                    constant as the fill volume changes. The black dot is the working-volume centre-point; diamonds mark any
                    fed-batch set-points; dashed lines are the reactor RPM limits.
                  </p>
                  <Chart figure={chart.data} height={480} />
                </>
              )}
              </section>

              <section className="sub-section">
                <h3>
                  <span className="sub-step">1.4</span> Measured responses
                </h3>
                <p>
                Track one or more KPIs — add a row per metric. A KPI counts as sensitive when it changes by more than its
                threshold from the centre value (<strong>5%</strong> for yield / conversion / purity / selectivity,{" "}
                <strong>10%</strong> for impurity levels and particle size) and the change exceeds twice the measurement noise
                (optional <strong>Std dev</strong> and <strong>Replicates</strong> columns). The overall verdict is{" "}
                <em>sensitive</em> if any critical KPI (impurity, selectivity) or every KPI is sensitive, <em>not sensitive</em>{" "}
                if none is, and <em>inconclusive</em> for a mixed signal.
              </p>
              {kpiSection(1)}
              </section>
            </Card>
          )}

          {show(2) && (
            <Card title="Test 2 — Feed Rate / Time">
              <p>
                Hold P/m at the centre and vary the <strong>feed rate</strong> over a 9× range. Insensitivity means the reaction
                is <strong>micromixing</strong>-controlled; sensitivity points to mesomixing.
              </p>
              <section className="sub-section">
                <h3>
                  <span className="sub-step">2.1</span> Feed definition &amp; test conditions
                </h3>
                {feedFields}
                {conditions(tables?.test2, "bourne_test_2_conditions.csv")}
              </section>
              <section className="sub-section">
                <h3>
                  <span className="sub-step">2.2</span> Measured responses
                </h3>
                <p>
                  KPIs carry over from Test 1 — edit the responses (columns: <strong>Slow feed / Centre / Fast feed</strong>),
                  add or remove rows as needed.
                </p>
                {kpiSection(2)}
              </section>
            </Card>
          )}

          {show(3) && (
            <Card title="Test 3 — Feed Location">
              <p>
                Hold P/m and feed rate; move the feed point between low- and high-dissipation zones. Insensitivity means{" "}
                <strong>macromixing</strong> controls; sensitivity means mesomixing.
              </p>
              <section className="sub-section">
                <h3>
                  <span className="sub-step">3.1</span> Feed locations &amp; test conditions
                </h3>
                <p>
                  The local dissipation ratios below are illustrative defaults. Replace them with measured or CFD-derived values
                  when available.
                </p>
                {ratioFields}
                {conditions(tables?.test3, "bourne_test_3_conditions.csv")}
              </section>
              <section className="sub-section">
                <h3>
                  <span className="sub-step">3.2</span> Measured responses
                </h3>
                <p>
                  KPIs carry over from Test 2 — edit the responses (columns: <strong>Surface / Mid / Impeller</strong>).
                </p>
                {kpiSection(3)}
              </section>
            </Card>
          )}

          {latest && (
            <Card title="Summary">
              <OutcomeDashboard out={latest.out} />
              <h3>Export report</h3>
              <p>Generate a PDF capturing the system, each completed test&apos;s conditions and responses, and the decision-tree conclusion.</p>
              <button type="button" className="primary" disabled={download.isPending} onClick={() => download.mutate("pdf")}>
                Download PDF report
              </button>
              <h3>Export for the Reaction Sensitivity Protocol</h3>
              <p>
                Export the outcome as a CSV that can be imported into the <strong>Reaction Sensitivity Protocol</strong> (Step 1
                pre-screen) to feed the experimental result into the overall sensitivity assessment.
              </p>
              <button type="button" className="primary" disabled={download.isPending} onClick={() => download.mutate("csv")}>
                Download Sensitivity CSV
              </button>
            </Card>
          )}
        </>
      ) : (
        <>
          <h2>Experimental plan</h2>
          <p>
            Set the vessel, fluid and test inputs to calculate all three experimental condition sets. Planning does not require
            starting or assessing the protocol. These inputs are shared with the Protocol tab; changing them invalidates previous
            assessments.
          </p>
          <Card title="System">
            <div className="form-row">
              {vesselSelect}
              {fluidSelect}
              {vField}
              {tField}
              {pField}
            </div>
            {inputError}
            {limits && <ResultTable rows={limits} />}
          </Card>
          <Card title="Test 1: impeller speed">
            {centreFields}
            {tables && <Markdown>{tables.centre_info}</Markdown>}
            {test1Conditions}
          </Card>
          <Card title="Test 2: feed rate / time">
            {feedFields}
            {conditions(tables?.test2, "bourne_test_2_conditions.csv")}
          </Card>
          <Card title="Test 3: feed location">
            <p>
              Keep the centre-point speed and feed rate fixed. Local dissipation ratios are illustrative; use measured or
              CFD-derived values when available.
            </p>
            {ratioFields}
            {conditions(tables?.test3, "bourne_test_3_conditions.csv")}
          </Card>
        </>
      )}
      {plan.isError && <ErrorNote error={plan.error} />}
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
