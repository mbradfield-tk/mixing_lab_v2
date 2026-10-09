import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, postForFile, unwrap, type Schemas } from "../api/client";
import type { Row } from "../api/tables";
import { Chart } from "../components/Chart";
import { NumberField, Segmented, SelectField, Switch } from "../components/Form";
import { Fader, InstrumentPanel, Knob, Selector, Setpoint } from "../components/Instrument";
import { StatGrid, TableDetails, statsFromRows } from "../components/Insights";
import { NoticeBar, useNotice } from "../components/Notice";
import { ResultTable } from "../components/ResultTable";
import { Card, ErrorNote, PageTitle } from "../components/ui";
import { useDebounced } from "../hooks";
import { asOrder, downloadBlob, sliderStep } from "./assessment/model";
import {
  INITIAL, MODES, MODE_HINT, adiabaticText, agitatorText, buildBody, colorLimits, heatStatus, kpiRows,
  reactionStatus, sweepRange, type HeatBody, type Inputs, type Mode, type SweepKey,
} from "./heat/model";

type HeatResult = Schemas["HeatCoolResult"];
type ReactionResult = Schemas["ReactionProfileResult"];
type Figures = Schemas["ChartResult"]["figures"];

const num = (v: unknown, fallback: number) => {
  const x = v === null || v === undefined || v === "" ? Number.NaN : Number(v);
  return Number.isFinite(x) ? x : fallback;
};
const md = (text: string) => <ReactMarkdown>{text}</ReactMarkdown>;

type Last =
  | { mode: "heat"; key: string; body: HeatBody; result: HeatResult; figures: Figures }
  | { mode: "reaction"; key: string; body: Record<string, unknown>; result: ReactionResult; figures: Figures }
  | { mode: "sweep"; key: string; figures: Figures; x: string; y: string };

