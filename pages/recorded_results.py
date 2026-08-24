"""Recorded Results page (Taipy).

Ported from the Streamlit ``8_Recorded_Results.py`` page. Views, filters and
exports the case results saved to ``data/recorded_results.csv`` (written by the
*Save results to Recorded Results* actions on the Vessel Assessment and Vessel
Comparison pages). Includes an assessment summary, CSV bulk export of the
filtered set, and a confirm-gated clear-all action.

Results saved in another session/page after this page was loaded are picked up
with the **Refresh** button (``db.fresh_csv`` re-reads on mtime change).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from pages import _db_common as db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RESULTS_CSV = DATA_DIR / "recorded_results.csv"

_FILTER_COLS = [("reactor", "Reactor"), ("reaction", "Reaction"), ("fluid", "Fluid")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load() -> pd.DataFrame:
    return db.fresh_csv(RESULTS_CSV).copy()


def _options(df: pd.DataFrame, col: str) -> list[str]:
    if col not in df.columns:
        return []
    return sorted(df[col].dropna().astype(str).unique().tolist())


def _fmt_display(df: pd.DataFrame) -> pd.DataFrame:
    """Display copy with floats shown to 4 significant digits."""
    disp = df.copy()
    for c in disp.columns:
        if pd.api.types.is_float_dtype(disp[c]):
            disp[c] = disp[c].map(lambda v: f"{v:.4g}" if pd.notna(v) else "—")
    return disp


def _filtered(df: pd.DataFrame, reactors, reactions, fluids) -> pd.DataFrame:
    out = df
    for col, sel in (("reactor", reactors), ("reaction", reactions), ("fluid", fluids)):
        if sel and col in out.columns:
            out = out[out[col].astype(str).isin([str(s) for s in sel])]
    return out


def _summary_counts(df: pd.DataFrame) -> tuple[int, int, int]:
    """(reaction-limited, potentially sensitive, mixing-sensitive/limited)."""
    if "Assessment" not in df.columns or df.empty:
        return 0, 0, 0
    a = df["Assessment"].astype(str)
    limited = a.str.contains("mixing-limited|Mixing-sensitive", case=False)
    potential = ~limited & a.str.contains("Potentially sensitive", case=False)
    n_limited, n_potential = int(limited.sum()), int(potential.sum())
    return len(a) - n_limited - n_potential, n_potential, n_limited


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
rr_df = _load()
rr_reactor_sel: list = []
rr_reaction_sel: list = []
rr_fluid_sel: list = []
rr_reactor_options = _options(rr_df, "reactor")
rr_reaction_options = _options(rr_df, "reaction")
rr_fluid_options = _options(rr_df, "fluid")
rr_view_df = _fmt_display(rr_df)
rr_has_data = not rr_df.empty
rr_status = f"Showing {len(rr_df)} of {len(rr_df)} records."
rr_n_safe, rr_n_potential, rr_n_limited = _summary_counts(rr_df)
rr_csv_bytes = db.csv_bytes(rr_df)
rr_csv_name = "mixing_lab_results.csv"
rr_confirm_clear = False


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def _apply(state):
    filtered = _filtered(state.rr_df, state.rr_reactor_sel,
                         state.rr_reaction_sel, state.rr_fluid_sel)
    state.rr_view_df = _fmt_display(filtered)
    state.rr_csv_bytes = db.csv_bytes(filtered)
    state.rr_status = f"Showing {len(filtered)} of {len(state.rr_df)} records."
    state.rr_n_safe, state.rr_n_potential, state.rr_n_limited = _summary_counts(filtered)


def _refresh(state):
    state.rr_df = _load()
    state.rr_has_data = not state.rr_df.empty
    state.rr_reactor_options = _options(state.rr_df, "reactor")
    state.rr_reaction_options = _options(state.rr_df, "reaction")
    state.rr_fluid_options = _options(state.rr_df, "fluid")
    # Drop selections that no longer exist in the reloaded data.
    state.rr_reactor_sel = [s for s in (state.rr_reactor_sel or []) if s in state.rr_reactor_options]
    state.rr_reaction_sel = [s for s in (state.rr_reaction_sel or []) if s in state.rr_reaction_options]
    state.rr_fluid_sel = [s for s in (state.rr_fluid_sel or []) if s in state.rr_fluid_options]
    _apply(state)


def on_rr_refresh(state):
    _refresh(state)
    notify(state, "I", f"Reloaded — {len(state.rr_df)} record(s) on file.")


def on_rr_filter(state):
    _apply(state)


def on_rr_clear_ask(state):
    state.rr_confirm_clear = True


def on_rr_clear_cancel(state):
    state.rr_confirm_clear = False


def on_rr_clear_yes(state):
    try:
        db.save_csv(state.rr_df.iloc[0:0], RESULTS_CSV)
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"Clear failed: {exc}")
        return
    state.rr_confirm_clear = False
    state.rr_reactor_sel, state.rr_reaction_sel, state.rr_fluid_sel = [], [], []
    _refresh(state)
    notify(state, "S", "All recorded results cleared.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Recorded_Results__Recorded Results

View, filter and bulk-export the case results saved from the analysis pages
(**Save results to Recorded Results** on the Vessel Assessment and Vessel
Comparison pages).

<|Refresh|button|on_action=on_rr_refresh|>

<|part|render={not rr_has_data}|class_name=va-card|
**No results recorded yet.** Compute a case on the **Vessel Assessment** or
**Vessel Comparison** page and use *Save results to Recorded Results*, then
click **Refresh** here.
|>

<|part|render={rr_has_data}|
<|part|class_name=va-card|
## Filter Results
<|layout|columns=1 1 1|class_name=form-grid|
<|{rr_reactor_sel}|selector|lov={rr_reactor_options}|multiple|dropdown|label=Reactor|on_change=on_rr_filter|>

<|{rr_reaction_sel}|selector|lov={rr_reaction_options}|multiple|dropdown|label=Reaction|on_change=on_rr_filter|>

<|{rr_fluid_sel}|selector|lov={rr_fluid_options}|multiple|dropdown|label=Fluid|on_change=on_rr_filter|>
|>
|>

<|part|class_name=va-card|
## Results Table
<|{rr_view_df}|table|width=100%|page_size=15|rebuild|>

<|{rr_status}|text|>
|>

<|part|class_name=va-card|
## Assessment Summary
<|part|class_name=result-box|
<|layout|columns=1 1 1|
**🟢 Reaction-limited:** <|{rr_n_safe}|text|>

**🟡 Potentially sensitive:** <|{rr_n_potential}|text|>

**🔴 Mixing-sensitive / limited:** <|{rr_n_limited}|text|>
|>
|>
|>

<|part|class_name=va-card|
## Export
Downloads the currently filtered set as CSV.

<|Download results (CSV)|file_download|content={rr_csv_bytes}|name={rr_csv_name}|label=Download results (CSV)|>
|>

<|part|class_name=va-card|
## Manage Records
<|part|render={not rr_confirm_clear}|
<|Clear all recorded results|button|on_action=on_rr_clear_ask|>
|>

<|part|render={rr_confirm_clear}|
**⚠️ Are you sure? This will permanently delete all recorded results.**

<|layout|columns=1 1|class_name=form-grid|
<|Yes, delete all|button|on_action=on_rr_clear_yes|class_name=compute-btn|>

<|Cancel|button|on_action=on_rr_clear_cancel|>
|>
|>
|>
|>
""")
)
