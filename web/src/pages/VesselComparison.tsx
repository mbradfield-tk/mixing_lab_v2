import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, postForFile, unwrap, type Schemas } from "../api/client";
import type { Row } from "../api/tables";
import { Chart } from "../components/Chart";
import { Segmented, SelectField, Switch } from "../components/Form";
import { InstrumentPanel, Setpoint } from "../components/Instrument";
import { MultiSelect } from "../components/MultiSelect";
import { NoticeBar, useNotice } from "../components/Notice";
import { PropertyTable } from "../components/PropertyTable";
import { ResultTable } from "../components/ResultTable";
import { Card, ErrorNote, MenuIcon, PageLink, PageTitle } from "../components/ui";
import { VesselViewer, type VesselMedia } from "../components/VesselViewer";
import { downloadBlob } from "./assessment/model";
import { COALESCENCE, DEFAULT_VESSELS, INITIAL, buildRequests, kineticsCaption, type Inputs, type PageRequest } from "./comparison/model";

type Tables = Schemas["ComparisonTables"];

const num = (v: unknown, fallback: number) => {
  const x = v === null || v === undefined || v === "" ? Number.NaN : Number(v);
  return Number.isFinite(x) ? x : fallback;
};

function VesselTile({ name }: { name: string }) {
  const media = useQuery({
    queryKey: ["vessel-media", name],
    queryFn: async () => {
      const res = await api.GET("/api/v1/media/vessels/{name}", { params: { path: { name } } });
      if (res.response.status === 404) return null;
      return unwrap(res) as unknown as VesselMedia;
    },
  });
  return (
    <figure className="vessel-tile">
      {media.data ? (
        <VesselViewer media={media.data} name={name} />
      ) : media.isSuccess ? (
        <p className="muted placeholder">No image or 3D model.</p>
      ) : null}
      <figcaption>{name}</figcaption>
    </figure>
  );
}

