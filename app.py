from __future__ import annotations

from pathlib import Path
import sys

if sys.version_info >= (3, 13):
    raise RuntimeError("Taipy GUI currently requires Python 3.12 or lower for this app. Please run with Python 3.12.")

from taipy.gui import Gui, navigate
from flask import Flask

from utils.menu_icons import image_thumb_uri, menu_icon_uri
from utils.usage import install_usage_logging

from pages import (
    bourne_protocol,
    crystallization_sensitivity,
    equations_reference,
    fluid_database,
    heat_transfer,
    home,
    mixing_sensitivity,
    particle_database,
    reaction_database,
    recorded_results,
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
    ("Home", "Home"),
    ("Vessel_Database", "Vessels"),
    ("Fluid_Database", "Fluids"),
    ("Reaction_Database", "Reactions"),
    ("Particle_Database", "Particles"),
    ("Vessel_Assessment", "Vessel Assessment"),
    ("Vessel_Comparison", "Vessel Comparison"),
    ("Bourne_Protocol", "Bourne Protocol"),
    ("Mixing_Sensitivity", "Reaction Sensitivity Protocol"),
    ("Crystallization_Sensitivity", "Crystallization Sensitivity Protocol"),
    ("Heat_Transfer", "Heat Transfer Tool"),
    ("Recorded_Results", "Recorded Results"),
    ("Unit_Converter", "Unit Converter"),
    ("Equations_Reference", "Equations Reference"),
]


def on_menu_action(state, action, info):
    page = info["args"][0]
    navigate(state, to=page)


def _logo_data_uri() -> str:
    """Return the sidebar logo as a small base64 ``data:`` URI ('' if missing)."""
    return image_thumb_uri(BASE_DIR / "images" / "general" / "logo.png", px=96)


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


# Per-item menu icons. Each menu key may supply a PNG at images/menu/[key].png
# (lowercase); when present a small cached thumbnail (utils/menu_icons.py)
# replaces the emoji fallback below.
MENU_ICON_EMOJI = {
    "Vessel_Database": "⚗️",
    "Fluid_Database": "💧",
    "Reaction_Database": "🧪",
    "Particle_Database": "🟤",
    "Vessel_Assessment": "🌀",
    "Vessel_Comparison": "⚖️",
    "Bourne_Protocol": "🅱️",
    "Mixing_Sensitivity": "🧭",
    "Crystallization_Sensitivity": "💎",
    "Heat_Transfer": "🔥",
    "Recorded_Results": "📋",
    "Unit_Converter": "🔄",
    "Equations_Reference": "📐",
}

_MENU_IMG_RULE = """.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(NTH) .MuiAvatar-root {
    background-color: #ffffff !important;
    background-image: url("IMG_URI");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    width: 44px !important;
    height: 44px !important;
    border-radius: 6px;
}"""

_MENU_EMOJI_RULE = """.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(NTH) .MuiAvatar-root::after {
    content: "EMOJI";
}"""


def _menu_icons_css() -> str:
    """Build the per-item icon CSS, preferring a PNG over the emoji fallback.

    nth-of-type(N) = menu position N-1 (position 1 is the drawer toggle), so a
    menu item at list index ``i`` maps to nth-of-type(i + 2). Home (index 0) is
    handled separately as the app logo.
    """
    blocks = []
    for i, (key, _label) in enumerate(menu_options):
        if key == "Home":
            continue
        nth = str(i + 2)
        img = menu_icon_uri(key)
        if img:
            blocks.append(_MENU_IMG_RULE.replace("NTH", nth).replace("IMG_URI", img))
        elif key in MENU_ICON_EMOJI:
            blocks.append(_MENU_EMOJI_RULE.replace("NTH", nth).replace("EMOJI", MENU_ICON_EMOJI[key]))
    return "\n".join(blocks)


