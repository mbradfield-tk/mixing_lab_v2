import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, postForFile, unwrap, uploadFile, type Schemas } from "../api/client";
import { NumberField, SelectField, Switch } from "../components/Form";
import {
  ActionList, InsightCard, InsightGrid, StatGrid, TableDetails, VerdictBanner, toneOf, type Tone,
} from "../components/Insights";
import { Markdown } from "../components/Markdown";
import { MultiSelect } from "../components/MultiSelect";
import { NoticeBar, useNotice } from "../components/Notice";
import { ResultTable } from "../components/ResultTable";
import { Card, ErrorNote, PageTitle } from "../components/ui";
import { useDebounced } from "../hooks";
import { downloadBlob } from "./assessment/model";
import {
  BLANK_PROJECT, INITIAL, SUMMARY_PRE_START, buildProtocol, bySeverity, findingRows, importPatch, reactionList,
  reactionPatch, severityCounts, sf, splitHeadline, type BourneImport, type Inputs, type Project,
} from "./sensitivity/model";

const NOT_RESOLVED = { code: "", label: "Not resolved" };
const SELECT = { code: "", label: "- select -" };
const TEST_LABELS = ["Test 1", "Test 2", "Test 3"];

function ResultBox({ children, tone }: { children: ReactNode; tone?: Tone }) {
  return <div className={`result-box${tone ? ` tone-${tone}` : ""}`}>{children}</div>;
}

const bourneTone = (sensitiveKpis: string): Tone => (/^none\b/i.test(sensitiveKpis.trim()) ? "ok" : "critical");

/** Step 6: verdict banner, severity tiles, finding cards (most severe first) and next steps. */
function SummaryDashboard({ res, bourne }: { res: Schemas["ProtocolPage"]; bourne: Schemas["BourneTestRow"][] }) {
  const [headline, rest] = splitHeadline(res.verdict);
  const counts = severityCounts(res.insights);
  return (
    <>
      <VerdictBanner tone={res.verdict_kind} eyebrow="Overall verdict" title={headline}>
        {rest && <Markdown>{rest}</Markdown>}
      </VerdictBanner>
      <StatGrid
        size="sm"
        stats={[
          { label: "Likely sensitive", value: counts.critical, tone: counts.critical ? "critical" : "info" },
          { label: "Watch / borderline", value: counts.watch, tone: counts.watch ? "warning" : "info" },
          { label: "Unlikely / manageable", value: counts.ok, tone: "ok" },
          { label: "Unknown", value: counts.unknown, tone: "unknown" },
        ]}
      />
      <h3>Sensitivity findings</h3>
      <InsightGrid>
        {bySeverity(res.insights).map((f) => (
          <InsightCard key={f.area} tone={f.kind} title={f.area} status={f.status}>
            <Markdown>{f.detail}</Markdown>
          </InsightCard>
        ))}
      </InsightGrid>
      <TableDetails rows={res.findings} csvName="sensitivity_findings.csv" />
      {bourne.length > 0 && (
        <>
          <h3>Bourne Protocol experimental findings</h3>
          <InsightGrid>
            {bourne.map((b) => (
              <InsightCard key={b.test} tone={bourneTone(b.sensitive_kpis)} title={b.test}>
                <p>{b.finding}</p>
                <p className="muted">Sensitive KPI(s): {b.sensitive_kpis}</p>
              </InsightCard>
            ))}
          </InsightGrid>
        </>
      )}
      <h3>Recommended next steps</h3>
      <ActionList items={res.actions} />
      <TableDetails rows={res.next_steps} csvName="sensitivity_next_steps.csv" />
    </>
  );
}

