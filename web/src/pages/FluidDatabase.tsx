import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api, unwrap, type Schemas } from "../api/client";
import { useTable, type Column, type Row } from "../api/tables";
import { AdminPanel } from "../components/Admin";
import { Chart } from "../components/Chart";
import { AddForm, DatabaseTable, ImportExport, type Field } from "../components/Database";
import { DataTable } from "../components/DataTable";
import { NoticeBar, useNotice, type Notice } from "../components/Notice";
import { Card, ErrorNote, PageTitle } from "../components/ui";
import { formatE, formatF, formatG } from "../format";

const TABS = [
  ["library", "Solvent Library"],
  ["properties", "Solvent Properties"],
  ["custom", "Custom Fluids"],
  ["blend", "Blend"],
  ["io", "Import / Export"],
] as const;
type Tab = (typeof TABS)[number][0];

const FIELDS: Field[] = [
  { key: "fluid_name", label: "Fluid name *", initial: "" },
  { key: "rho_kg_m3", label: "Density ρ (kg/m³)", type: "number", initial: 997 },
  { key: "mu_Pa_s", label: "Viscosity μ (Pa·s)", type: "number", initial: 0.00089 },
  { key: "D_mol_m2_s", label: "Diffusivity D (m²/s)", type: "number", initial: 2.3e-9 },
  { key: "surface_tension_N_m", label: "Surface tension σ (N/m)", type: "number", initial: 0.072 },
  { key: "Cp_J_per_kgK", label: "Specific heat Cp (J/kg·K)", type: "number", initial: 4182 },
  { key: "k_W_per_mK", label: "Thermal conductivity k (W/m·K)", type: "number", initial: 0.607 },
  { key: "notes", label: "Notes", initial: "" },
  { key: "hsp_d", label: "HSP δd dispersion (MPa½, 0 = unknown)", type: "number", initial: 0 },
  { key: "hsp_p", label: "HSP δp polar (MPa½)", type: "number", initial: 0 },
  { key: "hsp_h", label: "HSP δh H-bonding (MPa½)", type: "number", initial: 0 },
];

const columnsOf = (rows: Row[]): Column[] =>
  Object.keys(rows[0] ?? {}).map((k) => ({ column: k, label: k }));

function useLibrary() {
  return useQuery({
    queryKey: ["fluids", "library"],
    queryFn: async () => unwrap(await api.GET("/api/v1/fluids/library")) as unknown as Row[],
    staleTime: Infinity,
  });
}

function LibraryTab() {
  const library = useLibrary();
  const custom = useTable("fluids/custom");
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const all = library.data ?? [];
    const needle = q.trim().toLowerCase();
    return needle
      ? all.filter((r) => Object.values(r).some((v) => String(v ?? "").toLowerCase().includes(needle)))
      : all;
  }, [library.data, q]);

  return (
    <>
      <Card title="Solvent Library">
        <p>
          Reference table of all built-in solvents with <strong>properties at 25 °C and 1 atm</strong>.
          These are always available in the assessment tools — pick one and set any temperature to
          get properties from literature correlations.
        </p>
        <label className="search">
          Search solvents
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        {library.isError && <ErrorNote error={library.error} />}
        <DataTable rows={rows} columns={columnsOf(library.data ?? [])} nameKey="Solvent" pageSize={15} />
      </Card>
      <Card title="Custom Fluids">
        <p>Manually added fluids with fixed (temperature-independent) properties.</p>
        <DataTable
          rows={custom.list.data?.records ?? []}
          columns={custom.columns.data ?? []}
          nameKey="fluid_name"
          pageSize={10}
        />
      </Card>
    </>
  );
}