root_md = """
<style>
/* The menu draws a round icon badge per item whose auto-generated letter mangles
   emoji into "?". Blank out that letter and inject a per-page emoji via ::after,
   so it shows in both the collapsed (icon-only) and expanded menu states. The
   first item is the native open/close drawer toggle and is left untouched. */
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
/* Home menu item (menu position 1, i.e. nth-of-type(2); nth-of-type(1) is the
   drawer toggle): show the app logo so clicking the logo navigates home. */
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(2) .MuiAvatar-root {
    background-color: #ffffff !important;
    background-image: url("__LOGO_URI__");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    width: 44px !important;
    height: 44px !important;
    border-radius: 6px;
}
/* Icon order follows the `menu_options` list: nth-of-type(N) = menu position
   N-1 (position 1 is the drawer toggle). Update these if you reorder the menu.
   Order: 2=Home (logo, above), 3=Vessels, 4=Fluids, 5=Reactions, 6=Particles,
   7=Vessel Assessment, 8=Vessel Comparison, 9=Bourne Protocol,
   10=Reaction Sensitivity, 11=Crystallization Sensitivity, 12=Heat Transfer,
   13=Recorded Results, 14=Unit Converter, 15=Equations Reference. Each item uses images/menu/[key].png
   when present, otherwise an emoji fallback (generated by _menu_icons_css). */
__MENU_ICONS__

/* Hide the "Mode" text label on the theme toggle; the sun/moon icons suffice. */
.theme-toggle .MuiTypography-root {
    display: none !important;
}

/* Inline menu-icon images embedded in page headings and Home links (see
   utils/menu_icons.py). Sized in em so the icon scales with its heading/text. */
img[alt="menu-icon"] {
    height: 1.1em;
    width: auto;
    vertical-align: -0.18em;
    margin-right: 0.3em;
    border-radius: 3px;
}

/* Page titles: centre every H1 and lift its inline menu icon above the text,
   matching the Home page's logo-over-heading layout. Section headings (h2+)
   and their inline icons are unaffected. */
h1 {
    text-align: center;
}
h1 img[alt="menu-icon"] {
    display: block;
    height: 72px;
    margin: 4px auto 6px;
    border-radius: 8px;
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

/* Explore-vessel properties column: cap at the 3D viewer height (380px) so the
   filter selector + table can never extend past the model panel. The table's
   wrapper flexes to fill the space left by the selector and scrolls internally. */
.vessel-props {
    height: 380px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.vessel-props .md-para:last-child {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
}
.vessel-props .vp-table {
    height: 100%;
}

/* Clean, fully-bounded frame around the 2D vessel schematic iframe (the browser
   default inset border clips its right edge without box-sizing). */
.vessel-schem iframe {
    box-sizing: border-box;
    width: 100% !important;
    border: 1px solid #D0D0D0 !important;
    border-radius: 4px;
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

/* Home page: centred app logo above the welcome heading, and equal-height
   cards inside each two-column row (cells stretch to the tallest card). */
.home-logo {
    text-align: center;
    margin: 4px 0 8px;
}
.home-logo img {
    height: 180px;
    width: auto;
}
.home-grid {
    align-items: stretch;
    margin-bottom: 20px;
}
.home-grid .va-card {
    height: 100%;
    margin-bottom: 0;
    box-sizing: border-box;
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

/* Symbol/Description/Units tables on the Equations Reference page: markdown
   tables parse into bare, unstyled table elements, so give them borders, a
   shaded header row and zebra striping. Scoped to .eq-sec to avoid touching
   Taipy's MUI data tables elsewhere. */
.eq-sec table {
    border-collapse: collapse;
    margin: 6px 0 14px 0;
    font-size: 0.92em;
}
.eq-sec th, .eq-sec td {
    border: 1px solid #d7d9dc;
    padding: 4px 12px;
    text-align: left;
}
.eq-sec th {
    background: #f2f3f5;
    font-weight: 600;
}
.eq-sec tbody tr:nth-child(even) td {
    background: #fafbfc;
}
.taipy-dark .eq-sec th, .taipy-dark .eq-sec td {
    border-color: #4a4f55;
}
.taipy-dark .eq-sec th {
    background: #2e3338;
}
.taipy-dark .eq-sec tbody tr:nth-child(even) td {
    background: rgba(255,255,255,0.04);
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
root_md = root_md.replace("__MENU_ICONS__", _menu_icons_css())


pages = {
    "/": root_md,
    "Home": home.page,
    "Vessel_Database": vessel_database.page,
    "Fluid_Database": fluid_database.page,
    "Reaction_Database": reaction_database.page,
    "Particle_Database": particle_database.page,
    "Vessel_Assessment": vessel_assessment.page,
    "Vessel_Comparison": vessel_comparison.page,
    "Bourne_Protocol": bourne_protocol.page,
    "Mixing_Sensitivity": mixing_sensitivity.page,
    "Crystallization_Sensitivity": crystallization_sensitivity.page,
    "Heat_Transfer": heat_transfer.page,
    "Recorded_Results": recorded_results.page,
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
# Taipy runs on this externally-created Flask app so the usage-logging hook
# (data/usage.db, one row per app load — see utils/usage.py and usage_report.py)
# is active in both the local-dev and gunicorn deployment paths.
# path_mapping serves the 3D-viewer script and vessel media as cacheable static
# URLs (/vassets, /vimages) instead of megabyte base64 blobs in state variables.
_flask_app = Flask(__name__)
install_usage_logging(_flask_app, pages.keys())


@_flask_app.after_request
def _media_cache_headers(resp):
    """Let browsers cache the vessel models/script for a day (Taipy's default
    is no-cache, which re-validates the multi-MB GLBs on every page view)."""
    from flask import request

    if request.path.startswith(("/vimages/", "/vassets/")) and resp.status_code == 200:
        resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


# gzip/brotli responses when flask-compress is available (GLB models and the
# 0.9 MB viewer script shrink to ~25%). Optional: the app runs fine without it.
try:
    from flask_compress import Compress

    _flask_app.config["COMPRESS_MIMETYPES"] = [
        "text/html", "text/css", "application/json", "application/javascript",
        "text/javascript", "image/svg+xml",
        "model/gltf-binary", "model/gltf+json", "application/octet-stream",
    ]
    Compress(_flask_app)
except ImportError:
    pass

gui = Gui(pages=pages, flask=_flask_app,
          path_mapping={"vimages": str(BASE_DIR / "images"),
                        "vassets": str(BASE_DIR / "assets")})

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

