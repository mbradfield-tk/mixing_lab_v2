# Vessel-height clarification — code changes

> **Status:** historical snapshot. Describes the code as of commit `a6d920c` (2026-09-16); the referenced
> branch may no longer exist and later commits have changed some of these files. Last reviewed 2026-10-05
> (calculation pages now read the dish height via `pages/_db_common.bottom_dish_height`, which uses the
> real CSV column `H_bot_dish_m`).

Date: 2026-09-16. Committed as `a6d920c` ("CSV Overhaul") on branch `fix_blend_time`, 2026-09-16 16:49.
To see the exact diff: `git show a6d920c` (13 files, +662 / −68).
Companion documents: `README_csv_changes.md` (data edits) and `README_reactor_review.md` (rows to re-verify).

## Why

`data/reactors.csv` described vessel height with two columns whose meaning was ambiguous:

| old column | what it actually held |
|---|---|
| `H_m` | straight-wall length between the bottom and top tangent lines (tan-tan) — **not** a full height |
| `H_max_m` | bottom-dish apex → top tangent line = maximum fill height |

The bottom-dish height was never stored; every page inferred it from the `bottom_dish` text with a different
rule of thumb, so the Vessel Database picture, the Vessel Assessment / Bourne / Vessel Comparison numbers and the
CSV disagreed with each other. The new scheme:

```
                 ┌──────── top dish ────────┐
 H_m (Full Height, ┤                          ├  ← top tangent line
  new, EMPTY)      │                          │
                   │      L_tan_tan_m         │  ← straight wall (was "H_m")
 H_max_m           │                          │
 (unchanged)       ├──────────────────────────┤  ← bottom tangent line
                   └──── H_bot_dish_m ────────┘  = H_max_m − L_tan_tan_m
```

Fallback rule used everywhere: **use `H_max_m` as the fill cap; only if it is blank, use `L_tan_tan_m` as an
approximation.** Nothing reads the new `H_m`.

---

## 1. `data/reactors.csv` (structure only — values are in `README_csv_changes.md`)

| change | detail |
|---|---|
| column renamed | `H_m` → `L_tan_tan_m` (column 11) |
| column added | `H_bot_dish_m` (column 13) = `H_max_m − L_tan_tan_m`, populated for every row that has both |
| column added | `H_m` (column 14), **empty** — reserved for "Full Height" (dish apex → top-dish top) |
| header now | `…,D_tank_m,L_tan_tan_m,H_max_m,H_bot_dish_m,H_m,D_imp_m,…` (70 columns, 42 rows) |

File written byte-preserving: UTF-8 no BOM, LF line endings, no trailing newline, `csv` module quoting.
`data/bkp/*.csv` snapshots still carry the old `H_m` header and were **not** touched.

> ⚠ **Do not import a legacy CSV** through the Vessel Database *Import* dialog. Its `H_m` column (tan-tan
> values) would be written into the new, empty *Full Height* column. No guard was added (by decision).

---

## 2. `pages/_db_common.py` — column labels

```diff
-    "H_m": "Tank Height [m]",
-    "H_max_m": "Max Liquid Height [m]",
+    "L_tan_tan_m": "Tan-Tan Length [m]",
+    "H_max_m": "Max Fill Height [m]",
+    "H_bot_dish_m": "Bottom Dish Height [m]",
+    "H_m": "Full Height [m]",
```
Affects the Vessel Database property picker / detail table labels only.

---

## 3. `pages/heat_transfer.py` + `heat_transfer_core.py` — fallback rename **and dish-aware liquid height (behaviour change)**

### 3a. Fallback rename (lines 118, 239, 559 — no behaviour change)
```diff
-h_max = safe_float(_r.get("H_max_m"), safe_float(_r.get("H_m"), 0.2))
+h_max = safe_float(_r.get("H_max_m"), safe_float(_r.get("L_tan_tan_m"), 0.2))
```

### 3b. Liquid height now accounts for the bottom dish (behaviour change)
`pages/heat_transfer.py` imports `liquid_height_from_volume` from **`heat_transfer_core.py`**, which had its
**own** implementation — a flat cylinder `H = V / (π R²)` with **no dish term** — while every other page uses the
dish-aware `utils/calculations/geometry.py` version. Two same-named functions, different answers.

