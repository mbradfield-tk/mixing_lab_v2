import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, postForFile, unwrap, uploadFile, type Schemas } from "../api/client";
import { NumberField, SelectField, Switch } from "../components/Form";
import { Fader, InstrumentPanel, Knob } from "../components/Instrument";
import {
  ActionList, InsightCard, InsightGrid, LogScale, StatGrid, TableDetails, VerdictBanner, toneOf, type Tone,
} from "../components/Insights";
import { Markdown } from "../components/Markdown";
import { MultiSelect } from "../components/MultiSelect";
import { NoticeBar, useNotice } from "../components/Notice";
import { PropertyTable } from "../components/PropertyTable";
import { ResultTable } from "../components/ResultTable";
import { Card, ErrorNote, PageTitle } from "../components/ui";
import { useDebounced } from "../hooks";
import { downloadBlob, sliderStep } from "./assessment/model";
import {
  BLANK_PROJECT, DA_ZONES, INITIAL, SPEED_ZONES, SUMMARY_PENDING, SUMMARY_PRE_START, buildProtocol, bySeverity, daContext,
  findingRows, importPatch, reactionList, reactionPatch, severityCounts, sf, splitHeadline, timescaleTiles,
  type BourneImport, type Inputs, type Project,
} from "./sensitivity/model";

const NOT_RESOLVED = { code: "", label: "Not resolved" };
const SELECT = { code: "", label: "- select -" };
const TEST_LABELS = ["Test 1", "Test 2", "Test 3"];

function ResultBox({ children, tone }: { children: ReactNode; tone?: Tone }) {
  return <div className={`result-box${tone ? ` tone-${tone}` : ""}`}>{children}</div>;
}

const bourneTone = (sensitiveKpis: string): Tone => (/^none\b/i.test(sensitiveKpis.trim()) ? "ok" : "critical");

/** Step 8: verdict banner, severity tiles, finding cards (most severe first) and next steps. */
function SummaryDashboard({ res, bourne }: { res: Schemas["ProtocolPage"]; bourne: Schemas["BourneTestRow"][] }) {
  const [headline, rest] = splitHeadline(res.verdict);
  const counts = severityCounts(res.insights);
  const sorted = bySeverity(res.insights);
  const flagged = sorted.filter((f) => f.kind !== "ok");
  const clear = sorted.filter((f) => f.kind === "ok");
  const card = (f: Schemas["ProtocolPage"]["insights"][number]) => (
    <InsightCard key={f.area} tone={f.kind} title={f.area} status={f.status}>
      <Markdown>{f.detail}</Markdown>
    </InsightCard>
  );
  return (
    <>
      <VerdictBanner tone={res.verdict_kind} eyebrow="Overall verdict" title={headline}>
        {rest && <Markdown>{rest}</Markdown>}
      </VerdictBanner>
      <StatGrid
        size="sm"
        stats={[
          { label: "Likely limiting", value: counts.critical, tone: counts.critical ? "critical" : "info" },
          { label: "Watch", value: counts.watch, tone: counts.watch ? "warning" : "info" },
          { label: "Not a concern", value: counts.ok, tone: "ok" },
          { label: "Unknown", value: counts.unknown, tone: "unknown" },
        ]}
      />
      <h3>Recommended next steps</h3>
      <ActionList items={res.actions} />
      <h3>Findings</h3>
      {flagged.length > 0 ? <InsightGrid>{flagged.map(card)}</InsightGrid> : <p className="muted">Nothing flagged.</p>}
      {clear.length > 0 && (
        <details>
          <summary>Not a concern ({clear.length})</summary>
          <InsightGrid>{clear.map(card)}</InsightGrid>
        </details>
      )}
      {bourne.length > 0 && (
        <details>
          <summary>Bourne Protocol results ({bourne.length})</summary>
          <InsightGrid>
            {bourne.map((b) => (
              <InsightCard key={b.test} tone={bourneTone(b.sensitive_kpis)} title={b.test}>
                <p>{b.finding}</p>
                <p className="muted">Sensitive KPI(s): {b.sensitive_kpis}</p>
              </InsightCard>
            ))}
          </InsightGrid>
        </details>
      )}
      <TableDetails rows={res.findings} csvName="sensitivity_findings.csv" summary="Findings as table" />
      <TableDetails rows={res.next_steps} csvName="sensitivity_next_steps.csv" summary="Next steps as table" />
    </>
  );
}

