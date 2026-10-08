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

**16j. React Heat Transfer page and its API support.**

- New page at `/app/heat-transfer`; the Taipy page remains.
- **API (additive, no change to existing results):**
  - `HeatTransferRequest` gained optional overrides (`rho_kg_m3`, `mu_Pa_s`, `cp_J_kgK`, `k_W_mK`, `cp_jacket_J_kgK`, `wall_k_W_mK`, `lining_k_W_mK`, `lining_thickness_mm`). The API can now reproduce any edited Taipy input; previously these were always looked up.
  - `UaSurfaceRequest` gained `U_color_range` / `UA_color_range`.
  - New: `GET /heat-transfer/options`, `GET /heat-transfer/defaults/{vessel}`, `GET /heat-transfer/area`, `GET /fluids/thermal`.

**16k. React Bourne Protocol page and its API support.**

- New page at `/app/bourne-protocol`; the Taipy page remains.
- **Shared code moved out of the Taipy page (no behaviour change; golden outputs identical):**
  - table formatting → [reports/bourne_tables.py](../reports/bourne_tables.py);
  - the suggested KPI names and units → `utils.bourne_kpi.RESPONSE_METRICS` / `KPI_UNITS`.
- **New endpoints (additive):**
  - `POST /bourne/plan/tables`: the formatted Test 1–3 condition tables, the fed-batch setpoints and their caption, and the centre-point caption.
    - Test 3 uses the page label "Sub-surface (mid)"; the PDF keeps "Sub-surface (mid-tank)".
  - `GET /bourne/options`: KPI column names, suggested metrics and units, unit operations.
  - `GET /bourne/defaults/{vessel}`: mid-range working volume and centre RPM, plus the reactor-limits table.
  - `POST /bourne/sensitivity-csv`: the hand-off CSV for the Reaction Sensitivity Protocol. It is byte-identical to the Taipy export.
- **UI differences:**
  - **Downloads:** the PDF and the Sensitivity CSV download directly. Taipy had a Generate step, then a Download step.
  - **Assessment validity:** each test's result is tied to the inputs it depends on, plus the KPI tables of Tests 1..N:
    - Test 1: the system and centre point;
    - Test 2: adds the feed inputs;
    - Test 3: adds the location ratios.
    
    Editing an input hides that test's verdict and every later one, as Taipy's invalidation did. Restoring the exact earlier values brings the result back.
  - **New notice type:** a `warning` notice (amber).

**16l. React Reaction Sensitivity Protocol page and its API support.**

- New page at `/app/reaction-sensitivity`; the Taipy page remains.
- **New endpoints (additive):**
  - `POST /sensitivity/page`: Steps 0–5 Markdown, the kinetics / ΔT_ad / Da / t_rxn captions, the summary note, the verdict, findings and next steps, built from the same `rules.protocol_md` as the Taipy page.
  - `GET /sensitivity/options`: reaction orders, ΔH reference reactions with their values, unit operations.
  - `GET /sensitivity/reaction-defaults?reaction=&T_C=`: database kinetics, reaction type, raw solvent and the solvent ρ·Cp.
    - The reaction is a query parameter because names can contain `/`.
  - `POST /sensitivity/bourne-import` (multipart): parses a Bourne results CSV with `core.bourne_io.parse`, with the same error messages as Taipy. Uploads are capped at the database-import size limit.
- **Contract change:** `ProtocolReportRequest` gained `bourne_meta`, so the PDF can carry the imported Bourne metadata as the Taipy PDF does.
- **UI differences:**
  - **Live results:** once started, the results update live from a debounced request. "Update assessment" forces a refresh.
  - **PDF:** downloads directly.

**16m. Results shown as dashboards instead of tables (React only; Taipy and PDFs unchanged).**

- **Shared components:** `web/src/components/Insights.tsx`, with severity colours taken from the server's traffic-light icons or status codes:
  - a verdict banner;
  - finding cards;
  - stat tiles;
  - a numbered action list;
  - a stage tracker;
  - a change-vs-threshold bar.

  Each source table is still available under "Show as table", with its CSV download.
