# Vessel-height clarification — code changes

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