const PROPERTY_ROWS: [string, string, string, (v: unknown) => string][] = [
  ["Density ρ", "rho_kg_m3", "kg/m³", (v) => formatF(v, 2)],
  ["Viscosity μ", "mu_Pa_s", "Pa·s", (v) => formatF(v, 6)],
  ["Surface tension σ", "surface_tension_N_m", "N/m", (v) => formatF(v, 4)],
  ["Diffusivity D", "D_mol_m2_s", "m²/s", (v) => formatE(v, 3)],
  ["Specific heat Cp", "Cp_J_per_kgK", "J/kg·K", (v) => formatF(v, 1)],
  ["Thermal conductivity k", "k_W_per_mK", "W/m·K", (v) => formatF(v, 4)],
  ["Vapour pressure", "vapor_pressure_atm", "atm", (v) => formatF(v, 4)],
  ["b.p. at P", "bp_at_P_C", "°C", (v) => formatF(v, 1)],
  ["Normal b.p.", "bp_C", "°C", (v) => formatF(v, 1)],
  ["m.p.", "mp_C", "°C", (v) => formatF(v, 1)],
  ["MW", "mw", "g/mol", (v) => formatF(v, 2)],
  ["CAS", "cas", "–", (v) => String(v ?? "—")],
];

function PropertiesTab() {
  const library = useLibrary();
  const names = (library.data ?? []).map((r) => String(r.Solvent));
  const [solvent, setSolvent] = useState("Water");
  const [P, setP] = useState("1");
  const [T, setT] = useState("25");
  const body = { name: solvent, P_atm: Number(P), T_C: Number(T) };
  const ready = Number.isFinite(body.T_C) && Number.isFinite(body.P_atm) && body.P_atm > 0 && T !== "" && P !== "";

  const state = useQuery({
    queryKey: ["fluids", "state", body],
    queryFn: async () => unwrap(await api.POST("/api/v1/fluids/solvent-state", { body })) as Row,
    enabled: ready,
    placeholderData: keepPreviousData,
  });
  const chart = useQuery({
    queryKey: ["charts", "solvent-properties", body],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/charts/{kind}", {
          params: { path: { kind: "solvent-properties" } },
          body,
        }),
      ),
    enabled: ready,
    placeholderData: keepPreviousData,
  });

  const s = state.data;
  const range = s?.liquid_range_C as [number, number] | undefined;
  const lo = formatF(range?.[0], 0);
  const hi = formatF(s?.bp_at_P_C, 0);

  return (
    <Card title="Solvent Properties at Temperature">
      <p>
        Compute physical properties for a built-in solvent at any liquid-phase temperature and
        pressure. The Antoine equation adjusts the boiling point for non-atmospheric pressure.
      </p>
      <div className="form-row">
        <label>
          Solvent
          <select value={solvent} onChange={(e) => setSolvent(e.target.value)}>
            {names.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label>
          Pressure (atm)
          <input type="number" step="any" min="0" value={P} onChange={(e) => setP(e.target.value)} />
        </label>
        <label>
          Temperature (°C)
          <input type="number" step="any" value={T} onChange={(e) => setT(e.target.value)} />
        </label>
      </div>
      {!ready && <p className="error-note">Enter a temperature and a pressure above 0 atm.</p>}
      {state.isError && <ErrorNote error={state.error} />}
      {s && (
        <p>
          {s.in_range
            ? `Liquid range at ${formatF(s.P_atm, 3)} atm: ${lo} – ${hi} °C.`
            : `⚠️ ${formatF(s.T_C, 1)} °C is outside the liquid range (${lo} – ${hi} °C) — values are extrapolated.`}
        </p>
      )}
      {s && (
        <table className="results">
          <thead>
            <tr>
              <th>Property</th>
              <th>Value</th>
              <th>Units</th>
            </tr>
          </thead>
          <tbody>
            {PROPERTY_ROWS.map(([label, key, unit, fmt]) => (
              <tr key={key}>
                <td>{label}</td>
                <td className="num">{fmt(s[key])}</td>
                <td>{unit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {chart.isError && <ErrorNote error={chart.error} />}
      <Chart figure={chart.data?.figures.properties} height={780} />
    </Card>
  );
}

function CustomTab({ run }: { run: ReturnType<typeof useNotice>["run"] }) {
  return (
    <>
      <Card title="Custom Fluids">
        <p>
          Add or edit <strong>custom fluids</strong> not in the built-in solvent library (mixtures,
          slurries, concentrated acids). Custom fluids have fixed properties. Unlock the{" "}
          <strong>Admin</strong> panel (bottom of the page) to edit;{" "}
          <strong>every table edit is saved automatically.</strong>
        </p>
        <DatabaseTable table="fluids/custom" nameKey="fluid_name" run={run} searchLabel="Search custom fluids" />
      </Card>
      <Card title="Add Custom Fluid">
        <p className="muted">
          Hansen solubility parameters are optional (used for miscibility screening; 0 = unknown).
        </p>
        <AddForm
          table="fluids/custom"
          fields={FIELDS}
          nameKey="fluid_name"
          noun="custom fluid"
          run={run}
          submitLabel="Add fluid"
        />
      </Card>
    </>
  );
}

type BlendResult = Schemas["BlendResult"];
type BlendRequest = Schemas["BlendRequest"];

function joinPairs(pairs: string[], limit = 3): string {
  return pairs.length <= limit
    ? pairs.join("; ")
    : `${pairs.slice(0, limit).join("; ")}; +${pairs.length - limit} more`;
}

/** The Taipy page's status line for a blend result. */
export function blendStatus(res: BlendResult): Notice {
  const of = (cls: string) => res.pairs.filter((p) => p.classification === cls).map((p) => p.label);
  const rho = formatF(res.blend.rho_kg_m3, 1);
  const mu = formatF(res.blend.mu_Pa_s, 6);
  switch (res.status) {
    case "reactive":
      return {
        kind: "error",
        text: `⚠️ Reacts chemically on mixing (${joinPairs(of("reactive"))}) — this is not a physical blend; averaged properties do not apply.`,
      };
    case "immiscible":
      return {
        kind: "error",
        text: `⚠️ Immiscible / partially miscible (${joinPairs(of("immiscible"))}) — the blend may split into phases; averaged properties may not apply.`,
      };
    case "unknown":
      return {
        kind: "info",
        text: `❔ Miscibility unknown — no HSP data for ${joinPairs(of("unknown"))}. If single-phase: ρ = ${rho} kg/m³, μ = ${mu} Pa·s.`,
      };
    default:
      return { kind: "success", text: `🟢 Single-phase blend: ρ = ${rho} kg/m³, μ = ${mu} Pa·s.` };
  }
}

/** Kinematic viscosity ν = μ/ρ in mm²/s (cSt); NaN when either property is missing. */
export function kinematicViscosity(r: Row): number {
  const mu = Number(r.mu_Pa_s);
  const rho = Number(r.rho_kg_m3);
  return mu > 0 && rho > 0 ? (mu / rho) * 1e6 : Number.NaN;
}

function propertyCells(r: Row) {
  const nu = kinematicViscosity(r);
  return [
    formatF(r.rho_kg_m3, 1),
    formatF(r.mu_Pa_s, 6),
    Number.isFinite(nu) ? formatG(nu, 4) : "—",
    formatF(r.surface_tension_N_m, 4),
    formatE(r.D_mol_m2_s, 3),
    formatF(r.Cp_J_per_kgK, 1),
    formatF(r.k_W_per_mK, 4),
  ];
}

function BlendTab() {
  const library = useLibrary();
  const custom = useTable("fluids/custom");
  const available = [
    ...(library.data ?? []).map((r) => String(r.Solvent)),
    ...(custom.list.data?.records ?? []).map((r) => String(r.fluid_name)),
  ];
  const [components, setComponents] = useState<{ name: string; amount: string }[]>([]);
  const [pick, setPick] = useState("");
  const [basis, setBasis] = useState<"volume" | "mass">("volume");
  const [inputs, setInputs] = useState({ T: "25", speed: "5", D: "0.05", H: "1", sigma: "0.01" });

  const compute = useMutation({
    mutationFn: async (body: BlendRequest) => {
      const [result, chart] = await Promise.all([
        api.POST("/api/v1/fluids/blend", { body }).then(unwrap),
        api
          .POST("/api/v1/charts/{kind}", { params: { path: { kind: "blend-phases" } }, body })
          .then(unwrap),
      ]);
      return { result, figure: chart.figures.phases };
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    compute.mutate({
      components: components.map((c) => ({ name: c.name, amount: Number(c.amount) })),
      basis,
      T_C: Number(inputs.T),
      dispersion_speed_1_s: Number(inputs.speed),
      dispersion_D_imp_m: Number(inputs.D),
      dispersion_H_m: Number(inputs.H),
      interfacial_tension_N_m: Number(inputs.sigma),
    });
  }

  const numberInput = (key: keyof typeof inputs, label: string) => (
    <label>
      {label}
      <input
        type="number"
        step="any"
        value={inputs[key]}
        onChange={(e) => setInputs({ ...inputs, [key]: e.target.value })}
      />
    </label>
  );

  const res = compute.data?.result;
  const status = res ? blendStatus(res) : null;
  const choices = available.filter((n) => !components.some((c) => c.name === n));

  return (
    <>
      <Card title="Blend Fluids">
        <p>
          Create a blend from solvents and/or custom fluids. Enter proportions on a{" "}
          <strong>volume</strong> or <strong>mass</strong> basis; properties are combined with
          literature mixing rules (log-mixing viscosity, volume-additive density, etc.).
        </p>
        <form onSubmit={submit}>
          <div className="form-row">
            <label>
              Add component
              <select
                value={pick}
                onChange={(e) => {
                  if (e.target.value) setComponents([...components, { name: e.target.value, amount: "1" }]);
                  setPick("");
                }}
              >
                <option value="">— select a fluid —</option>
                {choices.map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
            <label>
              Input basis
              <select value={basis} onChange={(e) => setBasis(e.target.value as "volume" | "mass")}>
                <option value="volume">Volume</option>
                <option value="mass">Mass</option>
              </select>
            </label>
            {numberInput("T", "Temperature (°C)")}
          </div>

          <h3>Component amounts</h3>
          {components.length ? (
            <table className="narrow-table">
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Amount ({basis === "volume" ? "volume" : "mass"} parts)</th>
                  <th aria-label="Remove" />
                </tr>
              </thead>
              <tbody>
                {components.map((c, i) => (
                  <tr key={c.name}>
                    <td>{c.name}</td>
                    <td>
                      <input
                        type="number"
                        step="any"
                        min="0"
                        aria-label={`Amount of ${c.name}`}
                        value={c.amount}
                        onChange={(e) =>
                          setComponents(components.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))
                        }
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="icon-btn"
                        aria-label={`Remove ${c.name}`}
                        onClick={() => setComponents(components.filter((_, j) => j !== i))}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">Select two or more components, enter amounts, then compute.</p>
          )}

          <h3>Liquid-liquid dispersion screen</h3>
          <p>
            For immiscible pairs, estimate dispersion stability using the entered operating
            assumptions. Interfacial tension and impeller inputs are screening values.
          </p>
          <div className="form-row">
            {numberInput("speed", "Impeller speed (1/s)")}
            {numberInput("D", "Impeller diameter (m)")}
            {numberInput("H", "Separation height (m)")}
            {numberInput("sigma", "Interfacial tension σ_LL (N/m)")}
          </div>
          <button type="submit" className="primary" disabled={!components.length || compute.isPending}>
            {compute.isPending ? "Computing…" : "Compute blend"}
          </button>
        </form>
        {compute.isError && <ErrorNote error={compute.error} />}
      </Card>

      {res && status && (
        <Card title="Results">
          <p className={`status status-${status.kind}`}>{status.text}</p>
          <div className="table-scroll">
            <table className="results">
              <thead>
                <tr>
                  {["Component", "Vol %", "Mass %", "ρ (kg/m³)", "μ (Pa·s)", "ν (mm²/s = cSt)", "σ (N/m)", "D (m²/s)", "Cp (J/kg·K)", "k (W/m·K)"].map(
                    (h) => (
                      <th key={h}>{h}</th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {res.components.map((cp) => (
                  <tr key={String(cp.name)}>
                    <td>{String(cp.name)}</td>
                    <td className="num">{formatF(Number(cp.vol_frac) * 100, 1)}</td>
                    <td className="num">{formatF(Number(cp.mass_frac) * 100, 1)}</td>
                    {propertyCells(cp).map((v, i) => (
                      <td key={i} className="num">
                        {v}
                      </td>
                    ))}
                  </tr>
                ))}
                <tr className="total">
                  <td>Blend</td>
                  <td className="num">100.0</td>
                  <td className="num">100.0</td>
                  {propertyCells(res.blend).map((v, i) => (
                    <td key={i} className="num">
                      {v}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>

          <h3>Miscibility screening</h3>
          <p className="muted">
            Screening reflects ~25 °C behaviour; temperature effects (e.g. hexane/methanol UCST ≈ 34
            °C) are not modeled.
          </p>
          <table className="results">
            <thead>
              <tr>
                <th>Pair</th>
                <th>Assessment</th>
                <th>R_a (MPa½)</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {res.pairs.map((p) => (
                <tr key={p.label}>
                  <td>{p.label}</td>
                  <td>{p.assessment}</td>
                  <td className="num">{formatF(p.Ra_MPa05, 1)}</td>
                  <td>{p.source}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {res.dispersion.length > 0 && (
            <>
              <h3>Dispersion estimate</h3>
              <table className="results">
                <thead>
                  <tr>
                    <th>Pair</th>
                    <th>Weber number</th>
                    <th>d₃₂ (µm)</th>
                    <th>N_min (1/s)</th>
                    <th>N/N_min</th>
                    <th>Rest separation</th>
                  </tr>
                </thead>
                <tbody>
                  {res.dispersion.map((d) => (
                    <tr key={String(d.pair)}>
                      <td>{String(d.pair)}</td>
                      <td className="num">{formatG(Number(d.We), 3)}</td>
                      <td className="num">{formatG(Number(d.d32_um), 3)}</td>
                      <td className="num">{formatG(Number(d.N_min_1_s), 3)}</td>
                      <td className="num">{formatG(Number(d.N_over_N_min), 3)}</td>
                      <td>{String(d.assessment)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <h3>Phase stratification</h3>
          <p className="muted">
            Settled (unagitated) liquid levels predicted from pairwise miscibility and phase density
            — densest phase at the bottom. Layer heights are proportional to volume; mutual
            solubility between phases is neglected.
          </p>
          <Chart figure={compute.data?.figure} height={450} />
        </Card>
      )}
    </>
  );
}

export function FluidDatabase() {
  const { notice, setNotice, run } = useNotice();
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.some(([k]) => k === params.get("tab")) ? (params.get("tab") as Tab) : "library";
  const library = useLibrary();
  const custom = useTable("fluids/custom");

  return (
    <>
      <PageTitle pageKey="Fluid_Database">Fluid Database</PageTitle>
      <p>
        {custom.list.data && library.data
          ? `${custom.list.data.count} custom fluids (plus ${library.data.length} built-in solvents).`
          : "…"}
      </p>

      <div className="tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            onClick={() => setParams(key === "library" ? {} : { tab: key }, { replace: true })}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "library" && <LibraryTab />}
      {tab === "properties" && <PropertiesTab />}
      {tab === "custom" && <CustomTab run={run} />}
      {tab === "blend" && <BlendTab />}
      {tab === "io" && (
        <ImportExport table="fluids/custom" noun="custom fluid" run={run} title="Import / Export (custom fluids)" />
      )}

      <AdminPanel />
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