`heat_transfer_core.liquid_height_from_volume` now delegates to the shared geometry function (no circular import —
`geometry.py` only depends on `re`/`numpy`); `bottom_dish` is optional so the old 3-argument call still works:
```diff
-def liquid_height_from_volume(V_L: float, D_tank: float, H_max: float) -> float:
-    if V_L <= 0 or D_tank <= 0:
-        return 0.0
-    V_m3 = V_L / 1000.0
-    H = V_m3 / (np.pi * (D_tank / 2) ** 2)
-    return min(H, H_max) if H_max > 0 else H
+def liquid_height_from_volume(V_L: float, D_tank: float, H_max: float, bottom_dish: str = "") -> float:
+    from utils.calculations.geometry import liquid_height_from_volume as _dish_aware
+    return _dish_aware(V_L, D_tank, H_max, bottom_dish)
```
and the three call sites in `pages/heat_transfer.py` (module defaults ~line 119, `_refresh_area`, `_build_ua_sweeps`)
now pass `bottom_dish` — the value was already being read for `estimate_jacket_area` on the next line.

**Effect:** the old formula spread the dish volume over a full-diameter cylinder, so it under-read the wetted height
by roughly the dish depth, and the jacket area (hence **UA**) was under-reported. At the default fill:

| vessel | dish | old height | new height | jacket area |
|---|---|---|---|---|
| RX-001 R-3156 | 2:1 Elliptical | 1669 mm | 1783 mm | +6.4 % |
| RX-009 R-301 | 45° conical | 1108 mm | 1432 mm | **+33.5 %** |
| RX-013 Polyclave | Hemispherical | 175 mm | 189 mm | +7.0 % |
| RX-021 Nalas 5 L | DIN Torispherical | 154 mm | 167 mm | +7.4 % |
| RX-041 15 L Buchi | 2:1 Elliptical | 200 mm | 219 mm | +8.8 % |
| RX-042 30 Kilo GLS | Torispherical | 171 mm | 203 mm | +15.0 % |

Anyone who calibrated against earlier Heat Transfer page outputs should expect UA to rise by these amounts.

---

## 4. `pages/vessel_assessment.py` — fallback rename (3 sites, no behaviour change)

Lines 557, 602, 744:
```diff
-    h_max = _sf(row.get("H_max_m"), _sf(row.get("H_m"), tank_d))
+    h_max = _sf(row.get("H_max_m"), _sf(row.get("L_tan_tan_m"), tank_d))
```

---

## 5. `pages/bourne_protocol.py` — fallback rename (1 site, no behaviour change)

Line 110:
```diff
-    max_height = _sf(row.get("H_max_m"), _sf(row.get("H_m")))
+    max_height = _sf(row.get("H_max_m"), _sf(row.get("L_tan_tan_m")))
```

---

## 6. `pages/vessel_comparison.py` — **behaviour change** (approved)

This page previously used the tan-tan length **directly** as the fill cap / geometric-volume basis, unlike every
other page. It now follows the common rule. Lines 476–479 and 626–630:
```diff
-        D_imp, D_tank, H_max = _sf(r.get("D_imp_m")), _sf(r.get("D_tank_m")), _sf(r.get("H_m"))
+        D_imp, D_tank = _sf(r.get("D_imp_m")), _sf(r.get("D_tank_m"))
+        # Max fill height caps the liquid level; tan-tan length is only an
+        # approximation used when H_max_m is not recorded.
+        H_max = _sf(r.get("H_max_m"), _sf(r.get("L_tan_tan_m")))
```
Effect: `H_max` for every compared vessel is now larger by the bottom-dish height (e.g. Cambrex R-3156
3.048 → 3.381 m), so liquid-height caps and H/D-type ratios on this page changed accordingly.

---

## 7. `vessel_schematic.py` — Vessel Database 2D schematic

### 7a. Column rename (line 107)
```diff
-    H = _f(row, "H_m")
+    H = _f(row, "L_tan_tan_m")  # straight-wall (tan-tan) length
```

### 7b. **Bottom-dish depth now comes from the CSV** (behaviour change, approved)
Previously the dish was drawn with a depth guessed from the `bottom_dish` text (`_dish_depth`: hemi = R,
2:1 elliptical = 0.5 R, torispherical = 0.34 R, "dish" = 0.2 R, unknown = 0.2 R…). It now uses the measured value:

```python
def _bottom_dish_depth(row, dish_type, radius):
    """Bottom-dish height (m): CSV H_bot_dish_m, else H_max_m - L_tan_tan_m, else type heuristic."""
    depth = _f(row, "H_bot_dish_m", nan)
    if not isfinite(depth):
        depth = H_max_m - L_tan_tan_m   (if both > 0)
    if isfinite(depth) and depth >= 0:
        return depth
    return _dish_depth(dish_type, radius)          # heuristic only as a last resort
```
and in `_geometry`:
```diff
-    bot_depth, top_depth = _dish_depth(bottom, R), _dish_depth(top, R)
-    bot_shape, top_shape = _dish_shape(bottom), _dish_shape(top)
+    bot_shape, top_shape = _dish_shape(bottom), _dish_shape(top)
+    top_depth = _dish_depth(top, R)
+    bot_depth = _bottom_dish_depth(row, bottom, R)
+    if bot_depth > 0 and bot_shape == "flat":
+        bot_shape = "curved"          # a flat/blank label with a real dish height is drawn as an arc
```
The dish **shape** (arc / cone / flat) still comes from the type; only the **depth** is measured. Top dish is
unchanged (heuristic). Consequences: the schematic's top tangent line now lands exactly on `H_max_m`; brim-full
volume, liquid level, impeller clearance origin and the "impeller cuts into the dish" check all use the true depth.