export function MixingSensitivity() {
  const { notice, setNotice } = useNotice();
  const [inputs, setInputs] = useState<Inputs>(INITIAL);
  const set = (patch: Partial<Inputs>) => setInputs((i) => ({ ...i, ...patch }));
  const [project, setProject] = useState<Project>(BLANK_PROJECT);
  const [started, setStarted] = useState(false);
  const [daRanges, setDaRanges] = useState<{ N: [number, number]; V: [number, number] } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const options = useQuery({ queryKey: ["options"], queryFn: async () => unwrap(await api.GET("/api/v1/options")) });
  const msOptions = useQuery({
    queryKey: ["sensitivity-options"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sensitivity/options")),
    staleTime: Infinity,
  });
  const enums = options.data?.enums ?? {};
  const dhRefs = msOptions.data?.dh_references ?? {};
  const dhRefNames = Object.keys(dhRefs).length ? Object.keys(dhRefs) : ["(none available)"];
  const unitOperations = msOptions.data?.unit_operations ?? [];
  const reactions = reactionList(inputs.kineticsAvail, options.data?.reactions_measured ?? [], options.data?.reaction_classes ?? []);

  const report = (p: Promise<unknown>) => void p.catch((e: Error) => setNotice({ kind: "error", text: e.message }));
  async function loadReaction(name: string) {
    const d = unwrap(await api.GET("/api/v1/sensitivity/reaction-defaults", { params: { query: { reaction: name } } }));
    set(reactionPatch(name, d));
  }
  async function updateRhoCp(T: string) {
    if (!inputs.reaction) return;
    const d = unwrap(
      await api.GET("/api/v1/sensitivity/reaction-defaults", { params: { query: { reaction: inputs.reaction, T_C: sf(T, 25) } } }),
    );
    if (d.rho_cp_kJ_m3K != null) set({ rhoCp: String(d.rho_cp_kJ_m3K) });
  }
  async function loadVessel(name: string) {
    const [d, v] = await Promise.all([
      api.GET("/api/v1/bourne/defaults/{name}", { params: { path: { name } } }).then(unwrap),
      api.GET("/api/v1/assessment/vessel-defaults/{name}", { params: { path: { name } } }).then(unwrap),
    ]);
    setDaRanges({ N: [v.N_rpm_range[0], v.N_rpm_range[1]], V: [v.V_L_range[0], v.V_L_range[1]] });
    set({ daReactor: name, daRpm: String(d.centre_rpm), daVl: String(d.V_L) });
  }

  function defaults() {
    const o = options.data!;
    const measured = o.reactions_measured.length ? o.reactions_measured : o.reaction_classes;
    const reactors = o.reactors;
    setInputs({ ...INITIAL, dhRef: dhRefNames[0] });
    report(loadReaction(measured[0] ?? ""));
    report(loadVessel(reactors.includes("TMA EasyMax-102") ? "TMA EasyMax-102" : (reactors[0] ?? "")));
  }
  const initialised = useRef(false);
  useEffect(() => {
    if (!options.data || !msOptions.data || initialised.current) return;
    initialised.current = true;
    defaults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.data, msOptions.data]);

  // --- live assessment once started -------------------------------------------
  const built = buildProtocol(inputs, dhRefs);
  const body = "body" in built ? built.body : null;
  const debounced = useDebounced(body, 300);
  const page = useQuery({
    queryKey: ["sensitivity-page", debounced],
    queryFn: async () => unwrap(await api.POST("/api/v1/sensitivity/page", { body: debounced! })),
    enabled: started && !!debounced,
    placeholderData: (prev) => prev,
  });
  const res = started ? page.data : undefined;
  const stale = !!res && JSON.stringify(debounced) !== JSON.stringify(body);
  const step = (n: number) => (res?.steps[n] ? <Markdown>{res.steps[n]}</Markdown> : null);
  const stepTone = (n: number) => (res?.steps[n] ? toneOf(res.steps[n]) : undefined);

  const importCsv = useMutation({
    mutationFn: (file: File) => uploadFile<BourneImport>("/api/v1/sensitivity/bourne-import", file, "POST"),
    onSuccess: (imp) => {
      const p = importPatch(imp, project, unitOperations);
      set(p.inputs);
      setProject(p.project);
      setNotice({ kind: "success", text: "Bourne results imported." });
    },
    onError: (e: Error) => setNotice({ kind: "error", text: e.message }),
    onSettled: () => {
      if (fileInput.current) fileInput.current.value = "";
    },
  });

  const pdf = useMutation({
    mutationFn: () => {
      if (!res?.ready || !body) throw new Error("Complete the assessment (Steps 2, 3, 5 and 6) before exporting.");
      return postForFile("/api/v1/reports/sensitivity", {
        protocol: body,
        reaction_name: inputs.reaction,
        bourne_meta: inputs.bourneMeta,
        project: {
          project_name: project.projectName,
          step_number: project.step,
          unit_operation: project.unitOperation,
          process_version: project.processVersion,
        },
      });
    },
    onSuccess: ({ blob, filename }) => downloadBlob(blob, filename),
    onError: (e: Error) => setNotice({ kind: "error", text: e.message }),
  });

  const label = (name: string, code: string) => enums[name]?.find((o) => o.code === code)?.label ?? code;
  const codeOf = (name: string, lbl: string) => enums[name]?.find((o) => o.label === lbl)?.code ?? lbl;

  return (
    <>
      <PageTitle pageKey="Mixing_Sensitivity">Reaction Sensitivity Protocol</PageTitle>
      {(options.isError || msOptions.isError) && <ErrorNote error={options.error ?? msOptions.error} />}
      <p>
        Find out <strong>whether a reaction is sensitive to mixing</strong> and, if so, <strong>which mechanism</strong>{" "}
        controls it. Fill in the steps, then run the assessment for an overall verdict.
      </p>
      <details>
        <summary>Decision-tree flowsheet</summary>
        <img className="decision-tree" src="/vimages/general/mixing_sensitivity_protocol.png" alt="Reaction mixing sensitivity protocol" />
      </details>

      <Card title="Project Information">
        <div className="prop-narrow">
          <PropertyTable
            groups={[
              {
                title: "Project",
                rows: [
                  {
                    label: "Project name",
                    text: true,
                    value: project.projectName,
                    onChange: (projectName) => setProject({ ...project, projectName }),
                  },
                  { label: "Step", text: true, value: project.step, onChange: (step) => setProject({ ...project, step }) },
                  {
                    label: "Unit operation",
                    value: project.unitOperation,
                    options: [SELECT, ...unitOperations.map((u) => ({ code: u, label: u }))],
                    onChange: (unitOperation) => setProject({ ...project, unitOperation }),
                  },
                  {
                    label: "Process version",
                    text: true,
                    value: project.processVersion,
                    onChange: (processVersion) => setProject({ ...project, processVersion }),
                  },
                ],
              },
            ]}
          />
        </div>
      </Card>

      {started && (
        <p className="button-row">
          <button
            type="button"
            className="primary"
            onClick={() => {
              void page.refetch();
              setNotice({ kind: "success", text: "Assessment updated with the current inputs." });
            }}
          >
            Update assessment
          </button>{" "}
          <button
            type="button"
            className="primary"
            onClick={() => {
              setStarted(false);
              setProject(BLANK_PROJECT);
              defaults();
              setNotice({ kind: "info", text: "Assessment reset - set your inputs and start again." });
            }}
          >
            Reset assessment
          </button>
        </p>
      )}
      {"error" in built && <p className="stale-note">{built.error}</p>}
      {page.isError && started && <ErrorNote error={page.error} />}

      <Card title="Step 1 - Bourne Protocol Pre-Screen">
        <p>Have you run the Bourne Protocol? Enter the outcome or import its results CSV.</p>
        <div className="form-row">
          <SelectField
            label="Bourne outcome"
            value={inputs.bourneStatus}
            options={enums.BourneStatus ?? []}
            onChange={(v) => set({ bourneStatus: v as Inputs["bourneStatus"] })}
          />
          <label>
            Controlling scale identified
            <select
              value={inputs.bourneMech}
              disabled={inputs.bourneStatus !== "confirmed"}
              onChange={(e) => set({ bourneMech: e.target.value as Inputs["bourneMech"] })}
            >
              {[NOT_RESOLVED, ...(enums.Mechanism ?? [])].map((o) => (
                <option key={o.code} value={o.code}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <MultiSelect
            label="Tests completed"
            options={TEST_LABELS}
            value={inputs.bourneTests.map((n) => TEST_LABELS[n - 1])}
            placeholder="None"
            onChange={(v) => set({ bourneTests: v.map((l) => (TEST_LABELS.indexOf(l) + 1) as 1 | 2 | 3) })}
          />
        </div>
        <label>
          Import Bourne results CSV (optional)
          <input
            ref={fileInput}
            type="file"
            accept=".csv"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importCsv.mutate(f);
            }}
          />
        </label>
        {inputs.bourneMetaCaption && <Markdown>{inputs.bourneMetaCaption}</Markdown>}
        {inputs.bourneFindings.length > 0 && (
          <details>
            <summary>Imported Bourne results</summary>
            <ResultTable rows={findingRows(inputs.bourneFindings)} />
          </details>
        )}
        {res && step(0) && <ResultBox tone={stepTone(0)}>{step(0)}</ResultBox>}
      </Card>

      <Card title="Step 2 - Reaction Kinetics">
        <p>
          The reaction time <strong>t<sub>rxn</sub></strong> is compared with each mixing time below. Values are filled from the
          database; edit any to override.
        </p>
        <div className="grid-2 prop-grid">
          <PropertyTable
            groups={[
              {
                title: "Reaction",
                rows: [
                  {
                    label: "Kinetics available?",
                    value: inputs.kineticsAvail,
                    options: enums.Kinetics ?? [],
                    onChange: (v) => {
                      const list = reactionList(v, options.data?.reactions_measured ?? [], options.data?.reaction_classes ?? []);
                      set({ kineticsAvail: v as Inputs["kineticsAvail"] });
                      if (!list.includes(inputs.reaction)) report(loadReaction(list[0]));
                    },
                  },
                  { label: "Reaction or proxy class", value: inputs.reaction, options: reactions, onChange: (v) => report(loadReaction(v)) },
                  { label: "Order", value: inputs.order, options: msOptions.data?.reaction_orders ?? [], onChange: (order) => set({ order }) },
                ],
              },
            ]}
          />
          <PropertyTable
            groups={[
              {
                title: "Kinetics",
                rows: [
                  { label: "Rate constant k", unit: "1/s or L/mol·s", value: inputs.k, onChange: (k) => set({ k }) },
                  {
                    label: "Initial concentration C₀",
                    unit: "mol/L",
                    value: inputs.c0,
                    onChange: (c0) => set(sf(c0) > 0 ? { c0, c0Heat: String(Math.round(sf(c0) * 1e4) / 1e4) } : { c0 }),
                  },
                  { label: "Reaction time t_rxn", unit: "s (0 = from k)", value: inputs.tRxn, onChange: (tRxn) => set({ tRxn }) },
                  {
                    label: "Temperature",
                    unit: "°C",
                    value: inputs.T,
                    onChange: (T) => {
                      set({ T });
                      report(updateRhoCp(T));
                    },
                  },
                  { label: "Heat of reaction ΔH", unit: "kJ/mol", value: inputs.dH, onChange: (dH) => set({ dH }) },
                ],
              },
            ]}
          />
        </div>
        {res && (
          <ResultBox tone={stepTone(1)}>
            {res.kinetics_md && <Markdown>{res.kinetics_md}</Markdown>}
            {step(1)}
          </ResultBox>
        )}
      </Card>

      <Card title="Step 3 - Phase Assessment">
        <p>
          With more than one phase, transfer between phases (gas–liquid k<sub>L</sub>a, solid–liquid dissolution) can limit the
          rate before mixing does.
        </p>
        <MultiSelect
          label="Which phases are present?"
          options={(enums.Phase ?? []).map((o) => o.label)}
          value={inputs.phases.map((p) => label("Phase", p))}
          placeholder="None"
          onChange={(v) => set({ phases: v.map((l) => codeOf("Phase", l) as Inputs["phases"][number]) })}
        />
        {res && step(2) && <ResultBox tone={stepTone(2)}>{step(2)}</ResultBox>}
      </Card>

      <Card title="Step 4 - Feed Mode (Mesomixing)">
        <p>
          When a reagent is fed, the feed rate and local turbulence decide how fast it disperses. A batch process has no feed, so no
          feed-zone risk.
        </p>
        <Switch label="Semi-batch (fed-batch) process" checked={inputs.semiBatch} onChange={(semiBatch) => set({ semiBatch })} />
        {res && (
          <ResultBox tone={inputs.semiBatch ? "warning" : "ok"}>
            {inputs.semiBatch ? (
              <p>
                <strong>Semi-batch</strong> - feed rate and location matter (see Step 5 and the recommendations).
              </p>
            ) : (
              <p>
                <strong>Batch</strong> - no feed-zone risk.
              </p>
            )}
          </ResultBox>
        )}
      </Card>

      <Card title="Step 5 - Competing Reactions">
        <p>If side reactions compete for a reagent, slow local mixing can shift selectivity.</p>
        <SelectField
          label="Are there competing reactions?"
          value={inputs.competing}
          options={[SELECT, ...(enums.Competing ?? [])]}
          onChange={(v) => set({ competing: v as Inputs["competing"] })}
        />
        {res && step(3) && <ResultBox tone={stepTone(3)}>{step(3)}</ResultBox>}
      </Card>

      <Card title="Step 6 - Heat Transfer Screening">
        <p>
          Screened by the <strong>adiabatic temperature rise</strong> ΔT<sub>ad</sub> = |ΔH|·C₀·1000/(ρ·Cp): the temperature
          change at full conversion with no cooling.
        </p>
        <div className="prop-narrow">
          <PropertyTable
            groups={[
              ...(res?.show_dh_action
                ? [
                    {
                      title: "No ΔH data for this reaction",
                      rows: [
                        {
                          label: "ΔH source",
                          value: inputs.dhAction,
                          options: [SELECT, ...(enums.DhAction ?? [])],
                          onChange: (v: string) => set({ dhAction: v as Inputs["dhAction"] }),
                        },
                        {
                          label: "Reference reaction",
                          value: inputs.dhRef,
                          options: dhRefNames,
                          disabled: inputs.dhAction !== "estimate",
                          onChange: (dhRef: string) => set({ dhRef }),
                        },
                      ],
                    },
                  ]
                : []),
              {
                title: "Heat balance",
                rows: [
                  { label: "Volumetric heat capacity ρ·Cp", unit: "kJ/m³·K", value: inputs.rhoCp, onChange: (rhoCp) => set({ rhoCp }) },
                  { label: "Limiting-reagent C₀", unit: "mol/L", value: inputs.c0Heat, onChange: (c0Heat) => set({ c0Heat }) },
                  {
                    label: "ΔH override",
                    unit: "kJ/mol (0 = Step 2)",
                    value: inputs.dhOverride,
                    onChange: (dhOverride) => set({ dhOverride }),
                  },
                  {
                    label: "Override ΔH measured?",
                    value: inputs.dhMeasured,
                    options: enums.DhBasis ?? [],
                    onChange: (v) => set({ dhMeasured: v as Inputs["dhMeasured"] }),
                  },
                ],
              },
            ]}
          />
        </div>
        <p className="muted">Proxy-kinetics ΔH counts as estimated unless the override is marked measured.</p>
        {res && (
          <ResultBox tone={stepTone(4)}>
            {res.dt_ad_caption && <Markdown>{res.dt_ad_caption}</Markdown>}
            {step(4)}
          </ResultBox>
        )}
      </Card>

      <Card title="Step 7 - Mixing Time vs Reaction Time">
        <p>
          <strong>Da = mixing time / reaction time.</strong> Below 0.1 mixing does not limit; above 1 it does. Pick a vessel for
          actual values.
        </p>
        <Switch label="Compute Damköhler numbers for a vessel" checked={inputs.daOn} onChange={(daOn) => set({ daOn })} />
        {inputs.daOn && (
          <>
            <div className="form-row">
              <SelectField label="Vessel" value={inputs.daReactor} options={options.data?.reactors ?? []} onChange={(v) => report(loadVessel(v))} />
            </div>
            <InstrumentPanel title="Operating point">
              {daRanges && daRanges.N[1] > daRanges.N[0] ? (
                <Knob
                  label="Stir speed"
                  value={inputs.daRpm}
                  onChange={(daRpm) => set({ daRpm })}
                  min={daRanges.N[0]}
                  max={daRanges.N[1]}
                  step={sliderStep(daRanges.N[1] - daRanges.N[0])}
                  unit="RPM"
                />
              ) : (
                <NumberField label="Agitation speed N (RPM)" value={inputs.daRpm} onChange={(daRpm) => set({ daRpm })} />
              )}
              {daRanges && daRanges.V[1] > daRanges.V[0] ? (
                <Fader
                  label="Working volume"
                  value={inputs.daVl}
                  onChange={(daVl) => set({ daVl })}
                  min={daRanges.V[0]}
                  max={daRanges.V[1]}
                  step={sliderStep(daRanges.V[1] - daRanges.V[0])}
                  unit="L"
                />
              ) : (
                <NumberField label="Working volume (L)" value={inputs.daVl} onChange={(daVl) => set({ daVl })} />
              )}
            </InstrumentPanel>
          </>
        )}
        {res && step(5) && (
          <ResultBox tone={stepTone(5)}>
            <StatGrid size="sm" stats={timescaleTiles(res.t_rxn_s, res.damkohler)} />
            {res.damkohler ? (
              <>
                <LogScale
                  min={1e-4}
                  max={100}
                  zones={DA_ZONES}
                  markers={[
                    { label: "Da micro", value: res.damkohler.Da_micro ?? 0 },
                    { label: "Da macro", value: res.damkohler.Da_macro ?? 0 },
                  ]}
                />
                <p className="muted">{daContext(res.damkohler)}</p>
              </>
            ) : res.t_rxn_s ? (
              <LogScale min={1e-4} max={1000} zones={SPEED_ZONES} markers={[{ label: "t_rxn", value: res.t_rxn_s }]} unit=" s" />
            ) : null}
            {step(5)}
          </ResultBox>
        )}
        <details>
          <summary>How it&apos;s calculated</summary>
          <Markdown>
            {"Micromixing time $t_E \\approx 17.3\\sqrt{\\nu/\\varepsilon}$; blend time $\\theta_{95} = 5.2\\,T^{1.5}H^{0.5}/(N_p^{1/3} N D^2)$. " +
              "At constant P/V the blend time grows roughly as $T^{2/3}$, so re-check at each scale."}
          </Markdown>
        </details>
      </Card>

      {!started && (
        <Card title="Ready?">
          <p>Run the assessment to see each step&apos;s result and the overall verdict.</p>
          <button
            type="button"
            className="primary"
            onClick={() => {
              setStarted(true);
              if (inputs.reaction) report(loadReaction(inputs.reaction));
            }}
          >
            Run assessment
          </button>
        </Card>
      )}

      <Card title="Step 8 - Summary & Recommendations">
        {stale && <p className="stale-note">Updating…</p>}
        <Markdown>{res ? (res.ready ? "" : SUMMARY_PENDING) : SUMMARY_PRE_START}</Markdown>
        {res?.ready && (
          <SummaryDashboard res={res} bourne={inputs.bourneFindings} />
        )}
      </Card>

      {res?.ready && (
        <Card title="Step 9 - Export Report">
          <p>PDF with the inputs, findings, verdict and next steps.</p>
          <button type="button" className="primary" disabled={pdf.isPending || stale} onClick={() => pdf.mutate()}>
            Download PDF report
          </button>
        </Card>
      )}
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
