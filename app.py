from __future__ import annotations

from pathlib import Path
import sys

if sys.version_info >= (3, 13):
    raise RuntimeError("Taipy GUI currently requires Python 3.12 or lower for this app. Please run with Python 3.12.")

from taipy.gui import Gui, navigate

from pages import (
    bourne_protocol,
    equations_reference,
    fluid_database,
    heat_transfer,
    mixing_sensitivity,
    particle_database,
    reaction_database,
    unit_converter,
    vessel_assessment,
    vessel_comparison,
    vessel_database,
)

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Navigation menu
# ---------------------------------------------------------------------------

# Taipy's `menu` is a flat list. Emoji icons are injected via CSS (see root_md)
# because the auto letter-badge mangles emoji, so labels stay plain text here.
menu_options = [
    ("Vessel_Database", "Vessels"),
    ("Fluid_Database", "Fluids"),
    ("Reaction_Database", "Reactions"),
    ("Particle_Database", "Particles"),
    ("Vessel_Assessment", "Vessel Assessment"),
    ("Vessel_Comparison", "Vessel Comparison"),
    ("Bourne_Protocol", "Bourne Protocol"),
    ("Mixing_Sensitivity", "Reaction Sensitivity Protocol"),
    ("Heat_Transfer", "Heat Transfer Tool"),
    ("Unit_Converter", "Unit Converter"),
    ("Equations_Reference", "Equations Reference"),
]


def on_menu_action(state, action, info):
    page = info["args"][0]
    navigate(state, to=page)


def _logo_data_uri() -> str:
    """Return the sidebar logo as a base64 ``data:`` URI (empty string if missing)."""
    import base64

    path = BASE_DIR / "images" / "general" / "logo.png"
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


LOGO_DATA_URI = _logo_data_uri()


def _takeda_logo_uri() -> str:
    """Return the centred page logo (takeda.svg) as a base64 ``data:`` URI."""
    import base64

    path = BASE_DIR / "images" / "general" / "takeda.svg"
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


TAKEDA_LOGO_URI = _takeda_logo_uri()