export function MixingSensitivity() {
  const { notice, setNotice } = useNotice();
  const [inputs, setInputs] = useState<Inputs>(INITIAL);
  const set = (patch: Partial<Inputs>) => setInputs((i) => ({ ...i, ...patch }));
  const [project, setProject] = useState<Project>(BLANK_PROJECT);
  const [started, setStarted] = useState(false);
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
    const d = unwrap(await api.GET("/api/v1/bourne/defaults/{name}", { params: { path: { name } } }));
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
      if (!res?.ready || !body) throw new Error("Complete the assessment (Steps 1–4) before exporting.");
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
        A guided decision tree to determine <strong>whether a reaction is sensitive to mixing</strong> and, if so,{" "}
        <strong>which mechanism controls</strong> it - micromixing, mesomixing, macromixing, interphase mass transport, or heat
        transfer. Work through the steps; the <strong>Summary</strong> synthesises everything into an overall verdict.
      </p>
      <details>
        <summary>Decision-tree flowsheet</summary>
        <img className="decision-tree" src="/vimages/general/mixing_sensitivity_protocol.png" alt="Reaction mixing sensitivity protocol" />
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
            options={[SELECT, ...unitOperations.map((u) => ({ code: u, label: u }))]}
            onChange={(unitOperation) => setProject({ ...project, unitOperation })}
          />
          <label>
            Process version
            <input value={project.processVersion} onChange={(e) => setProject({ ...project, processVersion: e.target.value })} />
          </label>
        </div>
      </Card>

      {!started ? (
        <p>
          <strong>
            Set your inputs in the steps below, then click <em>Run assessment</em> at the bottom of the page.
          </strong>{" "}
          No results are shown until you do.
        </p>
      ) : (
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

      <Card title="Step 0 - Bourne Protocol Pre-Screen">
        <p>
          Independent experimental evidence of whether a mixing sensitivity exists. If you have run the Bourne Protocol, enter the
          outcome (or import its results CSV).
        </p>
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
        {inputs.bourneFindings.length > 0 && <ResultTable rows={findingRows(inputs.bourneFindings)} />}
        {res && step(0) && <ResultBox tone={stepTone(0)}>{step(0)}</ResultBox>}
      </Card>

      <Card title="Step 1 - Reaction Kinetics">
        <p>
          The characteristic reaction time <strong>t<sub>rxn</sub></strong> is the Damköhler reference timescale for every
          mechanism below. When derived from k and C₀, the protocol uses a conservative 90% conversion process-window estimate
          rather than only the initial rate.
        </p>
        <div className="form-row">
          <SelectField
            label="Are kinetics available?"
            value={inputs.kineticsAvail}
            options={enums.Kinetics ?? []}
            onChange={(v) => {
              const list = reactionList(v, options.data?.reactions_measured ?? [], options.data?.reaction_classes ?? []);
              set({ kineticsAvail: v as Inputs["kineticsAvail"] });
              if (!list.includes(inputs.reaction)) report(loadReaction(list[0]));
            }}
          />
          <SelectField label="Reaction or proxy class" value={inputs.reaction} options={reactions} onChange={(v) => report(loadReaction(v))} />
        </div>
        <p>
          <strong>Reaction conditions &amp; kinetics</strong> - auto-filled from the database; edit any value to override.
        </p>
        <div className="form-row">
          <SelectField label="Reaction order" value={inputs.order} options={msOptions.data?.reaction_orders ?? []} onChange={(order) => set({ order })} />
          <NumberField label="Rate constant k (1/s or L/mol·s)" value={inputs.k} onChange={(k) => set({ k })} />
          <NumberField
            label="C₀ (mol/L)"
            value={inputs.c0}
            onChange={(c0) => set(sf(c0) > 0 ? { c0, c0Heat: String(Math.round(sf(c0) * 1e4) / 1e4) } : { c0 })}
          />
        </div>
        <div className="form-row">
          <NumberField label="Reaction time (s, 0 = derive from k)" value={inputs.tRxn} onChange={(tRxn) => set({ tRxn })} />
          <NumberField
            label="Temperature (°C)"
            value={inputs.T}
            onChange={(T) => {
              set({ T });
              report(updateRhoCp(T));
            }}
          />
          <NumberField label="ΔH (kJ/mol)" value={inputs.dH} onChange={(dH) => set({ dH })} />
        </div>
        <Switch label="Semi-batch (fed-batch) process" checked={inputs.semiBatch} onChange={(semiBatch) => set({ semiBatch })} />
        {res && (
          <ResultBox tone={stepTone(1)}>
            {res.kinetics_md && <Markdown>{res.kinetics_md}</Markdown>}
            {step(1)}
          </ResultBox>
        )}
      </Card>

      <Card title="Step 2 - Phase Assessment">
        <p>
          Multi-phase systems can be limited by <strong>interphase mass transfer</strong> before mixing even matters. This includes
          gas–liquid (k<sub>L</sub>a) transport and solid–liquid (k<sub>SL</sub>) transport such as solid dissolution, adsorption,
          and desorption.
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

      <Card title="Step 3 - Competing Reactions">
        <p>
          When parallel/consecutive reactions compete for a reagent, incomplete <strong>micromixing</strong> (molecular scale) and{" "}
          <strong>mesomixing</strong> (feed-plume scale) can shift selectivity.
        </p>
        <SelectField
          label="Are there competing reactions?"
          value={inputs.competing}
          options={[SELECT, ...(enums.Competing ?? [])]}
          onChange={(v) => set({ competing: v as Inputs["competing"] })}
        />
        {res && step(3) && <ResultBox tone={stepTone(3)}>{step(3)}</ResultBox>}
      </Card>

      <Card title="Step 4 - Heat Transfer Screening">
        <p>
          The thermal load is set by the enthalpy of reaction (ΔH) and the limiting-reagent concentration (C₀), and is assessed by
          the <strong>adiabatic temperature rise</strong> (ΔT<sub>ad</sub> = |ΔH|·C₀·1000/(ρ·Cp)) - the temperature increase at
          full conversion with no cooling and perfect insulation. The reaction rate does not change ΔT_ad, but a faster reaction
          releases that heat more quickly and is harder to cool.
        </p>
        {res?.show_dh_action && (
          <>
            <p>
              The selected reaction has <strong>no ΔH data</strong>. Choose how to proceed:
            </p>
            <div className="form-row">
              <SelectField
                label="ΔH source"
                value={inputs.dhAction}
                options={[SELECT, ...(enums.DhAction ?? [])]}
                onChange={(v) => set({ dhAction: v as Inputs["dhAction"] })}
              />
              <label>
                Reference reaction for ΔH
                <select value={inputs.dhRef} disabled={inputs.dhAction !== "estimate"} onChange={(e) => set({ dhRef: e.target.value })}>
                  {dhRefNames.map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
            </div>
          </>
        )}
        <p>
          <strong>Heat of reaction basis</strong> - optionally override the ΔH used for this screening and state whether the value
          was measured experimentally. With proxy kinetics, the ΔH is treated as estimated unless a measured override is entered.
        </p>
        <div className="form-row">
          <NumberField label="ΔH override (kJ/mol, 0 = use Step 1 value)" value={inputs.dhOverride} onChange={(dhOverride) => set({ dhOverride })} />
          <SelectField
            label="Override ΔH measured?"
            value={inputs.dhMeasured}
            options={enums.DhBasis ?? []}
            onChange={(v) => set({ dhMeasured: v as Inputs["dhMeasured"] })}
          />
        </div>
        <div className="form-row">
          <NumberField label="Volumetric heat capacity ρ·Cp (kJ/m³·K)" value={inputs.rhoCp} onChange={(rhoCp) => set({ rhoCp })} />
          <NumberField label="Limiting-reagent C₀ (mol/L)" value={inputs.c0Heat} onChange={(c0Heat) => set({ c0Heat })} />
        </div>
        {res && (
          <ResultBox tone={stepTone(4)}>
            {res.dt_ad_caption && <Markdown>{res.dt_ad_caption}</Markdown>}
            {step(4)}
          </ResultBox>
        )}
      </Card>

      <Card title="Step 5 - Mixing Time vs Reaction Time">
        <p>
          The Damköhler number compares <strong>how long mixing takes</strong> with <strong>how long the reaction takes</strong>:{" "}
          <strong>Da = mixing time / reaction time</strong>. When <strong>Da &lt; 1</strong>, mixing is faster than the reaction and
          is less likely to limit the result. When <strong>Da &gt; 1</strong>, the reaction can proceed before the vessel is fully
          mixed, so mixing may affect conversion, selectivity, or temperature.
        </p>
        <p>
          As vessels get larger, bulk mixing usually takes longer. For geometrically similar reactors scaled at{" "}
          <strong>constant power per unit volume (P/V)</strong>, the blend time increases roughly with vessel diameter as{" "}
          <strong>T^(2/3)</strong>. A larger reactor therefore needs a scale-up check even when the small vessel mixed well.
          Micromixing is controlled by local turbulence near the impeller and feed point, while macromixing describes the time
          needed to homogenize the whole vessel.
        </p>
        <p>
          The estimates below compare micromixing time <strong>t<sub>E</sub> ≈ 17.3·√(ν/ε)</strong> and bulk blend time{" "}
          <strong>
            θ<sub>95</sub> = 5.2·T^1.5·H^0.5/(N<sub>p</sub>^(1/3)·N·D²)
          </strong>{" "}
          with the reaction time. Without a vessel, the screen uses fixed reaction-time bands; select a vessel to compute the actual{" "}
          <strong>
            Da<sub>macro</sub>
          </strong>{" "}
          and{" "}
          <strong>
            Da<sub>micro</sub>
          </strong>{" "}
          for a chosen operating point.
        </p>
        <Switch label="Compute Damköhler numbers for a vessel" checked={inputs.daOn} onChange={(daOn) => set({ daOn })} />
        {inputs.daOn && (
          <div className="form-row">
            <SelectField label="Vessel" value={inputs.daReactor} options={options.data?.reactors ?? []} onChange={(v) => report(loadVessel(v))} />
            <NumberField label="Agitation speed N (RPM)" value={inputs.daRpm} onChange={(daRpm) => set({ daRpm })} />
            <NumberField label="Working volume (L)" value={inputs.daVl} onChange={(daVl) => set({ daVl })} />
          </div>
        )}
        {res && step(5) && (
          <ResultBox tone={stepTone(5)}>
            {res.trxn_caption && <Markdown>{res.trxn_caption}</Markdown>}
            {res.da_caption && <Markdown>{res.da_caption}</Markdown>}
            {step(5)}
          </ResultBox>
        )}
      </Card>

      {!started && (
        <Card title="Ready?">
          <p>Once you&apos;ve worked through the steps above, start the assessment to generate the per-step findings and the overall verdict.</p>
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

      <Card title="Step 6 - Summary & Recommendations">
        {stale && <p className="stale-note">Updating…</p>}
        <Markdown>{res ? res.summary_note : SUMMARY_PRE_START}</Markdown>
        {res?.ready && (
          <SummaryDashboard res={res} bourne={inputs.bourneFindings} />
        )}
      </Card>

      {res?.ready && (
        <Card title="Step 7 - Export Report">
          <p>Generate a PDF capturing the inputs, findings, overall verdict, and next steps.</p>
          <button type="button" className="primary" disabled={pdf.isPending || stale} onClick={() => pdf.mutate()}>
            Download PDF report
          </button>
        </Card>
      )}
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