- **Result tables:** any cell that starts with 🔴 / 🟡 / 🟢 / ⚪ / ⚠️ / ✅ now renders as a coloured pill. This includes the Vessel Comparison and scale-up status columns.
- **Bourne Protocol:**
  - **Each test:** a verdict banner, plus one card per KPI with its max change, a bar against the threshold, the three responses, and a "critical KPI" or "Within noise" marker.
  - **Summary:** a dominant-regime banner, a Test 1–3 tracker, and tiles for tests assessed, P/m span, sensitive KPIs and the next step.
- **Reaction Sensitivity:**
  - **Summary:** a verdict headline banner, severity-count tiles, finding cards ordered most severe first, Bourne finding cards and numbered next steps.
  - **Step result boxes:** coloured by severity.
  - **Steps renumbered 1–9 (React only):** the Bourne pre-screen is now Step 1. The semi-batch switch moved out of Kinetics into a new **Step 4 – Feed Mode (Mesomixing)**, which has a short explanation and a batch or semi-batch result box. Competing Reactions, Heat, Mixing Time, Summary and Export follow as Steps 5–9.
    - The API keeps `steps[0..5]`, so the Taipy page and PDF are unchanged.
    - The page uses its own pending note and export message ("Steps 2, 3, 5 and 6"), because the server's `SUMMARY_PENDING` text is shared with Taipy and its golden snapshots.
  - **Step 7, Mixing Time vs Reaction Time:**
    - The introduction is cut to two sentences, and the formulas and scale-up note sit in a collapsed "How it's calculated" (KaTeX).
    - The results show as tiles: t_rxn, plus θ₉₅, t_E, Da_macro and Da_micro (coloured by band) when a vessel is selected.
    - A log scale shows Da_micro and Da_macro against the 0.1 / 1 thresholds, or t_rxn against the reaction-speed bands when no vessel is selected.
    - The vessel and operating point appear on one line.
    - The new `LogScale` component is in `components/Insights.tsx`.
  - **API (additive):** `ProtocolPage.t_rxn_s` and `ProtocolPage.damkohler` (the same values as `/sensitivity/assess`, via the new `services.screening_damkohler_out`).
  - The Bourne page's export text now refers to "Step 1 pre-screen".
- **Vessel Assessment:** Damköhler regime cards come first. Hydrodynamics are shown as tiles, with six headline values. Mass-transfer screening uses cards. Solids and heat balance use tiles, with the suspension state and the balance colour-coded.
  - **Solve-for:** the outcome is shown as four tiles:
    - the solved N or V, coloured green (solved), amber (outside the vessel window) or red (no solution, with the achievable range);
    - the target;
    - the input held fixed;
    - the vessel window.
    
    The roots table now appears only when there is more than one solution.