/** Two-column editable table: one number per vessel. */
function PerVesselInputs({
  title,
  vessels,
  values,
  onChange,
}: {
  title: string;
  vessels: string[];
  values: Record<string, string>;
  onChange: (values: Record<string, string>) => void;
}) {
  return (
    <table className="narrow-table">
      <thead>
        <tr>
          <th>Reactor</th>
          <th>{title}</th>
        </tr>
      </thead>
      <tbody>
        {vessels.map((v) => (
          <tr key={v}>
            <td>{v}</td>
            <td>
              <input
                type="number"
                step="any"
                aria-label={`${title} for ${v}`}
                value={values[v] ?? ""}
                onChange={(e) => onChange({ ...values, [v]: e.target.value })}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const md = (text: string) => <ReactMarkdown>{text}</ReactMarkdown>;

export function VesselComparison() {
  const { notice, setNotice, run } = useNotice();
  const [inputs, setInputs] = useState<Inputs>(INITIAL);
  const set = (patch: Partial<Inputs>) => setInputs((i) => ({ ...i, ...patch }));

  const options = useQuery({ queryKey: ["options"], queryFn: async () => unwrap(await api.GET("/api/v1/options")) });
  const enums = options.data?.enums ?? {};
  const reactionList =
    (inputs.reactionSource === "classes" ? options.data?.reaction_classes : options.data?.reactions_measured) ?? [];

  // --- setup for the current selection (correlation sources, feed pipes, scale-up defaults) ---
  const setup = useQuery({
    queryKey: ["comparison-setup", inputs.reactors, inputs.basis, inputs.solveFor],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/comparison/setup", {
          body: { reactors: inputs.reactors, basis_reactor: inputs.basis, solve_for: inputs.solveFor },
        }),
      ),
    enabled: inputs.reactors.length > 0,
    placeholderData: keepPreviousData,
  });
  const applied = useRef({ reactors: "", basis: "", targets: "" });
  useEffect(() => {
    const d = setup.data;
    if (!d) return;
    const reactorsKey = inputs.reactors.join("|");
    const targetsKey = `${reactorsKey}#${d.basis_reactor}#${inputs.solveFor}`;
    if (!Object.keys(d.fixed).every((r) => inputs.reactors.includes(r))) return; // stale placeholder
    const newReactors = applied.current.reactors !== reactorsKey;
    const newBasis = applied.current.basis !== d.basis_reactor;
    const newTargets = applied.current.targets !== targetsKey;
    applied.current = { reactors: reactorsKey, basis: d.basis_reactor, targets: targetsKey };
    setInputs((i) => {
      const next = { ...i };
      if (!d.corr_sources.some((c) => c.code === i.corr)) next.corr = d.corr_sources[0]?.code ?? "Literature";
      if (newReactors) {
        next.feedPipe = Object.fromEntries(Object.entries(d.feed_pipe_mm).map(([k, v]) => [k, String(v)]));
        if (!i.reactors.includes(i.feedBasis)) next.feedBasis = i.reactors[0] ?? "";
      }
      if (newBasis) {
        next.basis = d.basis_reactor;
        next.basisRpm = String(d.basis_N_rpm);
        next.basisVol = String(d.basis_V_L);
      }
      if (newTargets) next.targets = Object.fromEntries(Object.entries(d.fixed).map(([k, v]) => [k, String(v)]));
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setup.data]);

  // --- loaders ------------------------------------------------------------
  async function loadReaction(name: string) {
    if (!name) return;
    const kd = unwrap(await api.GET("/api/v1/kinetics/defaults", { params: { query: { reaction: name } } }));
    setInputs((i) => ({
      ...i,
      reaction: name,
      order: kd.order,
      k: String(kd.k),
      c0: String(kd.C0_mol_L),
      trxn: String(kd.t_rxn_s),
      dH: String(kd.dH_kJ_mol),
      ...(kd.fluid ? { fluid: kd.fluid, ...(kd.T_C > 0 ? { T: String(kd.T_C) } : {}) } : {}),
    }));
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

  const initialised = useRef(false);
  useEffect(() => {
    const o = options.data;
    if (!o || initialised.current) return;
    initialised.current = true;
    const picked = DEFAULT_VESSELS.filter((v) => o.reactors.includes(v));
    const reactors = picked.length ? picked : o.reactors.slice(0, 3);
    const reaction = (o.reactions_measured.length ? o.reactions_measured : o.reaction_classes)[0] ?? "";
    set({
      reactors,
      fluid: o.fluids.includes("Water") ? "Water" : (o.fluids[0] ?? ""),
      feedBasis: reactors[0] ?? "",
      basis: reactors[0] ?? "",
    });
    // The Taipy page seeds the kinetics but keeps the default fluid on first load.
    report(
      api.GET("/api/v1/kinetics/defaults", { params: { query: { reaction } } }).then((res) => {
        const kd = unwrap(res);
        set({ reaction, order: kd.order, k: String(kd.k), c0: String(kd.C0_mol_L), trxn: String(kd.t_rxn_s), dH: String(kd.dH_kJ_mol) });
      }),
    );
    report(loadParticle(o.particles[0] ?? ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.data]);

  // --- compute --------------------------------------------------------------
  const built = useMemo(() => buildRequests(inputs), [inputs]);
  const currentKey = "page" in built ? JSON.stringify(built.page) : null;
  const [last, setLast] = useState<{ key: string; page: PageRequest; tables: Tables } | null>(null);
  const stale = !!last && currentKey !== last.key;

  const compute = useMutation({
    mutationFn: async (page: PageRequest) => unwrap(await api.POST("/api/v1/comparison/tables", { body: page })),
  });

  function onCompute() {
    if ("error" in built) {
      setNotice({ kind: "error", text: built.error });
      return;
    }
    const page = built.page;
    compute
      .mutateAsync(page)
      .then((tables) => {
        setLast({ key: JSON.stringify(page), page, tables });
        setNotice(
          tables.feed_ok
            ? { kind: "success", text: "Comparison computed." }
            : { kind: "error", text: tables.feed_warning || tables.status },
        );
      })
      .catch((e: Error) => setNotice({ kind: "error", text: e.message }));
  }

  const t = last?.tables;
  const ready = !!t && t.feed_ok;

  const [envParams, setEnvParams] = useState<string[] | null>(null);
  const available = t?.parameters ?? [];
  const envSelected = (envParams ?? available.filter((p) => p.default).map((p) => p.field)).filter((f) =>
    available.some((p) => p.field === f),
  );
  const labelOf = new Map(available.map((p) => [p.field, p.label]));
  const envelope = useQuery({
    queryKey: ["chart", "comparison-envelope", last?.key, envSelected.join("|")],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/charts/{kind}", {
          params: { path: { kind: "comparison-envelope" } },
          body: { comparison: last!.page.comparison, parameters: envSelected },
        }),
      ),
    enabled: ready && envSelected.length > 0,
    placeholderData: keepPreviousData,
  });

  const scaleLabel = setup.data?.scalable.find((p) => p.field === last?.page.scale_up?.parameter)?.label ?? "";
  const pdf = useMutation({
    mutationFn: () =>
      postForFile("/api/v1/reports/comparison", {
        ...last!.page.comparison,
        scale_param: last!.page.scale_up ? scaleLabel : "",
        scale_basis_reactor: last!.page.scale_up?.basis_reactor ?? "",
      }),
  });
  const save = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/comparison/save", { body: last!.page.comparison })),
  });

  const caption = kineticsCaption(inputs.order, num(inputs.k, 0), num(inputs.c0, 0), num(inputs.trxn, 0), num(inputs.dH, 0));
  const vessels = inputs.reactors;

  return (
    <>
      <PageTitle pageKey="Vessel_Comparison">Vessel Comparison</PageTitle>
      <p>
        Compare the mixing performance of several vessels side-by-side. Each vessel's operating envelope is mapped
        from its RPM range and fill-volume band for a shared fluid and reaction system.
      </p>
      <p>{t ? t.status : "Select vessels and conditions, then Compute comparison."}</p>
      {options.isError && <ErrorNote error={options.error} />}

      <Card title="1. Reactors & Conditions">
        <MultiSelect
          label="Vessels to compare"
          options={options.data?.reactors ?? []}
          value={vessels}
          onChange={(reactors) =>
            set({ reactors, ...(reactors.includes(inputs.basis) ? {} : { basis: reactors[0] ?? "" }) })
          }
          placeholder="Select vessels"
        />
        <div className="form-row">
          <SelectField label="Correlation source" value={inputs.corr} options={setup.data?.corr_sources ?? []} onChange={(corr) => set({ corr })} />
          <p className="muted">{setup.data?.corr_status}</p>
        </div>
        <div className="form-row">
          <SelectField label="Fluid" value={inputs.fluid} options={options.data?.fluids ?? []} onChange={(fluid) => set({ fluid })} />
        </div>
        <InstrumentPanel title="Operating point">
          <Setpoint label="Temperature" value={inputs.T} onChange={(T) => set({ T })} unit="°C" />
          <Setpoint label="Pressure" value={inputs.P} onChange={(P) => set({ P })} unit="atm" step={0.1} min={0} />
          <Setpoint label="Coolant temp" value={inputs.Tcool} onChange={(Tcool) => set({ Tcool })} unit="°C" />
        </InstrumentPanel>
        <p className="muted">Reaction kinetics are auto-filled from the database; edit any value to override.</p>
        <div className="grid-2 prop-grid">
          <PropertyTable
            groups={[
              {
                title: "Reaction (for Da numbers)",
                rows: [
                  {
                    label: "Source",
                    value: inputs.reactionSource,
                    options: [
                      { code: "measured", label: "Measured kinetics" },
                      { code: "classes", label: "Reaction classes" },
                    ],
                    onChange: (v) => {
                      const source = v as Inputs["reactionSource"];
                      const list = (source === "classes" ? options.data?.reaction_classes : options.data?.reactions_measured) ?? [];
                      set({ reactionSource: source });
                      const next = list.includes(inputs.reaction) ? inputs.reaction : list[0];
                      if (next) report(loadReaction(next));
                    },
                  },
                  { label: "Reaction", value: inputs.reaction, options: reactionList, onChange: (v) => report(loadReaction(v)) },
                  {
                    label: "Order",
                    value: inputs.order,
                    options: ["0", "1", "2", "pseudo-1", "pseudo-2"],
                    onChange: (order) => set({ order: order as Inputs["order"] }),
                  },
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
                  { label: "Initial concentration C₀", unit: "mol/L", value: inputs.c0, onChange: (c0) => set({ c0 }) },
                  { label: "Reaction time t_rxn", unit: "s (0 = from k)", value: inputs.trxn, onChange: (trxn) => set({ trxn }) },
                  { label: "Heat of reaction ΔH", unit: "kJ/mol", value: inputs.dH, onChange: (dH) => set({ dH }) },
                ],
              },
            ]}
          />
        </div>
        {md(caption)}
      </Card>

      <Card title="Selected Vessels">
        <p className="muted">Drag to rotate a 3D model; scroll to zoom. The row scrolls sideways when several vessels are selected.</p>
        <div className="vessel-row">
          {vessels.map((v) => (
            <VesselTile key={v} name={v} />
          ))}
        </div>
      </Card>

      <Card title="2. Options">
        <div className="phase-grid">
          <section className="phase-panel">
            <h3>
              <MenuIcon pageKey="Particle_Database" /> Solid particles
            </h3>
            <Switch label="Include solid particles" checked={inputs.solids} onChange={(solids) => set({ solids })} />
            {inputs.solids ? (
              <>
                <SelectField label="Particle" value={inputs.particle} options={options.data?.particles ?? []} onChange={(v) => report(loadParticle(v))} />
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
                Enable to check off-bottom suspension in each vessel. Particle properties are shared across all compared vessels.
              </p>
            )}
          </section>

          <section className="phase-panel">
            <h3>🫧 Gas</h3>
            <Switch label="Include gas phase" checked={inputs.gas} onChange={(gas) => set({ gas })} />
            {inputs.gas ? (
              <>
                <Segmented label="Mass-transfer mode" value={inputs.gasTransfer} options={enums.GasTransfer ?? []} onChange={(gasTransfer) => set({ gasTransfer })} />
                {inputs.gasTransfer === "sparging" && (
                  <PropertyTable
                    groups={[
                      {
                        title: "Sparging",
                        rows: [
                          { label: "Superficial gas velocity v_s", unit: "m/s", value: inputs.vs, onChange: (vs) => set({ vs }) },
                          {
                            label: "Liquid type (for kLa)",
                            value: inputs.coalescing,
                            options: COALESCENCE,
                            onChange: (coalescing) => set({ coalescing }),
                          },
                        ],
                      },
                    ]}
                  />
                )}
              </>
            ) : (
              <p className="muted">Enable to include gas–liquid mass transfer (headspace or sparged) in each vessel.</p>
            )}
          </section>

          <section className="phase-panel">
            <h3>🔁 Fed-batch</h3>
            <Switch label="Fed-batch addition" checked={inputs.fed} onChange={(fed) => set({ fed })} />
            {inputs.fed ? (
              <>
                <p>
                  <strong>Feed schedule</strong> — feed volume is set at the basis vessel and scaled to the others by V_L_max.
                </p>
                <PropertyTable
                  groups={[
                    {
                      title: "Feed",
                      rows: [
                        {
                          label: "Feed location",
                          value: inputs.feedLocation,
                          options: enums.FeedLocation ?? [],
                          onChange: (feedLocation) => set({ feedLocation }),
                        },
                        { label: "Basis vessel", value: inputs.feedBasis, options: vessels, onChange: (feedBasis) => set({ feedBasis }) },
                        { label: "Feed volume", unit: "mL", value: inputs.feedVolume, onChange: (feedVolume) => set({ feedVolume }) },
                        { label: "Feed time", unit: "h", value: inputs.feedTime, onChange: (feedTime) => set({ feedTime }) },
                      ],
                    },
                  ]}
                />
                <p>
                  <strong>Feed pipe diameter per vessel</strong> — defaults from each reactor's recorded feed-pipe ID; edit to override.
                </p>
                <PerVesselInputs title="Feed pipe ID (mm)" vessels={vessels} values={inputs.feedPipe} onChange={(feedPipe) => set({ feedPipe })} />
              </>
            ) : (
              <p className="muted">Enable to add the mesomixing Damköhler number (Da_meso), evaluated at the feed point.</p>
            )}
          </section>
        </div>
      </Card>

      <Card title="3. Scale-Up Matching">
        <p>
          Hold one parameter constant on a <strong>basis</strong> vessel and solve for the equivalent operating point on every
          other selected vessel.
        </p>
        <Switch label="Perform scale-up matching" checked={inputs.scaling} onChange={(scaling) => set({ scaling })} />
        {inputs.scaling && (
          <>
            <div className="prop-narrow">
              <PropertyTable
                groups={[
                  {
                    title: "Basis",
                    rows: [
                      { label: "Basis vessel", value: inputs.basis, options: vessels, onChange: (basis) => set({ basis }) },
                      {
                        label: "Parameter to hold constant",
                        value: inputs.scaleParam,
                        options: (setup.data?.scalable ?? []).map((p) => ({ code: p.field, label: p.label })),
                        onChange: (scaleParam) => set({ scaleParam }),
                      },
                      { label: "Basis stir speed", unit: "RPM", value: inputs.basisRpm, onChange: (basisRpm) => set({ basisRpm }) },
                      { label: "Basis volume", unit: "L", value: inputs.basisVol, onChange: (basisVol) => set({ basisVol }) },
                    ],
                  },
                  {
                    title: "Target vessels",
                    rows: [
                      {
                        label: "Solve for",
                        value: inputs.solveFor,
                        options: [
                          { code: "N_rpm", label: "RPM (specify volume)" },
                          { code: "V_L", label: "Volume (specify RPM)" },
                        ],
                        onChange: (v) => set({ solveFor: v as Inputs["solveFor"] }),
                      },
                    ],
                  },
                ]}
              />
            </div>
            <p>
              <strong>Target vessel known values</strong>
            </p>
            <PerVesselInputs
              title={inputs.solveFor === "N_rpm" ? "Fill volume (L)" : "Stir speed (RPM)"}
              vessels={vessels.filter((v) => v !== inputs.basis)}
              values={inputs.targets}
              onChange={(targets) => set({ targets })}
            />
          </>
        )}
      </Card>

      <button type="button" className={`compute-btn ${!ready || stale ? "primary" : "done"}`} disabled={compute.isPending} onClick={onCompute}>
        {compute.isPending ? "Computing…" : "Compute comparison"}
      </button>
      {stale && (
        <p className="stale-note">
          ⚠️ Inputs changed since the last run — click <em>Compute comparison</em> to refresh.
        </p>
      )}

      {t && !t.feed_ok && t.feed_plan.length > 0 && (
        <Card title="Fed-Batch Feed Plan">
          <p className="error-note">{t.feed_warning || t.status}</p>
          <ResultTable rows={t.feed_plan} />
        </Card>
      )}

      {ready && t && last && (
        <>
          <Card title="Operating Envelope Summary">
            <p>Each row shows the range across the 4 corner conditions (min/max RPM × min/max volume).</p>
            <ResultTable rows={t.summary} csvName="vessel_comparison_summary.csv" stale={stale} />
            <details>
              <summary>Full 4-corner detail</summary>
              <ResultTable rows={t.detail} csvName="vessel_comparison_detail.csv" stale={stale} />
            </details>
          </Card>

          <Card title="Stir Speed Reference">
            <p>Translates a percentage of each vessel's maximum RPM (the chart x-axis) to actual RPM.</p>
            <ResultTable rows={t.rpm_ref} csvName="vessel_comparison_stir_speed.csv" stale={stale} />
          </Card>

          <Card title="Operating Envelope Charts">
            <p className="muted">
              Each vessel&apos;s reachable region across its speed range (% of max). Solid: max fill; dotted: min fill; dashed (Da
              panels): 0.1 and 1 thresholds.
            </p>
            <MultiSelect
              label="Parameters to plot"
              options={available.map((p) => p.label)}
              value={envSelected.map((f) => labelOf.get(f) ?? f)}
              onChange={(labels) => setEnvParams(available.filter((p) => labels.includes(p.label)).map((p) => p.field))}
              placeholder="Select parameters"
            />
            {envelope.isError && <ErrorNote error={envelope.error} />}
            <Chart figure={envelope.data?.figures.envelope} />
          </Card>

          {t.heat.length > 0 && (
            <Card title="Heat Balance Summary">
              <p>Evaluated at each vessel's max-RPM / max-volume corner.</p>
              <ResultTable rows={t.heat} csvName="vessel_comparison_heat_balance.csv" stale={stale} />
            </Card>
          )}

          {t.scale.length > 0 && (
            <Card title="Scale-Up Matching Results">
              <p>Conditions in each vessel that match the chosen parameter of the basis vessel.</p>
              <ResultTable rows={t.scale} csvName="vessel_comparison_matching.csv" stale={stale} />
              {t.scale_full.length > 0 && (
                <details>
                  <summary>Full parameter comparison at matched conditions</summary>
                  <ResultTable rows={t.scale_full} csvName="vessel_comparison_matched_parameters.csv" stale={stale} />
                </details>
              )}
              {t.scale_pct.length > 0 && (
                <details>
                  <summary>Percentage difference vs. basis vessel</summary>
                  <ResultTable rows={t.scale_pct} csvName="vessel_comparison_scale_up_differences.csv" stale={stale} />
                </details>
              )}
            </Card>
          )}

          {t.impact.length > 0 && (
            <Card title="Scale-Up Impact Summary">
              <p>Ratios to the first vessel, using each parameter&apos;s midpoint (average of the 4 corners).</p>
              <ResultTable rows={t.impact} csvName="vessel_comparison_impact.csv" stale={stale} />
            </Card>
          )}

          {t.feed_plan.length > 0 && (
            <Card title="Fed-Batch Feed Plan">
              <p>
                Feed volume scales with each vessel&apos;s max fill; feed time is shared. Flagged rows exceed the vessel&apos;s
                max fill.
              </p>
              <ResultTable rows={t.feed_plan} csvName="vessel_comparison_feed_plan.csv" stale={stale} />
            </Card>
          )}

          <Card title="Export & Save">
            <p>
              Download a PDF of the comparison, or save each vessel's max-RPM / max-volume corner to the{" "}
              <PageLink pageKey="Recorded_Results" /> page.
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
                  void run(save.mutateAsync(), (r) => `Saved ${r.saved} vessel result(s) — view them on the Recorded Results page.`).catch(
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

      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