root_md = """
<style>
/* Replace the native hamburger (triple-bar) toggle icon of the Taipy menu
   with the app logo. The first list item in the menu Drawer is the open/close
   toggle; its avatar holds the MenuIcon SVG we hide and swap for the logo. */
.htt-menu .MuiList-root .MuiButtonBase-root:first-of-type .MuiAvatar-root {
    background-color: #ffffff !important;
    background-image: url("__LOGO_URI__");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    width: 44px !important;
    height: 44px !important;
    border-radius: 6px;
}
.htt-menu .MuiList-root .MuiButtonBase-root:first-of-type .MuiAvatar-root svg {
    display: none !important;
}

/* The menu draws a round icon badge per item whose auto-generated letter mangles
   emoji into "?". Blank out that letter and inject a per-page emoji via ::after,
   so it shows in both the collapsed (icon-only) and expanded menu states. The
   first item's avatar is the logo (styled above) and is left untouched. */
.htt-menu .MuiList-root .MuiButtonBase-root:not(:first-of-type) .MuiAvatar-root {
    color: transparent !important;
    font-size: 0 !important;
    background-color: transparent !important;
}
.htt-menu .MuiList-root .MuiButtonBase-root:not(:first-of-type) .MuiAvatar-root::after {
    color: initial;
    font-size: 1.3rem;
    line-height: 1;
}
/* Icon order follows the `menu_options` list: nth-of-type(N) = menu position
   N-1 (position 1 is the logo/toggle). Update these if you reorder the menu.
   Order: 2=Vessels, 3=Fluids, 4=Reactions, 5=Particles, 6=Vessel Assessment,
   7=Vessel Comparison, 8=Bourne Protocol, 9=Reaction Sensitivity, 10=Heat Transfer,
   11=Unit Converter, 12=Equations Reference. */
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(2) .MuiAvatar-root::after {
    content: "⚗️";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(3) .MuiAvatar-root::after {
    content: "💧";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(4) .MuiAvatar-root::after {
    content: "🧪";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(5) .MuiAvatar-root::after {
    content: "🟤";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(6) .MuiAvatar-root::after {
    content: "🌀";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(7) .MuiAvatar-root::after {
    content: "⚖️";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(8) .MuiAvatar-root::after {
    content: "🅱️";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(9) .MuiAvatar-root::after {
    content: "🧭";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(10) .MuiAvatar-root::after {
    content: "🔥";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(11) .MuiAvatar-root::after {
    content: "🔄";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(12) .MuiAvatar-root::after {
    content: "📐";
}

/* Hide the "Mode" text label on the theme toggle; the sun/moon icons suffice. */
.theme-toggle .MuiTypography-root {
    display: none !important;
}

/* ---- Takeda corporate palette (red / gray / white) --------------------- */
/* Section headings in Takeda red; sub-headings in a neutral gray. */
h1, h2 {
    color: #E1251B;
}
h3, h4 {
    color: #4A4A4A;
}
/* Default (non-tagged) buttons use Takeda red so all actions read as on-brand. */
.taipy-button .MuiButton-root,
button.taipy-button {
    background-color: #E1251B !important;
    color: #ffffff !important;
}
.taipy-button .MuiButton-root:hover,
button.taipy-button:hover {
    background-color: #A81A12 !important;
}
/* Text/link accents and focused input outlines in Takeda red. */
a, .MuiLink-root {
    color: #E1251B;
}
.MuiOutlinedInput-root.Mui-focused .MuiOutlinedInput-notchedOutline {
    border-color: #E1251B !important;
}
.MuiInputLabel-root.Mui-focused {
    color: #E1251B !important;
}
/* Highlight the selected sidebar-menu item with a red accent. */
.htt-menu .MuiList-root .Mui-selected {
    background-color: rgba(225, 37, 27, 0.12) !important;
    border-left: 3px solid #E1251B;
}
/* Table header row: subtle Takeda-red tint for a corporate feel. */
.taipy-table .MuiTableCell-head {
    background-color: #FBEBEA !important;
    color: #4A4A4A !important;
    font-weight: 600;
}

/* ---- Dark-mode adjustments (Taipy adds `.taipy-dark` on the root) -------
   Keep the Takeda red accents but swap light surfaces/text for dark-legible
   equivalents so cards and headings don't jar against a dark background. */
.taipy-dark h1, .taipy-dark h2 {
    color: #FF5247;
}
.taipy-dark h3, .taipy-dark h4 {
    color: #C7CBD1;
}
.taipy-dark .va-card {
    background: rgba(255, 255, 255, 0.04);
    border-color: rgba(255, 255, 255, 0.14);
    border-left-color: #E1251B;
}
.taipy-dark .scheme-box {
    background: rgba(225, 37, 27, 0.16);
}
.taipy-dark .result-box {
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.14);
    border-left-color: #9AA1A9;
}
.taipy-dark .taipy-table .MuiTableCell-head {
    background-color: rgba(225, 37, 27, 0.24) !important;
    color: #F0F0F0 !important;
}
.taipy-dark a,
.taipy-dark .MuiLink-root {
    color: #FF5247;
}
.taipy-dark .htt-menu .MuiList-root .Mui-selected {
    background-color: rgba(225, 37, 27, 0.28) !important;
}

/* Make the primary action button stand out in Takeda red. */
.compute-btn .MuiButton-root,
button.compute-btn {
    background-color: #E1251B !important;
    color: #ffffff !important;
}
.compute-btn .MuiButton-root:hover,
button.compute-btn:hover {
    background-color: #A81A12 !important;
}

/* Neutral gray variant shown after a result has been computed (results fresh). */
.compute-btn-ok .MuiButton-root,
button.compute-btn-ok {
    background-color: #5C6670 !important;
    color: #ffffff !important;
}
.compute-btn-ok .MuiButton-root:hover,
button.compute-btn-ok:hover {
    background-color: #3E464E !important;
}

/* Grouped "card" containers used to visually separate page sections
   (e.g. the Vessel Assessment page). White card with a Takeda-red left accent. */
.va-card {
    border: 1px solid #E6E6E6;
    border-left: 3px solid #E1251B;
    border-radius: 8px;
    padding: 2px 20px 16px;
    margin: 0 0 20px 0;
    background: #ffffff;
}

/* Reaction-scheme highlight box. */
.scheme-box {
    display: block;
    background: rgba(225, 37, 27, 0.08);
    border-left: 4px solid #E1251B;
    padding: 10px 14px;
    border-radius: 6px;
    font-family: monospace;
    margin: 8px 0 4px;
}

/* Result callout: wraps a step's computed assessment so the outcome stands
   apart from the input controls and the white card background. */
.result-box {
    display: block;
    background: #F4F5F6;
    border: 1px solid #E1E4E8;
    border-left: 4px solid #5C6670;
    border-radius: 6px;
    padding: 4px 16px 8px;
    margin: 12px 0 4px;
}

/* On/off toggles: neutral gray when OFF (first button) is selected, Takeda red
   when ON (last button) is selected. Applies to class_name=onoff-toggle. */
.onoff-toggle .MuiToggleButton-root:first-of-type.Mui-selected {
    background-color: #6E6E6E !important;
    color: #ffffff !important;
}
.onoff-toggle .MuiToggleButton-root:last-of-type.Mui-selected {
    background-color: #E1251B !important;
    color: #ffffff !important;
}

/* Operating-envelope chart height, keyed to the number of subplot rows.
   The Taipy chart `height` property is not reactive after first render, so the
   height is driven by a dynamic class_name instead (!important overrides the
   inline height). Heights ≈ rows*300 + title/legend allowance. */
.env-rows-1 { height: 520px !important; }
.env-rows-2 { height: 880px !important; }
.env-rows-3 { height: 1240px !important; }
.env-rows-4 { height: 1600px !important; }
.env-rows-5 { height: 1960px !important; }
.env-rows-6 { height: 2320px !important; }
.env-rows-7 { height: 2680px !important; }
.env-rows-8 { height: 3040px !important; }

/* Editable-table cell dropdowns (MUI Autocomplete) inherit the narrow column
   width, clipping long option text. Let the popup size to its content instead. */
.MuiAutocomplete-popper {
    width: max-content !important;
    min-width: 180px !important;
    max-width: 460px !important;
}
.MuiAutocomplete-popper .MuiAutocomplete-option {
    white-space: nowrap;
}

/* Global search box shown above each database table. */
.db-search {
    max-width: 380px;
    margin: 4px 0 12px 0;
}

/* Centred Takeda logo shown at the top of every page (in the shared shell,
   above the page content). */
.page-logo {
    text-align: center;
    margin: 6px 0 10px;
}
.page-logo img {
    height: 40px;
    width: auto;
}

/* Pre-rendered equation images on the Equations Reference page. Capped to a
   small height so they read like inline text; wide equations still shrink to
   fit the page width. Raise --eq-h to make them larger. */
.eq-img {
    margin: 4px 0 12px 2px;
}
.eq-img img {
    max-width: 100%;
    max-height: 34px;
    height: auto;
    width: auto;
    vertical-align: middle;
}

.taipy-dark .eq-img {
    background: #f4f5f6;
    display: inline-block;
    padding: 4px 10px;
    border-radius: 6px;
}

/* Neat, level form controls: inside layout grids every input/selector fills its
   column and is top-aligned, and all number/text/selector fields share one
   height so boxes line up cleanly regardless of label length. Tight, uniform
   gaps keep related inputs grouped without excess white space. */
.taipy-layout {
    align-items: start;
    row-gap: 8px;
    column-gap: 12px;
    margin-top: 4px;
    margin-bottom: 4px;
}
.taipy-layout .taipy-number,
.taipy-layout .taipy-selector,
.taipy-layout .taipy-input,
.taipy-layout .taipy-date {
    width: 100%;
}
.taipy-number .MuiInputBase-root,
.taipy-input .MuiInputBase-root,
.taipy-selector .MuiInputBase-root {
    min-height: 48px;
}
/* Trim the default dense-form margins so stacked fields sit closer together. */
.taipy-number.MuiFormControl-marginDense,
.taipy-input.MuiFormControl-marginDense,
.taipy-selector.MuiFormControl-marginDense {
    margin-top: 4px;
    margin-bottom: 4px;
}
/* Add/entry forms: cap the grid width so inputs stay grouped and compact
   instead of stretching across the full page on wide screens. */
.form-grid {
    max-width: 780px;
}

/* Let table columns size to their content instead of wrapping text. Wide tables
   scroll horizontally within their container rather than cramming columns and
   wrapping cell/header text unnecessarily. */
.taipy-table .MuiTableContainer-root {
    overflow-x: auto;
}
.taipy-table .MuiTableCell-root {
    white-space: nowrap;
}
</style>

<|menu|lov={menu_options}|on_action=on_menu_action|label=Mixing Lab|width=260px|class_name=htt-menu|>

<|toggle|theme|class_name=theme-toggle|>

<|part|class_name=page-logo|
![Takeda](__TAKEDA_URI__)
|>

<|content|>
"""