- **Heat Transfer:** core KPIs and both summaries are shown as tiles.
- **Vessel Assessment, inputs and fed-batch filling (React):**
  - **Card 1** is renamed "1. Vessel".
  - **Sliders:** agitation speed and **fill volume** (renamed from "working volume" on this page) have a slider next to the number box.
    - The slider spans the vessel range from `GET /assessment/vessel-defaults`, which now returns `N_rpm_range` / `V_L_range` (the same fallbacks as the operating envelope).
    - The slider increment is about 20 steps for spans under 10 and about 100 steps above that, rounded to 1/2/5. For example, a 100 mL span steps by 5 mL, a 1000 L span by 10 L, and 50–1000 RPM by 10 RPM.
    - Typed values may go outside the range; the slider then shows "outside vessel range".
  - **Fed-batch inputs:**
    - **Dosing Time [h]** and **Dosing Amount [L]**. **Feed rate [mL/min]** is now calculated from them (read-only); it was an input that the calculation never used.
    - **Dosed fluid**, chosen from the Fluids database.
    - A **Simulate Filling** checkbox.
  - **Filling simulation (new):** on Compute, `POST /assessment/filling` and the `assessment-filling` chart (`services.filling`, `viz/filling.py`) re-evaluate the operating point at 50 steps over the dosing time.
    - The fill volume runs from V to V + dosing amount.
    - At each step the liquid is a volume blend of the initial and dosed fluids, using the Fluid Database blend rules (new `fluids.volume_blend`).
    - The **Filling Dynamics** section shows start → end tiles; plots against time for fill level and blended ρ/μ/ν/σ/D, hydrodynamics, mass transfer, Damköhler numbers (log axis, 0.1/1 thresholds) and heat transfer; and a data table / CSV.
    - It warns when the final volume exceeds the vessel maximum, or when the two fluids are immiscible, reactive or of unknown miscibility.
    - 51 point evaluations take milliseconds.
  - **"3. Dosing" section:** the Fed-batch switch and all dosing inputs have moved out of "1. Vessel" into a new **3. Dosing** card after "2. Phases". Reaction and Correlations are now sections 4 and 5. The user switches on Fed-batch first, then defines the dosing.
  - **Dosing temperature (°C), feed sensible heat (API contract change):**
    - `FeedSpec` gained `rate_mL_min`, `T_C` and `fluid`. `PointResult` gained `Q_feed_W` ("Q_feed (W)") and `Q_load_W` ("Q_load (W)").
    - When a rate and a temperature are given, `services._feed` computes Q_feed = ṁ·Cp·(T_feed − T_process). Here ṁ = rate × ρ, and ρ and Cp come from `thermal_props(dosed fluid, T_feed)`. Q_feed is negative when the feed is colder than the batch.
    - `operating_point.evaluate` uses the net load Q_load = Q_gen + Q_feed for `Q_gen/Q_cool (%)` and for the heat-table balance. The heat balance now also runs when ΔH = 0 and the feed alone carries sensible heat.
    - The heat table adds the rows "Feed sensible heat Q_feed" and "Net heat load Q_gen + Q_feed". If the net load is ≤ 0, the balance reads "Net cooling by the feed - no heat to remove".
    - The filling simulation adds Q_feed and Q_load series.
    - With no feed rate or temperature, the keys are absent and the outputs are unchanged, so the Taipy golden snapshots still pass.
  - **Simulate Filling** is now a switch (same control as Fed-batch); the unused `.check-field` CSS was removed.
  - **"No reaction" (API contract change):** "4. Reaction" offers *No reaction* as a reaction source; the request sends `reaction: null`.
    - `PointRequest.reaction` is nullable. `op.Reaction.present = False` makes `evaluate_point` omit all Damköhler numbers (incl. Da_meso); `PointResult` Da fields default to `None` and `assessment` to `""`.
    - The tables return empty Damköhler and mass-transfer screens and the line "No reaction selected - Damköhler screening does not apply". Envelope and PDF drop Da parameters; the PDF shows t_rxn as "n/a (no reaction)". Filling drops Da series (as before for t_rxn ≤ 0).
    - `services.require_kinetics` replaces the four "t_rxn ≤ 0" checks: a *selected* reaction without usable kinetics is still rejected (422).
    - The page hides the reaction picker and kinetics inputs, and filters Da parameters out of the envelope / Solve-for lists.
  - **Temperature Profile (new):** `POST /assessment/temperature` (`TemperatureRequest` → `TemperatureResult`) and chart `assessment-temperature`, in the new `core/batch_temperature.py`.
    - Same energy balance as the Heat Transfer reaction profile (fixed k, constant-temperature jacket, 99 % conversion stop), extended to a feed: C(t)·dT/dt = Q_rxn + ṁ_f·cp_f·(T_f − T) + UA(t)·(T_cool − T), C(t) = m0·cp0 + m_f(t)·cp_f. Integrated semi-implicitly (4000 steps; 201 points returned).
    - **Batch scenario** (no dosing): both reagents charged at C0, run to 99 % conversion (24 h cap), UA at V. **Dosed scenario** (Fed-batch with dosing time and amount): reagent A charged at C0·V0, the stoichiometric co-reagent dosed at a constant rate with the feed (accumulates if the reaction is slower than the dosing), over the dosing time; UA(t) is interpolated from 26 points along the volume-blended fill.
    - Results: start / peak / lowest / end temperature, the no-cooling end temperature (overall heat balance: all reagent reacted and all feed added, no jacket), conversion, time to 99 %, total reaction heat. The page runs it on Compute when dosing is defined, or when a reaction with ΔH ≠ 0 is selected.
    - `operating_point.jacket_ua` is the shared U / A calculation (used by `evaluate_point`, the filling series and the temperature profile).
  - **Filling Dynamics:** new **UA (W/K)** series in the Heat-transfer plots (whenever process/coolant temperatures are set). Constant series get a ±10 % axis so float noise is not magnified.
  - **Coolant (HTF) selection (API contract change):** "1. Vessel" has a **Coolant (HTF)** dropdown (media from `GET /heat-transfer/options`; default Water, plus "Typical jacket (h_o 1500 W/m²·K)").
    - Previously `estimate_U_detailed` always used the typical jacket-side h_o = 1500 W/m²·K, whatever coolant was used.
    - `HeatSpec` gained `htm`, `v_jacket_m_s` (1.0) and `d_hyd_jacket_m` (0.05), the Heat Transfer page defaults. `services._heat` computes h_o with `core.heat_transfer.jacket_side_htc` (as on the Heat Transfer page) and passes it as `jacket_htc` through `op.jacket_ua`. U, Q_cool, the temperature profile and the filling U/UA series all use it.
    - The heat table adds "Coolant (HTF)" and "Jacket-side h_o"; a coolant temperature outside the HTF's range in `data/HTM.csv` is flagged with ⚠️. Unknown media return 404.
    - Example (EasyMax 102, 400 RPM, 50 mL water): U = 821 W/m²·K (typical) vs 1210 (Water) vs 311 (Syltherm 800).
    - `htm = None` keeps the old behaviour, so the Taipy golden snapshots are unchanged.