export function HeatTransfer() {
  const { notice, setNotice, run } = useNotice();
  const [mode, setMode] = useState<Mode>("heat");
  const [inputs, setInputs] = useState<Inputs>(INITIAL);
  const set = (patch: Partial<Inputs>) => setInputs((i) => ({ ...i, ...patch }));

  const options = useQuery({ queryKey: ["options"], queryFn: async () => unwrap(await api.GET("/api/v1/options")) });
  const htOptions = useQuery({
    queryKey: ["heat-options"],
    queryFn: async () => unwrap(await api.GET("/api/v1/heat-transfer/options")),
    staleTime: Infinity,
  });
  const ht = htOptions.data;
  const reactionList =
    (inputs.reactionSource === "classes" ? options.data?.reaction_classes : options.data?.reactions_measured) ?? [];
  const sweepLabel = (key: string) => ht?.sweep_parameters.find((p) => p.field === key)?.label ?? key;

  // Vessel bounds for the sweep defaults; refreshed with each vessel.
  const [ranges, setRanges] = useState<{ N_rpm_range?: number[] | null; V_L_range?: number[] | null }>({});
  const span = (r?: number[] | null) => (r && r.length === 2 && r[1] > r[0] ? (r as [number, number]) : null);
  const nRange = span(ranges.N_rpm_range);
  const vRange = span(ranges.V_L_range);
  const setVolume = (v_l: string) => {
    areaPending.current = true;
    set({ v_l });
  };

  function sweepDefaults(i: Inputs, r = ranges): Partial<Inputs> {
    const zero = ht?.sweep_zero_max ?? {};
    const [xMin, xMax] = sweepRange(i.sweepX, num(i[i.sweepX], 0), r, zero);
    const [yMin, yMax] = sweepRange(i.sweepY, num(i[i.sweepY], 0), r, zero);
    return { xMin: String(xMin), xMax: String(xMax), yMin: String(yMin), yMax: String(yMax) };
  }

  // --- loaders (each mirrors a Taipy on_change handler) -----------------------
  async function loadReactor(name: string) {
    const d = unwrap(await api.GET("/api/v1/heat-transfer/defaults/{name}", { params: { path: { name } } }));
    const r = { N_rpm_range: d.N_rpm_range, V_L_range: d.V_L_range };
    setRanges(r);
    setInputs((i) => {
      const next: Inputs = {
        ...i,
        reactor: name,
        d_tank: String(d.D_tank_m),
        d_imp: String(d.D_imp_m),
        n_rpm: String(d.N_rpm),
        np_in: String(d.Np),
        v_l: String(d.V_L),
        a_ht: String(d.A_ht_m2),
        wallMaterial: d.wall_material,
        wall_k: String(d.wall_k_W_mK),
        wall_thickness_mm: String(d.wall_thickness_mm),
        liningMaterial: d.lining_material,
        lining_k: String(d.lining_k_W_mK),
        lining_thickness_mm: String(d.lining_thickness_mm),
      };
      return { ...next, ...sweepDefaults(next, r) };
    });
  }

  async function loadFluid(name: string, tStart: string) {
    const p = unwrap(await api.GET("/api/v1/fluids/thermal", { params: { query: { name, T_C: num(tStart, 25) } } }));
    set({ fluid: name, rho: String(p.rho_kg_m3), mu: String(p.mu_Pa_s), cp: String(p.cp_J_kgK), k_fluid: String(p.k_W_mK) });
  }

  async function loadReaction(name: string) {
    if (!name) return;
    const r = unwrap(await api.GET("/api/v1/reactions/{name}", { params: { path: { name } } })) as Row;
    setInputs((i) => ({
      ...i,
      reaction: name,
      order: r.order ? asOrder(r.order) : i.order,
      rxnK: String(num(r.k_value, num(i.rxnK, 0.5))),
      rxnC0: String(num(r.C0_mol_L, num(i.rxnC0, 1))),
      rxnDH: String(num(r.delta_H_kJ_mol, num(i.rxnDH, -50))),
    }));
  }

  async function updateArea(vL: string) {
    const v = num(vL, Number.NaN);
    const d = num(inputs.d_tank, Number.NaN);
    if (!(v > 0) || !(d > 0) || !inputs.reactor) return;
    const res = unwrap(
      await api.GET("/api/v1/heat-transfer/area", { params: { query: { reactor: inputs.reactor, D_tank_m: d, V_L: v } } }),
    );
    set({ a_ht: String(res.A_ht_m2) });
  }

  const report = (p: Promise<unknown>) => void p.catch((e: Error) => setNotice({ kind: "error", text: e.message }));

  // Re-derive the jacket area once a user-set volume settles.
  const areaPending = useRef(false);
  const vSettled = useDebounced(inputs.v_l, 400);
  useEffect(() => {
    if (!areaPending.current) return;
    areaPending.current = false;
    report(updateArea(vSettled));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vSettled]);

  const initialised = useRef(false);
  useEffect(() => {
    const o = options.data;
    if (!o || !ht || initialised.current) return;
    initialised.current = true;
    const reactors = [...o.reactors].sort();
    const reactor = reactors.includes("TMA EasyMax-102") ? "TMA EasyMax-102" : (reactors[0] ?? "");
    const htm = Object.keys(ht.media)[0] ?? "";
    set({ htm, cp_jacket: String(ht.media[htm] ?? 3500), nusselt: ht.nusselt_correlations[0] ?? "", fouling: String(ht.fouling_default) });
    report(loadReactor(reactor));
    report(loadFluid(o.fluids.includes("Water") ? "Water" : (o.fluids[0] ?? "Water"), "25"));
    const measured = o.reactions_measured.length ? o.reactions_measured : o.reaction_classes;
    report(loadReaction(measured[0] ?? ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.data, ht]);

  // --- compute --------------------------------------------------------------
  const built = useMemo(() => buildBody(inputs), [inputs]);
  const [last, setLast] = useState<Last | null>(null);
  const [status, setStatus] = useState(MODE_HINT.heat);

  function requestFor(m: Mode): { kind: string; body: Record<string, unknown> } | { error: string } {
    if ("error" in built) return built;
    const { T_target_C: _target, q_rxn_W: _q, ...shared } = built.body;
    if (m === "heat") return { kind: "heat-cool", body: built.body };
    if (m === "reaction") {
      const k = num(inputs.rxnK, 0);
      const c0 = num(inputs.rxnC0, 0);
      if (!(k > 0) || !(c0 > 0)) return { error: "Reaction needs a rate constant k > 0 and C0 > 0." };
      return {
        kind: "reaction-profile",
        body: { ...shared, reaction: { order: inputs.order, k, C0_mol_L: c0, dH_kJ_mol: num(inputs.rxnDH, 0) } },
      };
    }
    if (inputs.sweepX === inputs.sweepY) return { error: "Choose two different parameters for the sweep." };
    const [x0, x1, y0, y1] = [inputs.xMin, inputs.xMax, inputs.yMin, inputs.yMax].map((v) => num(v, Number.NaN));
    if (![x0, x1, y0, y1].every(Number.isFinite) || !(x1 > x0) || !(y1 > y0))
      return { error: "Each sweep maximum must be greater than its minimum." };
    const custom = inputs.colorMode === "Custom";
    const [u0, u1, a0, a1] = [inputs.uMin, inputs.uMax, inputs.uaMin, inputs.uaMax].map((v) => num(v, Number.NaN));
    if (custom && !([u0, u1, a0, a1].every(Number.isFinite) && u1 > u0 && a1 > a0))
      return { error: "Each custom color maximum must be greater than its minimum." };
    return {
      kind: "ua-surface",
      body: {
        ...shared,
        x_parameter: inputs.sweepX,
        y_parameter: inputs.sweepY,
        x_range: [x0, x1],
        y_range: [y0, y1],
        color_theme: inputs.colorTheme,
        U_color_range: custom ? [u0, u1] : null,
        UA_color_range: custom ? [a0, a1] : null,
      },
    };
  }
  const current = requestFor(mode);
  const currentKey = "body" in current ? `${mode}:${JSON.stringify(current.body)}` : null;
  const stale = !!last && last.mode === mode && last.key !== currentKey;

  const compute = useMutation({
    mutationFn: async (): Promise<Last> => {
      const req = requestFor(mode);
      if ("error" in req) throw new Error(req.error);
      const key = `${mode}:${JSON.stringify(req.body)}`;
      const chart = api
        .POST("/api/v1/charts/{kind}", { params: { path: { kind: req.kind } }, body: req.body })
        .then(unwrap);
      if (mode === "heat") {
        const [result, figs] = await Promise.all([
          api.POST("/api/v1/heat-transfer/heat-cool", { body: req.body as HeatBody }).then(unwrap),
          chart,
        ]);
        return { mode, key, body: req.body as HeatBody, result, figures: figs.figures };
      }
      if (mode === "reaction") {
        const [result, figs] = await Promise.all([
          api
            .POST("/api/v1/heat-transfer/reaction-profile", {
              body: req.body as Schemas["ReactionProfileRequest"],
            })
            .then(unwrap),
          chart,
        ]);
        return { mode, key, body: req.body, result, figures: figs.figures };
      }
      const figs = await chart;
      return { mode, key, figures: figs.figures, x: sweepLabel(inputs.sweepX), y: sweepLabel(inputs.sweepY) };
    },
  });

  function onCompute() {
    compute
      .mutateAsync()
      .then((res) => {
        setLast(res);
        if (res.mode === "heat") {
          const r = res.result;
          setStatus(heatStatus(r.coefficients.U_W_m2K ?? 0, r.time_constant_jacket_s, r.time_analytical_s));
          setNotice({ kind: "success", text: "Heat-transfer results computed." });
        } else if (res.mode === "reaction") {
          const r = res.result;
          setStatus(reactionStatus(num(inputs.rxnDH, 0), r.T_peak_C ?? 0, r.T_adiabatic_C ?? 0, r.t_complete_s));
          setNotice({ kind: "success", text: "Reaction temperature profile computed." });
        } else {
          setStatus(`Parameter sweep computed for ${res.x} and ${res.y}.`);
          setNotice({ kind: "success", text: "U and UA parameter surfaces computed." });
          if (inputs.colorMode === "Automatic") {
            const u = colorLimits((res.figures.U?.data as { z: (number | null)[][] }[])[0].z);
            const ua = colorLimits((res.figures.UA?.data as { z: (number | null)[][] }[])[0].z);
            set({ uMin: String(u[0]), uMax: String(u[1]), uaMin: String(ua[0]), uaMax: String(ua[1]) });
          }
        }
      })
      .catch((e: Error) => {
        setStatus(e.message);
        setNotice({ kind: "error", text: e.message });
      });
  }

  const pdf = useMutation({
    mutationFn: () =>
      postForFile(`/api/v1/reports/${last!.mode === "heat" ? "heat-cool" : "reaction-profile"}`, (last as { body: unknown }).body),
  });

  function setSweepAxis(axis: "x" | "y", key: SweepKey) {
    setInputs((i) => {
      const other = axis === "x" ? "sweepY" : "sweepX";
      const next: Inputs = { ...i, [axis === "x" ? "sweepX" : "sweepY"]: key };
      if (next[other] === key) {
        const replacement = ht?.sweep_parameters.find((p) => p.field !== key)?.field as SweepKey | undefined;
        if (replacement) next[other] = replacement;
      }
      return { ...next, ...sweepDefaults(next) };
    });
  }

  const sweepOptions = (ht?.sweep_parameters ?? []).map((p) => ({ code: p.field, label: p.label }));
  const shown = last && last.mode === mode ? last : null;
  const adiabatic = adiabaticText(num(inputs.rho, 0), num(inputs.cp, 0), num(inputs.rxnC0, 0), num(inputs.rxnDH, 0), num(inputs.t_start, 25));

  return (
    <>
      <PageTitle pageKey="Heat_Transfer">Heat Transfer Tool</PageTitle>
      <p>{status}</p>
      {(options.isError || htOptions.isError) && <ErrorNote error={options.error ?? htOptions.error} />}

      <Card title="Mode">
        <p>Choose heat/cool operation, a reaction temperature profile, or a two-parameter U/UA sweep.</p>
        <Segmented
          label="What to model"
          value={mode}
          options={MODES.map((m) => ({ code: m.code, label: m.label }))}
          onChange={(m) => {
            setMode(m as Mode);
            setStatus(MODE_HINT[m as Mode]);
          }}
        />
      </Card>

      <Card title="Project Information">
        <div className="form-row">
          <label>
            Project name
            <input value={inputs.projectName} onChange={(e) => set({ projectName: e.target.value })} />
          </label>
          <label>
            Step
            <input value={inputs.step} onChange={(e) => set({ step: e.target.value })} />
          </label>
          <SelectField
            label="Unit operation"
            value={inputs.unitOperation}
            options={[{ code: "", label: "- select -" }, ...(ht?.unit_operations ?? []).map((u) => ({ code: u, label: u }))]}
            onChange={(unitOperation) => set({ unitOperation })}
          />
          <label>
            Process version
            <input value={inputs.processVersion} onChange={(e) => set({ processVersion: e.target.value })} />
          </label>
        </div>
      </Card>

      <Card title="1. Reactor and Fluid Selection">
        <div className="form-row">
          <SelectField
            label="Reactor"
            value={inputs.reactor}
            options={[...(options.data?.reactors ?? [])].sort()}
            onChange={(v) => {
              report(loadReactor(v));
              setNotice({ kind: "info", text: "Reactor defaults loaded." });
            }}
          />
          <SelectField
            label="Process fluid"
            value={inputs.fluid}
            options={options.data?.fluids ?? []}
            onChange={(v) => {
              report(loadFluid(v, inputs.t_start));
              setNotice({ kind: "info", text: "Fluid properties loaded." });
            }}
          />
          <SelectField label="Nusselt correlation" value={inputs.nusselt} options={ht?.nusselt_correlations ?? []} onChange={(nusselt) => set({ nusselt })} />
        </div>
      </Card>

      <Card title="2. Geometry, Materials, and Operating Inputs">
        <h3>Reactor &amp; Operating Point</h3>
        <div className="form-row">
          <NumberField label="D_tank (m)" value={inputs.d_tank} onChange={(d_tank) => set({ d_tank })} />
          <NumberField label="D_imp (m)" value={inputs.d_imp} onChange={(d_imp) => set({ d_imp })} />
          <NumberField label="Np" value={inputs.np_in} onChange={(np_in) => set({ np_in })} />
        </div>
        <InstrumentPanel title="Operating point">
          {nRange ? (
            <Knob
              label="Stir speed"
              value={inputs.n_rpm}
              onChange={(n_rpm) => set({ n_rpm })}
              min={nRange[0]}
              max={nRange[1]}
              step={sliderStep(nRange[1] - nRange[0])}
              unit="RPM"
            />
          ) : (
            <NumberField label="N (RPM)" value={inputs.n_rpm} onChange={(n_rpm) => set({ n_rpm })} />
          )}
          {vRange ? (
            <Fader
              label="Liquid volume"
              value={inputs.v_l}
              onChange={setVolume}
              min={vRange[0]}
              max={vRange[1]}
              step={sliderStep(vRange[1] - vRange[0])}
              unit="L"
            />
          ) : (
            <NumberField label="Liquid volume (L)" value={inputs.v_l} onChange={setVolume} />
          )}
          <Setpoint label="Start temperature" value={inputs.t_start} onChange={(t_start) => set({ t_start })} unit="°C" />
          {mode === "heat" && (
            <Setpoint label="Target temperature" value={inputs.t_target} onChange={(t_target) => set({ t_target })} unit="°C" />
          )}
          <Selector
            label="Coolant"
            value={inputs.htm}
            options={Object.keys(ht?.media ?? {})}
            onChange={(htm) => {
              set({ htm, cp_jacket: String(ht?.media[htm] ?? inputs.cp_jacket) });
              setNotice({ kind: "info", text: "Coolant defaults loaded." });
            }}
          />
          <Setpoint label="Coolant temp" value={inputs.t_jacket} onChange={(t_jacket) => set({ t_jacket })} unit="°C" />
        </InstrumentPanel>
        <div className="form-row">
          <NumberField label="Heat-transfer area A_ht (m²)" value={inputs.a_ht} onChange={(a_ht) => set({ a_ht })} />
          <NumberField label="Fouling resistance (m²·K/W)" value={inputs.fouling} onChange={(fouling) => set({ fouling })} />
          <NumberField label="Extra heat input (W)" value={inputs.q_rxn} onChange={(q_rxn) => set({ q_rxn })} />
        </div>
        <Switch label="Include agitator heat" checked={inputs.includeAgitator} onChange={(includeAgitator) => set({ includeAgitator })} />

        <h3>Wall</h3>
        <div className="form-row">
          <SelectField
            label="Wall material"
            value={inputs.wallMaterial}
            options={Object.keys(ht?.wall_materials ?? {})}
            onChange={(wallMaterial) => set({ wallMaterial, wall_k: String(ht?.wall_materials[wallMaterial] ?? inputs.wall_k) })}
          />
          <NumberField label="Wall k (W/m.K)" value={inputs.wall_k} onChange={(wall_k) => set({ wall_k })} />
          <NumberField label="Wall thickness (mm)" value={inputs.wall_thickness_mm} onChange={(wall_thickness_mm) => set({ wall_thickness_mm })} />
          <NumberField label="mu at wall (Pa.s)" value={inputs.mu_wall} onChange={(mu_wall) => set({ mu_wall })} />
        </div>

        <h3>Lining</h3>
        <div className="form-row">
          <SelectField
            label="Lining"
            value={inputs.liningMaterial}
            options={["None", ...Object.keys(ht?.linings ?? {})]}
            onChange={(liningMaterial) => {
              const [k, mm] = liningMaterial === "None" ? [0, 0] : (ht?.linings[liningMaterial] ?? [0, 2]);
              set({ liningMaterial, lining_k: String(k), lining_thickness_mm: String(mm) });
            }}
          />
          <NumberField label="Lining k (W/m.K)" value={inputs.lining_k} onChange={(lining_k) => set({ lining_k })} />
          <NumberField label="Lining thickness (mm)" value={inputs.lining_thickness_mm} onChange={(lining_thickness_mm) => set({ lining_thickness_mm })} />
        </div>

        <h3>Fluid Properties</h3>
        <div className="form-row">
          <NumberField label="rho (kg/m3)" value={inputs.rho} onChange={(rho) => set({ rho })} />
          <NumberField label="mu (Pa.s)" value={inputs.mu} onChange={(mu) => set({ mu })} />
          <NumberField label="Cp (J/kg.K)" value={inputs.cp} onChange={(cp) => set({ cp })} />
          <NumberField label="k fluid (W/m.K)" value={inputs.k_fluid} onChange={(k_fluid) => set({ k_fluid })} />
        </div>

        <h3>Jacket</h3>
        <div className="form-row">
          <NumberField label="Jacket velocity (m/s)" value={inputs.v_jacket} onChange={(v_jacket) => set({ v_jacket })} />
          <NumberField label="Jacket hydraulic diameter (m)" value={inputs.d_hyd_jacket} onChange={(d_hyd_jacket) => set({ d_hyd_jacket })} />
          <NumberField label="Jacket mass flow (kg/s)" value={inputs.m_dot_jacket} onChange={(m_dot_jacket) => set({ m_dot_jacket })} />
          <NumberField label="Jacket Cp (J/kg.K)" value={inputs.cp_jacket} onChange={(cp_jacket) => set({ cp_jacket })} />
        </div>

        <h3>Plot</h3>
        <div className="form-row">
          <SelectField
            label="Plot time unit"
            value={inputs.timeUnit}
            options={["Seconds", "Minutes", "Hours"]}
            onChange={(v) => set({ timeUnit: v as Inputs["timeUnit"] })}
          />
        </div>
      </Card>

      {mode === "sweep" && (
        <Card title="Parameter Sweep Inputs">
          <h3>X axis</h3>
          <div className="form-row three">
            <SelectField label="X-axis parameter" value={inputs.sweepX} options={sweepOptions} onChange={(v) => setSweepAxis("x", v as SweepKey)} />
            <NumberField label="X minimum" value={inputs.xMin} onChange={(xMin) => set({ xMin })} />
            <NumberField label="X maximum" value={inputs.xMax} onChange={(xMax) => set({ xMax })} />
          </div>
          <h3>Y axis</h3>
          <div className="form-row three">
            <SelectField label="Y-axis parameter" value={inputs.sweepY} options={sweepOptions} onChange={(v) => setSweepAxis("y", v as SweepKey)} />
            <NumberField label="Y minimum" value={inputs.yMin} onChange={(yMin) => set({ yMin })} />
            <NumberField label="Y maximum" value={inputs.yMax} onChange={(yMax) => set({ yMax })} />
          </div>
          <h3>Surface Appearance</h3>
          <div className="form-row two">
            <SelectField
              label="Color theme"
              value={inputs.colorTheme}
              options={["Takeda", "Turbo", "Viridis", "Cool/Warm", "X-ray"]}
              onChange={(v) => set({ colorTheme: v as Inputs["colorTheme"] })}
            />
            <SelectField
              label="Color range"
              value={inputs.colorMode}
              options={["Automatic", "Custom"]}
              onChange={(v) => set({ colorMode: v as Inputs["colorMode"] })}
            />
          </div>
          {inputs.colorMode === "Custom" && (
            <>
              <h3>U color range</h3>
              <div className="form-row two">
                <NumberField label="U color minimum" value={inputs.uMin} onChange={(uMin) => set({ uMin })} />
                <NumberField label="U color maximum" value={inputs.uMax} onChange={(uMax) => set({ uMax })} />
              </div>
              <h3>UA color range</h3>
              <div className="form-row two">
                <NumberField label="UA color minimum" value={inputs.uaMin} onChange={(uaMin) => set({ uaMin })} />
                <NumberField label="UA color maximum" value={inputs.uaMax} onChange={(uaMax) => set({ uaMax })} />
              </div>
            </>
          )}
        </Card>
      )}

      {mode === "reaction" && (
        <Card title="Reaction Kinetics and Heat of Reaction">
          <p>
            Pick a reaction to fill its kinetics, or edit the fields. Runs to 99% conversion with a fixed rate constant (no
            activation energy).
          </p>
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
                if (next) report(loadReaction(next));
              }}
            />
            <SelectField
              label="Reaction"
              value={inputs.reaction}
              options={reactionList}
              onChange={(v) => {
                report(loadReaction(v));
                setNotice({ kind: "info", text: "Reaction kinetics and heat of reaction loaded." });
              }}
            />
            <SelectField label="Order" value={inputs.order} options={["1", "2", "pseudo-1", "pseudo-2"]} onChange={(v) => set({ order: v as Inputs["order"] })} />
            <NumberField label="Rate constant k" value={inputs.rxnK} onChange={(rxnK) => set({ rxnK })} />
            <NumberField label="C0 (mol/L)" value={inputs.rxnC0} onChange={(rxnC0) => set({ rxnC0 })} />
            <NumberField label="dH_rxn (kJ/mol)" value={inputs.rxnDH} onChange={(rxnDH) => set({ rxnDH })} />
          </div>
          {md(adiabatic)}
        </Card>
      )}

      <button type="button" className={`compute-btn ${!shown || stale ? "primary" : "done"}`} disabled={compute.isPending} onClick={onCompute}>
        {compute.isPending ? "Computing…" : "Compute"}
      </button>
      {stale && (
        <p className="stale-note">
          ⚠️ Inputs changed since the last run — click <em>Compute</em> to refresh the results.
        </p>
      )}

      {shown?.mode === "sweep" && (
        <Card title="U and UA Surfaces">
          <div className="grid-2">
            <Chart figure={shown.figures.U} height={520} />
            <Chart figure={shown.figures.UA} height={520} />
          </div>
        </Card>
      )}

      {shown?.mode === "heat" && (
        <>
          <Card title="3. Core KPIs">
            <StatGrid stats={statsFromRows(kpiRows(shown.result.coefficients), "Metric")} />
            <TableDetails rows={kpiRows(shown.result.coefficients)} csvName="heat_transfer_core_kpis.csv" stale={stale} />
          </Card>
          <Card title="4. Heat Transfer Resistances & Agitator Heat">
            <p>Relative contribution of each series thermal resistance to the overall U.</p>
            <Chart figure={shown.figures.resistances} height={360} />
            {md(agitatorText(shown.result.coefficients.agitator_power_W ?? 0, shown.result.q_max_W ?? 0))}
          </Card>
          <Card title="5. UA Sensitivity">
            <p>UA versus stir speed at the selected volume, and versus volume at the selected stir speed.</p>
            <div className="grid-2">
              <Chart figure={shown.figures.ua_vs_speed} height={360} />
              <Chart figure={shown.figures.ua_vs_volume} height={360} />
            </div>
          </Card>
          <Card title="6. Temperature and Heat-Duty Profiles">
            <div className="grid-2">
              <Chart figure={shown.figures.temperature} height={380} />
              <Chart figure={shown.figures.duty} height={380} />
            </div>
          </Card>
          <Card title="7. Correlation and HTM Comparisons">
            <h3>Nusselt correlation comparison</h3>
            <ResultTable rows={shown.result.correlations} csvName="heat_transfer_correlations.csv" stale={stale} />
            <h3>Heat transfer medium comparison</h3>
            <ResultTable rows={shown.result.media} csvName="heat_transfer_media.csv" stale={stale} />
          </Card>
          <Card title="8. Summary">
            <StatGrid size="sm" stats={statsFromRows(shown.result.summary, "Metric")} />
            <TableDetails rows={shown.result.summary} csvName="heat_transfer_summary.csv" stale={stale} />
          </Card>
        </>
      )}

      {shown?.mode === "reaction" && (
        <Card title="Reaction Temperature Profile">
          <p>
            Batch temperature (red) and conversion (grey dashed, right axis) versus time. Dotted lines mark the coolant
            temperature and the adiabatic temperature (the peak the batch would reach with no cooling).
          </p>
          <div className="chart-narrow">
            <Chart figure={shown.figures.profile} height={400} />
          </div>
          <h2>Reaction and Heat-Transfer Summary</h2>
          <StatGrid size="sm" stats={statsFromRows(shown.result.summary, "Metric")} />
          <TableDetails rows={shown.result.summary} csvName="heat_transfer_reaction_summary.csv" stale={stale} />
        </Card>
      )}

      {mode !== "sweep" && (
        <Card title="Export Report">
          <p>
            Generate a PDF capturing the system, resistances, KPIs, and profiles (heat/cool mode) or the reaction
            kinetics and temperature/conversion profile (reaction mode).
          </p>
          <button
            type="button"
            className="primary"
            disabled={!shown || stale || pdf.isPending}
            onClick={() =>
              void run(pdf.mutateAsync(), "PDF report downloaded.")
                .then(({ blob, filename }) => downloadBlob(blob, filename))
                .catch(() => undefined)
            }
          >
            {pdf.isPending ? "Building PDF…" : "Download PDF report"}
          </button>
          {!shown && <span className="muted"> Compute first.</span>}
        </Card>
      )}

      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
