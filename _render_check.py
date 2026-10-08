"""Render representative report figures with the matplotlib fallback (dev check)."""
import sys
import time

sys.path.insert(0, "tests")
import test_golden_outputs as g  # noqa: E402
from pages import bourne_protocol as bp, heat_transfer as ht, vessel_assessment as va  # noqa: E402
from utils import report_builder as rb  # noqa: E402
from viz.static import render_png  # noqa: E402

for mod in (va, ht, bp):
    mod.notify = lambda *a, **k: None
st = g._state(va, **g._VA_FULL)
va.on_va_compute(st)
va.on_va_surface(st)
h = g._state(ht)
ht.on_compute(h)
r = g._state(ht, ht_mode=ht.HT_MODE_RXN, rxn_k=0.01, rxn_c0=1.0, rxn_dH=-100.0)
ht.on_compute(r)
b = g._state(bp)
bp._build_plan(b)
curves = {"A": {"pct_arr": [10, 55, 100], "maxV": {"Da_micro": [0.01, 0.1, 1.0]},
                "minV": {"Da_micro": [0.02, 0.2, 2.0]}},
          "B": {"pct_arr": [10, 55, 100], "maxV": {"Da_micro": [0.05, 0.5, 5.0]},
                "minV": {"Da_micro": [0.1, 1.0, 9.0]}}}
figs = {"va_env": st.va_env_fig, "va_surface": st.va_surf_fig, "ht_T": h.temp_fig,
        "ht_Q": h.duty_fig, "ht_res": h.res_fig, "ht_ua": h.ua_rpm_fig, "ht_rxn": r.rxn_fig,
        "bp_t1": b.bp_t1_plot,
        "vc_report": rb.build_comparison_envelope_fig("Da_micro", curves, None, {})}
for k, f in figs.items():
    t = time.time()
    png = render_png(f)
    with open(f"/tmp/static_{k}.png", "wb") as fh:
        fh.write(png)
    print(k, len(png), round(time.time() - t, 2))