- **Bourne Protocol (React):**
  - **Working volume** has a slider (both tabs) over the vessel fill range; `BourneDefaults` gained `V_L_range` (same `envelope.operating_window` fallbacks as Vessel Assessment).
  - **Test 1 conditions** now show a short table (Condition, N, Fill volume, P/V, P/m; CSV `bourne_test_1_conditions.csv`) and an expander *All hydrodynamic parameters per condition* (CSV `bourne_test_1_conditions_detail.csv`): power, torque, mean EDR (= P/m) and ε_max, tip speed, Re, Froude, pumping rate, circulation / blend times, bulk and impeller micromixing times, Kolmogorov η, average / maximum shear rate, shear stress, EDCF, surface kLa — `compute_reactor_hydro` per condition.
  - `BournePlanTables` gained `test1_summary` and `test1_detail` (`reports/bourne_tables.test1_summary_table` / `test1_detail_table`). `test1` is unchanged (Taipy page and PDF parity).
  - **Test 1 layout:** the four steps are numbered, bordered sub-panels (`.sub-section` / `.sub-step` in `styles.css`): 1.1 Centre point & test conditions, 1.2 Discrete speed adjustments (fed-batch), 1.3 Impeller speed vs fill volume, 1.4 Measured responses.
  - **Operating conditions in every conditions table:** `bourne_tables.with_operating` inserts **T (°C)** (and, for Tests 2 and 3, the held **N (RPM)** = the Test 1 centre condition and **Fill volume (L)**) after the first column of `test1_summary`, `test1_detail`, `test2` and `test3`. The Taipy parity test compares Tests 2/3 without these columns.
  - **Report:** the API snapshot adds `T_C` and `vessel_info` (`bourne_tables.vessel_info`: manufacturer / model, vessel type, scale, tank diameter, dish, baffles, materials, impeller type / model / flow / count / diameter / clearance, Np, feed pipe, probes, instrumentation, heating / cooling, HTF, volume and speed ranges; empty fields skipped). `build_bourne_protocol_pdf` shows the temperature and a *Vessel* table under System Configuration, and T / Volume / N columns in the Test 1-3 conditions tables (T only when the snapshot has it, so the Taipy page PDF keeps its layout). The page-vs-API snapshot test pops the two report-only keys.