Unchanged but worth knowing: the schematic subtracts an **impeller metal displacement** (20 % solidity of each
impeller's swept cylinder, `_IMP_SOLIDITY`, present since commit `16afa23`, 2026-08-10). No calculation page does
this, so schematic vs. calculation liquid levels differ by that amount (up to ~30–50 mm on the large Cambrex
vessels).

---

## 8. `utils/calculations/geometry.py` — `dish_geometry()` (used by Vessel Assessment, Bourne, Vessel Comparison and — since §3b — Heat Transfer)

Two new branches, inserted **before** the torispherical one; torispherical/conical/default numbers unchanged.

```diff
     if "conic" in dish:
         h_dish = cone_depth(D_tank, dish)
         V_dish = np.pi / 12 * D_tank**2 * h_dish
-    elif "torisph" in dish or "din" in dish or "dished" in dish:
+    elif "hemi" in dish or "round" in dish:
+        # hemispherical head: depth = R, volume = 2/3 pi R^3
+        h_dish = D_tank / 2
+        V_dish = np.pi * D_tank**3 / 12
+    elif "dished" in dish:
+        # shallow spherical cap, depth 0.1 D (consistent with the schematic heuristic 0.2 R)
+        h_dish = 0.10 * D_tank
+        V_dish = np.pi * h_dish * (3 * (D_tank / 2) ** 2 + h_dish**2) / 6
+    elif "torisph" in dish or "din" in dish:
         h_dish = 0.1935 * D_tank
         V_dish = 0.0847 * D_tank**3
     else:                      # unchanged: 2:1 ellipsoidal default, h = D/4, V = pi D^3 / 24
```

| label contains | before | after |
|---|---|---|
| `hemi` / `round` | default D/4 ellipsoid | **hemisphere h = D/2** |
| `dished` | torispherical 0.1935 D | **shallow cap h = 0.1 D** |
| `torisph` / `din` | 0.1935 D, 0.0847 D³ | unchanged |
| `conic` | from angle | unchanged |
| anything else (incl. `2:1 Elliptical`, `Spherical`) | D/4 | unchanged |

Affects any vessel labelled Hemispherical (RX-013, 014, 036, 037) or Dished (RX-015, 017, 027) on the
calculation pages. **`estimate_jacket_area` (heat-transfer area) was not changed** — it has no hemispherical or
dished branch and treats those labels as flat for wetted area.

---

## 9. `.gitignore` — new file (untracked before)

```
*.pyc

# Local diagnostic: dish-height comparison script and its generated report
scripts/dish_height_comparison.py
scripts/dish_height_comparison_gui.py
scripts/dish_height_comparison_out/
```

---

## 10. Diagnostic scripts (git-ignored, local only)

| file | purpose |
|---|---|
| `scripts/dish_height_comparison.py` | For every vessel computes liquid height vs volume two ways — **B** = CSV dish height via the schematic's integration, **C** = `liquid_height_from_volume()` (calculation pages) — and writes an HTML + CSV report to `scripts/dish_height_comparison_out/`. `--classify D h` prints the best-matching standard head (or equivalent cone angle) for a diameter and dish height. |
| `scripts/dish_height_comparison_gui.py` | tkinter window: real Vessel Database schematic on the left, B-vs-C curves on the right, level table, AGREE/DISAGREE verdict (C−B as % of `H_max_m`, limit 1 %), and a dish-type finder. Run with `conda activate mixer && python scripts\dish_height_comparison_gui.py [RX-013]`. Only vessels with `D_tank_m`, `L_tan_tan_m`, `H_max_m` and `bottom_dish` are listed. |

Method definitions:
- **B (CSV)** — dish depth `H_bot_dish_m`, shape from `bottom_dish`, numeric capacity curve (400-pt trapezoid) incl. impeller displacement. This is exactly what the Vessel Database schematic draws.
- **C (analytic)** — `geometry.dish_geometry()` depth/volume from the type formula, straight-wall algebra, no impellers, capped at `H_max_m`. This is what Vessel Assessment / Bourne / Vessel Comparison / Heat Transfer compute with.

---

## 11. Things deliberately **not** changed

- `heat_transfer_core.estimate_jacket_area` / `utils.calculations.heat_transfer.estimate_jacket_area` — no hemispherical/dished branch (those labels are treated as flat for wetted **area**; the wetted **height** feeding them is now dish-aware, see §3b).
- `vessel_schematic._IMP_SOLIDITY` impeller displacement (20 %).
- Schematic draws every curved dish as an **elliptical arc**; a true torispherical head is flatter, so B holds slightly more dish volume than C's `0.0847 D³` (visible on RX-040, +2 %).
- `data/bkp/*.csv` legacy snapshots.
- No import guard for legacy CSVs.

## 12. Verification performed

- All pages import; `tests/test_bourne_protocol_regression.py` + `tests/test_liquid_liquid.py` — 23 runnable test functions pass (pytest is not installed in `mixer`; `test_miscibility.py` needs it and two Bourne tests need the `monkeypatch` fixture).
- CSV: 70 columns × 42 rows, LF, no trailing newline, `H_bot_dish_m == H_max_m − L_tan_tan_m` for all 39 populated rows, `H_m` blank everywhere.
- `tests/test_liquid_liquid.py` was accidentally overwritten by a stray keystroke during GUI testing and **restored from git** (`git checkout -- tests/test_liquid_liquid.py`); 4/4 pass.

## 13. Runtime warnings that are **not** caused by these changes

Seen in the `python app.py` console after the change set, and investigated 2026-09-17:

```
Session id … not found in data scope. Taipy will automatically create a scope … you may have to reload your page.
A problem occurred while resolving variable 'selected_vessel_TPMDL_9' in module '__main__'.
__process_content_provider() callback function raised an exception:
    AttributeError: 'types.SimpleNamespace' object has no attribute '_TpCh_tpec_TpExPr_vessel_schematic_html_TPMDL_9'
```

All three are one event: `app.py` runs with `use_reloader=True, debug=True`, so every save of a `.py` file restarts
the server process. The browser tab keeps the **old** session id; the new process has no data scope for it, Taipy
stubs an empty scope, and anything the page asks for from that scope — state variables (`selected_vessel`,
`bp_reactor`) or the `<|part|content=…|>` HTML providers for the schematic / 3D viewer — is missing. `_TPMDL_9` /
`_TPMDL_25` are Taipy's per-module suffixes (Vessel Database / Bourne Protocol). **Refresh the browser tab (F5)
after any "Server reloaded" line** and the warnings stop; no data or calculation is affected.

The reloader watches every directory on `sys.path`, and `sys.path[0]` is the repo root, so saving *any* `.py`
under `mixing_lab_v2/` — including the git-ignored `scripts/dish_height_comparison*.py` and the `tests/` — triggers a
restart. Run with `use_reloader=False` while editing side scripts if this is a nuisance.

---

## 14. P0 modularization (2026-10-06): behaviour changes

This is the back-end-seams refactor from [README_react_migration_plan.md](README_react_migration_plan.md). Every calculation result, golden page output and PDF snapshot is unchanged. Only the items below behave differently.

**14a. Admin login (security fix).**

- The built-in default credentials are gone.
- Admin editing on the Vessel and Reaction databases only works when **both** `MIXING_LAB_ADMIN_USER` and `MIXING_LAB_ADMIN_PW` are set in the environment.
- Without them, the Admin panel says *"Admin editing is disabled on this server — set … to enable it."*
- **For local editing, start the app with the two variables set.**

**14b. Reaction Database "Add reaction" now needs admin.** The add form previously wrote to `reactions.csv` even while the table was locked. The write policy now lives in the repository (`core/auth.PROTECTED_TABLES`), so every reaction write is gated.

**14c. Stricter add-form validation** (`core/schemas.py` record models).

- **Particles:**
  - density and D10/D50/D90 must be > 0;
  - the shape factor must be > 0;
  - the size order rule is unchanged.
- **Custom fluids:**
  - ρ, μ, D, Cp and k must be > 0;
  - σ and the Hansen parameters must be ≥ 0.
- **Error wording.** Messages for non-numeric input now name the field, for example "Particle Density [kg/m³]: Input should be a valid number…", instead of the old generic "must be numeric".

**14d. Fluid dropdowns are de-duplicated.**

- Vessel Assessment and Bourne Protocol used to concatenate library solvents and custom fluids, so a custom fluid named like a solvent appeared twice. They now use `catalog.fluid_names()`: sorted and unique, the same list Heat Transfer already used.
- Vessel Comparison keeps its "library first, then custom" order (`catalog.fluid_names_grouped()`).

**14e. Option lists have one source.**

- Reactor, reaction, fluid and particle dropdowns on the analysis pages now come from `core/catalog.py`, which reads the mtime-cached repositories, instead of each page's own `pd.read_csv`.
- The Taipy pages still build these lists once at import, so they still need a restart to show new database rows.
- The API's `options()` service reads them live on every call.

**14f. Unused code removed.**

- `pages/_db_common.py` no longer defines the CSV helpers. They live in `core/tables.py`, and `_db_common` re-exports them.
- The per-page copies of the Bourne verdict text, the fluid blend calculation and the VC scale-up/heat-summary loops were replaced by calls into `core/`.

---

## 15. P1 HTTP API (2026-10-06): behaviour changes

The new FastAPI app (`api/`) adds routes and changes nothing in the Taipy pages' calculations. Golden outputs, all 180 vessel schematics and all 483 Unit Converter cases are byte-identical. The items below behave differently.

**15a. Particles and custom fluids now need admin to edit** (decision of 2026-10-06).

- `core/auth.PROTECTED_TABLES` is now reactors, reactions, particles and fluids.
- The Particle Database and Fluid Database pages show the same Admin panel as the Vessel and Reaction pages.
- While locked, their tables are read-only and the add-form button and CSV import are disabled.
- **Recorded results stay open to the local user:** saving and "clear all" need no login.

**15b. Saved results are validated.**

- `ResultsRepository.append` checks each row against the new `RecordedResult` schema.
- The reactor name is required, numbers must be numbers, and unknown columns are rejected.
- Rows are always written with the full `recorded_results.csv` header in its fixed order. Missing values are left blank, as before.

**15c. Vessel media IDs are sanitised.** `core/media.find_vessel_media` only accepts reactor IDs made of letters, digits, `_`, `.` and `-`, with no `..`. Every current ID passes (34 of 44 vessels still resolve to media). The check stops path-traversal through the new `/media/vessels/...` routes.

**15d. Appending to an empty results file.** `core/csv_store.append_csv` no longer concatenates onto a header-only frame. This silences a pandas FutureWarning; the written CSV is the same.

**15e. Files moved** (with `git mv`; import paths changed, behaviour did not):

| Before | After |
|---|---|
| `utils/report_builder.py` | `reports/pdf.py` |
| `utils/menu_icons.py` | `pages/_menu_icons.py` |
| `pages/_vessel_media.py` media lookup | `core/media.py` |
| `viz/vessel_schematic.py` geometry / capacity / fill state | `core/vessel_capacity.py` |
| Unit Converter tables | `core/units.py` |
| Home `APP_VERSION` | `core/version.py` |

**15f. New dependencies:** `fastapi`, `uvicorn[standard]`, `python-multipart` and `itsdangerous` (runtime), plus `httpx` (tests). See `requirements.txt`.

**15g. Lint clean-up.**

- Unused locals and an unused import were removed from `reports/pdf.py`.
- The duplicate `"type"` key in `COLUMN_LABELS` was removed. Its later value ("Reaction Type") already applied, so labels are unchanged.

---

## 16. P2 start (2026-10-06): React front end and API cache

The Taipy app is unchanged; its menu icons now come from `core.media.thumbnail` (the same `images/menu/.thumbs/` cache).

**16a. The API serves the React app.**

- When `web/dist` exists (run `npm run build` in `web/`), `uvicorn api.main:app` serves it at `/app`, and `/` redirects there instead of to `/api/v1/docs`.
- Page loads under `/app` are written to `data/usage.db` as `app:<path>`.

**16b. Slow API results are cached in memory.**

- **Covered:** PDFs, charts, 3D surfaces, comparisons and scale-up results.
- **Lifetime:** until any file in `data/` changes, the date changes, or the process restarts.
- A second identical request returns the stored result instead of recomputing it.

**16c. New route:** `GET /api/v1/media/icons/{key}?px=48|96|192|240|360` returns cached menu-icon / logo thumbnails (`key = logo` for the app logo). The favicon is now a 48 px thumbnail instead of the 0.8 MB logo.

**16d. New tooling.**

- `web/` holds the React app. Its `node_modules/` and `dist/` are git-ignored.
- Node.js 22 is installed in a separate conda env, `mixing_lab_web`; the Python env is unchanged.

**16e. Equations are real LaTeX in the React app (API contract change).**

- `GET /api/v1/equations` now serves `data/equations_source.json` (raw LaTeX), typed as `EquationsResult` (`EquationSection` → `EquationItem{type, text, latex, level:int}`). It no longer returns the base64 PNGs, so the payload falls from about 258 kB to about 66 kB.
- The React page renders display equations with KaTeX, and inline `$...$` in text, tables and headers with `remark-math` + `rehype-katex`. All 80 display and 287 inline fragments render with no errors. Search also matches the LaTeX source.
- **Security:** raw HTML is sanitised *before* KaTeX runs, so only KaTeX's own markup is trusted. A KaTeX error shows as red source text instead of breaking the page (`throwOnError: false`).
- The Taipy page is unchanged. It still reads the pre-rendered `data/equations_reference.json`, so keep running `scripts/build_equations.py` after editing the source until Taipy is retired. After that, the PNG JSON and the matplotlib build step can be deleted.

**16f. React Particle, Reaction and Fluid database pages (no back-end behaviour change).**

- New pages at `/app/particles`, `/app/reactions` and `/app/fluids`; the sidebar now opens them in the React app instead of Taipy. The Taipy pages remain available at their old URLs.
- **Same write policy as Taipy:** all writes need the admin login. Credentials come from `MIXING_LAB_ADMIN_USER` / `MIXING_LAB_ADMIN_PW`, and tokens are signed with `MIXING_LAB_API_SECRET`.
  - The browser keeps the token in memory only, so reloading the page locks editing again.
  - Set `MIXING_LAB_API_SECRET` in deployment; otherwise tokens stop working whenever the server restarts.
- **Difference from Taipy:** editing and deleting are allowed while a search is active, because the API addresses rows by name rather than row position.
- **New web dependency:** `plotly.js-dist-min` **3.7.0**, pinned to match Python plotly 6.9's plotly.js. Upgrade the two together.

**16g. React Vessel Database, Recorded Results and Crystallization Sensitivity pages.**

- New pages at `/app/vessels`, `/app/recorded-results` and `/app/crystallization-sensitivity`; the sidebar links there now. The Taipy pages remain available.
- **Back-end fix:** `POST /api/v1/vessels` (create) now assigns a `reactor_id` and `search_name`, as adding a blank row and importing already did. Previously, an API-created vessel had neither (`ReactorRepository.create`).
- **Vessel import review in React:** the browser keeps the uploaded file and sends the accepted change IDs to `/import/apply`. The server recomputes the changes from the file, so the result is the same as Taipy's dialog.

**16h. React Vessel Assessment page and its API support.**

- New page at `/app/vessel-assessment`; the Taipy page remains.
- **New endpoints:**
  - `POST /assessment/tables` (formatted result tables);
  - `GET /assessment/parameters`;
  - `GET /assessment/vessel-defaults/{name}`;
  - `POST /assessment/save`;
  - `GET /fluids/properties`.
- **Shared code moved out of the Taipy page (no behaviour change):** the envelope parameter list (`core.envelope.ENVELOPE_PARAMETERS` / `DEFAULT_ENVELOPE`) and the Recorded-Results row (`core.services.recorded_result_row`).
- **Fix:** the assessment PDF from `POST /reports/assessment` printed the pressure as 1 atm regardless of the request. It now uses `point.fluid.P_atm`, as the Taipy page always did.

**16i. React Vessel Comparison page and its API support.**

- New page at `/app/vessel-comparison`; the Taipy page remains.
- **New endpoints:** `POST /comparison/setup`, `POST /comparison/tables`, `POST /comparison/save` (returns `{saved, count}`) and `GET /kinetics/defaults`.
- **Shared code moved out of the Taipy page (no behaviour change; golden outputs identical):** the table formatting (`reports/comparison_tables.py`) and the setup/save helpers (`core.scale_up`).
- **Small UI difference:** the React page loads the basis vessel's mid-range RPM and volume as soon as scale-up is shown. Taipy started at 100 RPM / 1 L until the basis was changed.