root_md = root_md.replace("__LOGO_URI__", LOGO_DATA_URI).replace("__TAKEDA_URI__", TAKEDA_LOGO_URI)


pages = {
    "/": root_md,
    "Vessel_Database": vessel_database.page,
    "Fluid_Database": fluid_database.page,
    "Reaction_Database": reaction_database.page,
    "Particle_Database": particle_database.page,
    "Vessel_Assessment": vessel_assessment.page,
    "Vessel_Comparison": vessel_comparison.page,
    "Bourne_Protocol": bourne_protocol.page,
    "Mixing_Sensitivity": mixing_sensitivity.page,
    "Heat_Transfer": heat_transfer.page,
    "Unit_Converter": unit_converter.page,
    "Equations_Reference": equations_reference.page,
}

# The `part` element's `content` property needs a content provider for the bound
# type. Register one for `str` so the vessel viewer HTML is served as-is.
Gui.register_content_provider(str, lambda html: html)

# Takeda corporate palette applied to the MUI theme so every primary-coloured
# component (buttons, toggles, checkboxes, focused inputs) reads as Takeda red.
TAKEDA_THEME = {
    "palette": {
        "primary": {"main": "#E1251B"},
        "secondary": {"main": "#5C6670"},
    },
}

# if __name__ == "__main__":
#     Gui(pages=pages).run(title="Mixing Lab V2", use_reloader=True, port="auto",
#                          dark_mode=False, theme=TAKEDA_THEME)
    
# ------------------------------------------------------------------------------->
# Adding this for server deployment --------------------------------------------->

# ---- Module-level Gui instance (so Taipy sees the module's globals) ----
gui = Gui(pages=pages)

def create_app():
    """WSGI factory used by Gunicorn in production."""
    return gui.run(
        title="Mixing Lab 2.0",
        dark_mode=False,
        theme=TAKEDA_THEME,
        run_server=False,      # return the Flask app instead of starting a server
        use_reloader=False,
        debug=False,
        async_mode="gevent",
    )

if __name__ == "__main__":
    # Local development — same Gui instance, its own server, reloader on.
    gui.run(
        title="Mixing Lab 2.0",
        dark_mode=False,
        theme=TAKEDA_THEME,
        use_reloader=True,
        port="auto",
        debug=True,
    )