- **Fluid Database, Blend:** the results table has a **kinematic viscosity ν = μ/ρ** column (mm²/s = cSt) for each component and for the blend. It is calculated in the page from the returned μ and ρ, so the API is unchanged.
- **Vessel Database, Explore Vessel:**
  - **3D viewer:** the figure caption (model name / file name) is no longer shown under the viewer.
  - **2D schematic:** the fill volume has a slider next to the number box, spanning the vessel's V_L_min–V_L_max (0 / brim-full when missing; `fillSliderRange`).
  - **Layout:** the 3D viewer and a compact spec sheet sit side by side and stack on narrow screens. The spec sheet has a vessel-name header with the property picker and scrolling property/value rows, with units shown inline.
  - **Default properties:** now include Impeller 1 Diameter and two calculated ratios, marked "calc":
    - **D/T** = `D_imp_m / D_tank_m`;
    - **H/T** = `(bottom dish height + L_tan_tan_m) / D_tank_m`, the aspect ratio of the liquid-holding volume. The dish height is `H_bot_dish_m`, else `H_max_m − L_tan_tan_m`, as in `core.records.bottom_dish_height`. Overall height `H_m` is not used: it is missing for some vessels and includes the top head.
  - **Default list:** shows Tan-Tan Length and Bottom Dish Height (the H/T inputs) instead of Full Height.
  - **Label change:** `D_imp_m` is now labelled "Impeller 1 Diameter [m]" (was "Impeller Diameter"), matching the Impeller 2/3 labels. Labels are display-only, so the CSV is unchanged; the Taipy vessel table shows the new label too.
- **Not converted (still tables):** comparative or multi-row data, such as the Vessel Comparison tables, the correlation / heat-transfer-medium comparisons, Bourne condition tables and Recorded Results.
- **API (additive):**
  - `BourneTestOut.kpi_details`;
  - `BourneAssessResult.test_lines` / `conclusion` / `pm_span`;
  - `ProtocolPage.verdict_kind` / `insights` / `actions`.
  
  `rules.bourne_summary_md` is now built from the new `rules.bourne_conclusion_lines`, and its output is unchanged. Tests assert that the structured fields reproduce the existing Markdown and tables.

**16n. Taipy UI retired (the app is React + FastAPI only).**

- **Moved to `../mixing_lab_taipy_depr`** (a sibling of this repo; they show as deletions in git): `app.py`, `pages/`, `.taipyignore`, `_smoke.py`, `_render_check.py`, `scripts/build_equations.py` and `data/equations_reference.json` (plus its `data/bkp` copy — pre-rendered equation PNGs used only by the Taipy page; the web app renders the LaTeX in `data/equations_source.json`), and the Taipy-only tests (`test_golden_outputs`, `test_golden_reports`, `test_bourne_kpi_workflow`, `test_bourne_protocol_regression`, `test_db_common`, `test_*_exports`, `test_sensitivity_pdf_export`) with copies of `tests/golden/page_outputs.json` and `report_outputs.json`.
- **Regression coverage kept without Taipy:** the page inputs and page-side values that the API, contract and report tests compared against were frozen (while Taipy was still installed) into `tests/golden/requests.json` and `tests/golden/page_parity.json`. `tests/golden_helpers.py` holds the comparison helpers. `test_contracts`, `test_reports` and the parity tests in `test_api` now read these fixtures. The KPI-rule and reaction-time tests that did not need a page moved to `tests/test_bourne_kpi.py`; `test_bottom_dish_height` now uses `core.records.bottom_dish_height`. The Taipy admin-unlock and blend-page `_join_pairs` tests were archived.
- **Other clean-up:** `requirements.txt` drops taipy-gui, Flask, Flask-SocketIO, flask-compress, gunicorn and gevent. `utils.usage.install_usage_logging` (the Flask hook) is removed; the FastAPI middleware logs usage. Docstrings no longer refer to Taipy. Python suite: 760 tests (853 before; the difference is the archived Taipy tests).
- **Bourne Protocol:** Tests 2 and 3 have numbered sub-sections like Test 1 (2.1 Feed definition & test conditions, 2.2 Measured responses; 3.1 Feed locations & test conditions, 3.2 Measured responses).

**16o. Calculation accuracy review (equations, units, sources).**

Every equation, its variables, code location, source and verification status is listed in [EQUATIONS_REGISTRY.md](EQUATIONS_REGISTRY.md). Numeric corrections:

- **Specific power uses the actual fill volume.** `hydro_basics` / `compute_reactor_hydro` / `compute_reactor_hydro_with_mode` take an optional `V_m3`. The VA/VC operating point, the Sensitivity screening vessel and the Bourne Test 1 detail table pass the entered volume. Before this change V = πD²H/4, which over-stated the volume of dished vessels by about 12 % (up to 37 %). P/V, ε, t_c, η, t_E, γ̇_avg and kLa_surface all move accordingly, and "Volume (L)" now equals the entered fill. The fallback without `V_m3` is unchanged.
- **Klöpper (torispherical) head volume** is now 0.0990 D³ (was 0.0847 D³, 14 % low). The value is checked by profile integration.
- **Heat generation is signed:** Q_gen = −ΔH·r (positive when exothermic). Endothermic reactions no longer count as heat load. Zero-order kinetics now give r = k (previously 0).
- **Hausen laminar jacket Nu:** the constant is 0.0668 (was 0.065), in both copies. The flow length L = 1 m is now the named constant `JACKET_PATH_L_M`.
- **Heat Transfer "Initial dT/dt"** = |UA(T_j − T₀) + P_ag|/(ρVc_p). The old form (q_max − P_ag) was wrong for heating.
- **Unit converter:** US gal/h is 1.0515e-6 m³/s (was 10× too large).
- **VA:** the ΔH field label states the sign convention ("− = exothermic").

Equations Reference page (`data/equations_source.json`):

- **New entries:**
  - liquid height and dish volumes;
  - feed-point ε rules and the mesomixing reference (Bałdyga, Bourne & Hearn 1997);
  - zero-order t_rxn and rate;
  - feed sensible heat / Q_load;
  - the VA batch/dosed temperature-profile balance;
  - liquid–liquid dispersion screen;
  - blend mixing rules;
  - Cp(T) and k(T);
  - scale-up matching;
  - Bourne planning;
  - ROM demo-correlation warning.
- **Corrected entries:**
  - wall and lining k now match the code (SS 15, glass 1.2);
  - Da_SL slip velocity (the code uses v_t only);
  - process-side Nu attribution (Chilton–Drew–Jebens);
  - ε_max form and reference consistency;
  - EDCF variant note (Jüsten et al. 1996);
  - van 't Riet ungassed P/V and validity range;
  - blend-time validity;
  - heuristic labels on the Da / heat-balance / suspension / miscibility bands;
  - dish-area references (DIN 28011/28013) and Perry/TEMA references.
- **Hyperlinks:** all 24 DOI / ISBN links were verified (Crossref / Open Library) to resolve to the cited work, and the NIST link returns 200. The ResearchGate link (Grenville et al. 2017) blocks automated clients (HTTP 403) and is labelled "opens in a browser only".

Code docstrings were corrected: the blend-time form, the ε_max / mesomixing / EDCF references, and the signed heat generation. The golden baselines (`tests/golden/*.json`) were rewritten after confirming that every diff traces to the corrections above. New regression tests are in `tests/test_calculation_review.py`.

**16p. Heat-transfer data sources, dead-code removal and Equations Reference redesign.**

- **Nusselt options (Heat Transfer tool):** only the three traceable correlations remain: Chilton–Drew–Jebens (the new default), flat-blade turbine and Brooks–Su. Removed:
  - "DIN 28131": that standard covers agitator types and did not define these constants; they duplicated CDJ.
  - "Lehrer (anchor/helical)": Lehrer (1970), doi:10.1021/i260036a010, is a jacket-side correlation.
  - "Stein–Schmidt": the cited *Chem. Eng. Process.* 32:305 is a filtration paper.
  - "Nagata 0.18": not traceable.
- **Coolants (`data/HTM.csv`):** checked against vendor datasheets, now stored in `data/HTM_datasheets`.
  - **Dowtherm A** (Dow TDS 176-01472): μ corrected from 2.5 to 3.8 mPa·s.
  - **Dowtherm Q** (Dow TDS 176-01467): corrected ρ 962, μ 3.5 mPa·s, k 0.121.
  - **Therminol 66** (Eastman bulletin TF-8695): Cp 1680 → 1580.
  - **Marlotherm SH** (Eastman guide MT-10741): the fluid is dibenzyltoluene, not benzyltoluene. New values: range −15–325 °C, ρ 1039, Cp 1580, μ 2.8 → 36 mPa·s, k 0.130.
  
  Every entry now cites its datasheet.
- **One home for the heat-transfer primitives:** `utils/calculations/heat_transfer.py` now holds the Nusselt and material tables (with their source dicts) and these functions: `nusselt_jacket`, `jacket_side_htc(htm, v, d_h)`, `estimate_U_from_resistances`, `estimate_jacket_area` and `time_to_cool_or_heat`.
  - `core/heat_transfer.py` imports them and keeps only the Heat Transfer tool simulations.
  - Removed duplicates: core copies of `estimate_jacket_area`, the cone helpers, `impeller_power`, `nusselt_jacket`, `jacket_side_htc`, `estimate_U_from_resistances` and `time_to_cool_or_heat`.
  - Removed from utils: the name-based `jacket_side_htc`, `load_htm_db` / `HTM_DB`, and the unused `JACKET_HTC` table.
  - `estimate_U_detailed` now uses the shared CDJ correlation and the 15 W/m·K stainless default (was 16).
- **Unused calculations removed:**
  - gas–liquid: `gas_holdup_calderbank`, `gas_flooding_speed` / `_flow_rate`, `complete_dispersion_speed` / `_flow_rate`;
  - liquid–liquid: `n_min_van_heuven_beek`, `liquid_liquid_mass_transfer`, `liquid_liquid_capacity_ratio`, `dispersion_screen`;
  - ROM registry: the demo correlations (never applied, untraceable sources), `get_all_registered_reactors`, `get_all_correlations`, `available_param_modes`, `has_any_alt_correlations`, `PARAM_DISPLAY`;
  - ROM templates: `templates_for_param`, `compatible_templates`;
  - kinetics: the `timescale_profile` alias.
  
  The ROM parity test now registers its own correlation.
- **Equations Reference:**
  - **Source:** now `data/equations.md`, readable Markdown. Each `#` heading is a section and each `##` heading an entry. An entry has an optional `Used in:` line, a body whose first `$$` block is the headline equation, and a `Sources:` list. `core/equations.py` parses it. `data/equations_source.json` is removed.
  - **API:** `GET /equations` returns `sections[] → {id, title, intro, entries[] → {id, title, used_in, equation, body, sources}}`.
  - **Content:** reorganised into 13 sections and 47 entries, with the overlaps between "Heat Balance" and "Heat Transfer Tool" merged (jacket area, batch time, U, Nusselt, wall k, impeller power).
  - **Page:**
    - a sticky search / "Expand all" / "Collapse all" bar;
    - a sticky table of contents with deep links (`#section--entry`, honoured on load);
    - one card per entry: title, "used in" chips, headline equation, and a collapsible "Variables, notes & sources" panel;
    - search matches titles, LaTeX, notes, sources and pages, and shows "N of M entries".
  
  The stray "; search matches…" text inside each section is gone.
- **Tests:** 764 Python and 101 web tests pass. The golden Heat Transfer entries were refreshed: 3 correlations, corrected HTF data, and Marlotherm now in range at −10 °C.

**16q. Vortex at an agitation rate (Vessel Database).**

- **Model (`core/vortex.py`):** Nagata combined Rankine vortex. Solid-body rotation applies inside the impeller radius and a free vortex outside it. The centre height is found by bisection so the liquid volume equals the static fill, including flat, conical and dished bottoms.
  - Baffles: ≥ 3 → flat surface; 1–2 → unbaffled profile shown as an upper bound; blank → treated as unbaffled with a note.
  - Warnings: vortex reaching the bottom or the top impeller, surface rising above the tangent line or brim at the wall. A note is added when Re < 10⁴.
- **API:** `/media/vessels/{name}/fill` and `/schematic.png` take an optional `rpm`. The fill response gains `vortex` (rpm, regime, depth, centre and wall heights, Re, Fr, warnings).
- **Schematic:** the liquid is drawn up to the vortex surface, with the rest level shown dashed, and the label reads "V L @ N rpm".
- **Page:** a "Show vortex at an agitation rate" switch adds an rpm slider (over the vessel's rated speed range, defaulting to the midpoint) and a caption with the vortex depth and model notes.
- **Docs:** a new "Free-surface vortex (Nagata)" entry in `data/equations.md` and row G9 in `docs/EQUATIONS_REGISTRY.md`.
- **Tests:** `tests/test_vortex.py` and the rpm helpers in `VesselDatabase.test.ts`. 771 Python and 103 web tests pass.

**16r. Bourne Test 1 stir-speed limit alert.**

- `core/bourne_plan.test1_speed_limit_warning` lists each Test 1 condition (low, centre, high) whose target speed falls outside the vessel's minimum or maximum RPM. For each it gives the speed and P/m that were needed, the limit applied, and the P/m actually reached.
- `BournePlanTables.test1_speed_warning` carries the alert. The page shows it as a warning banner above the Test 1 conditions table, on both the Protocol and Plan tabs.

**16s. Reaction Sensitivity Protocol: verdict logic review.**

- **Heat transfer is no longer treated as a mixing mechanism.** The verdict is built from the mixing and mass-transport findings only (micromixing, micro/mesomixing selectivity, feed-plume mesomixing, macromixing, mass transfer). A heat-transfer flag is reported alongside it ("…; heat transfer needs review" plus a "Separately, heat transfer is likely limiting" sentence), and it never produces "scale-dependent mixing sensitivity … confirm with Damköhler". An unknown ΔH no longer makes the mixing verdict "Incomplete". The "Kinetics basis" caveat is no longer counted as a mechanism; it adds a proxy-kinetics note instead.
- **Each mechanism has its own confirmation step** in the verdict: Damköhler numbers for micro/macromixing, Bourne Tests 2 and 3 for feed-zone selectivity, and kLa-based Da_GL / Da_SL for mass transfer.
- **Findings now agree with Step 7.** A 0.1–1 s reaction is "Possible at scale" (warning) in both places; only t_rxn < 0.1 s is "Likely sensitive". The duplicate "Semi-batch (fed-batch)" finding is merged into the selectivity / feed-plume finding.
- **Next steps:**
  - "Re-check Da at the target scale" when Da was already computed on the page, rather than "compute Da".
  - "Complete Test N" when the Bourne Protocol confirmed a sensitivity but did not resolve the scale.
  - A single feed-zone action, which is not suggested when the Bourne Protocol already settled it.
- **PDF:** the verdict colour now comes from the verdict's severity rather than keyword matching, which had printed "Mixing sensitivity confirmed" in green.
- **Page:** the Step 2 text now says that t_rxn is the initial-rate time constant (it previously claimed the 90 % conversion time was used). The summary tile reads "Likely limiting".
- **Tests:** new rule tests in `tests/test_core_rules.py`. The Reaction Sensitivity Protocol goldens (`page_outputs`, `page_parity`, `report_outputs`) were refreshed, and every diff traces to the points above.
