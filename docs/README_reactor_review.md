# Reactor rows to re-verify

Date: 2026-09-16. Every row of `data/reactors.csv` that has missing geometry, a physically inconsistent dimension,
a questionable dish label, or a schematic-vs-calculation disagreement above 1 % of `H_max_m`. Rows are in **CSV
order**. Rows not listed here (RX-001–004, 007, 008, 015, 017, 027–030, 034, 035, 037, 038, 039, 042) are
complete and self-consistent.

How the checks were made (see `README_code_changes.md` §10):
- **B** = liquid level from the CSV dish height (what the Vessel Database schematic draws)
- **C** = liquid level from `liquid_height_from_volume()` (what Vessel Assessment / Bourne / Vessel Comparison compute)
- "C−B" is the difference at the page-default fill (midpoint of `V_L_min`/`V_L_max`, else 70 % of brim), as % of `H_max_m`
- "hemisphere limit" — a curved (non-conical) bottom cannot be deeper than R = D/2
- "best fit" — standard head whose depth/D ratio is closest to `H_bot_dish_m / D_tank_m`

Two systematic effects that appear on many rows and are **not** data errors:
1. The schematic subtracts impeller metal displacement (20 % solidity); the calculation pages don't. On heavily agitated vessels this alone is 1–3 % of `H_max_m`.
2. The schematic draws a torispherical head as an elliptical arc; `dish_geometry` uses the DIN constant 0.0847 D³. A real Klöpper head holds less than the arc, so B reads slightly high (~+2 %).

---

## RX-005 · Cambrex R-B02
| | |
|---|---|
| Missing | `V_L_max` |
| Effect | default fill falls back to 70 % of brim (1 686 L) instead of the working range |
| Re-verify | working max volume |

## RX-006 · Cambrex R-C01
| | |
|---|---|
| Geometry | D 1.218, tan-tan 0.832, H_max 1.14, dish 0.308 = 0.253 D ✓ 2:1 elliptical |
| C−B | −16.6 mm (−1.5 %) — impeller displacement (systematic #1) |
| Re-verify | nothing; noted because it is over the 1 % line |

## RX-009 · Cambrex R-301 &nbsp;·&nbsp; RX-010 · Cambrex R-302 &nbsp;·&nbsp; RX-011 · Cambrex R-801
(identical geometry rows)
| | |
|---|---|
| Missing | `V_L_min`, `V_L_max` |
| Label vs. depth | `45 deg conical` → R·tan 45° = 486 mm, but CSV dish = **511 mm = 46.4° cone** |
| C−B | −49.5 mm (−3.1 %): 33 mm impeller displacement (two ⌀600 mm impellers, one flagged as cutting the dish wall) + 17 mm from the 25 mm cone-depth mismatch |
| Re-verify | (a) cone angle — if 46°, relabel `46 deg conical`; if truly 45°, then `H_max_m` (1.583) or `L_tan_tan_m` (1.072) is 25 mm off. (b) Impeller 1 ⌀600 mm at 171 mm clearance inside a 972 mm cone — check `D_imp_m` / `imp1_clearance_m`. (c) working volumes. |

## RX-012 · Cambrex R-802
| | |
|---|---|
| Geometry | dish 187 mm = 0.192 D ✓ torispherical |
| C−B | +14.5 mm (+1.2 %) — systematic #1/#2, opposite signs partly cancelling |
| Re-verify | nothing required |

## RX-013 · TMA 1.6 L Polyclave
| | |
|---|---|
| Edited | tan-tan 0.285 → 0.244, dish forced to R = 0.041, label Spherical → Hemispherical (see csv change log #6, #11) |
| Remaining | `V_L_max` 1.5 L exceeds the geometric brim to the top tangent (1.43 L) by 5 % |
| C−B | −1.5 mm (−0.5 %) ✓ |
| Re-verify | whether 1.5 L is a nominal size or a real working max above the tangent line; whether `H_max_m` 0.285 was measured to the apex |

## RX-014 · TSHO Optimax-1001
| | |
|---|---|
| Edited | label Dished → Hemispherical (#18) |
| **Physically inconsistent** | CSV dish **60 mm > hemisphere limit 50.5 mm** on D 101 mm (0.59 D) |
| C−B | −3.6 mm (−1.7 %) |
| Re-verify | `H_max_m` 0.22 and/or `L_tan_tan_m` 0.16 — one is ~10 mm off (expected dish ≈ 50 mm → either H_max ≈ 0.21 or tan-tan ≈ 0.17). Measure from the dish apex, not the drain/outlet. |

## RX-016 · TSHO 102 EasyMax
| | |
|---|---|
| Label vs. depth | `2:1 Elliptical` (0.25 D = 12.5 mm) but CSV dish **17.6 mm = 0.35 D** (+38 %) — between elliptical and hemispherical |
| C−B | −2.7 mm (−2.9 %) |
| Re-verify | dish depth / `H_max_m` 0.09384; the other EasyMax-102s were set to a 4.7 mm "Dished" cap — confirm the TSHO 102 is really a different bottom |

## RX-018 · Nalas 1 L MP06 &nbsp;·&nbsp; RX-019 · Nalas 1 L MP10
| | |
|---|---|
| **Missing** | `D_tank_m`, `L_tan_tan_m`, `H_bot_dish_m`, `bottom_dish`, `top_dish`, `V_L_min`, `V_L_max` — only `H_max_m = 0.22` present |
| Effect | excluded from the schematic and the comparison; calculation pages have no diameter |
| Re-verify | full geometry (user to handle individually) |

## RX-020 · Nalas 2 L Buchi
| | |
|---|---|
| **Missing** | `L_tan_tan_m`, `H_bot_dish_m`, `bottom_dish`, `top_dish`, `imp1_clearance_m` (has D 0.102, H_max 0.2254) |
| Effect | excluded from the schematic; calculation pages use `H_max_m` with the 2:1-ellipsoidal default dish |
| Re-verify | tan-tan length and dish type (user to handle individually) |

## RX-021 · Nalas 5 L Buchi
| | |
|---|---|
| **Physically inconsistent** | CSV dish **86.6 mm > hemisphere limit 74 mm** on D 148 mm; a DIN Klöpper head would be ~29 mm |
| Drawing evidence | Büchi sheet shows a torispherical knuckle + shallow crown **and a ⌀66 mm bottom-outlet flange** — the excess ≈ 58 mm is almost certainly the outlet neck measured into `H_max_m` |
| C−B | −16.2 mm (−5.4 %) |
| Re-verify | **dish depth from tangent line to inside crown** (expected ≈ 29 mm) → then `H_max_m` = 0.215 + h ≈ 0.244. Also confirm `imp1_clearance_m` 40 mm is from the crown, not the outlet. Label `DIN Torispherical` is believed correct. |

## RX-022 · Nalas 20 L Buchi
| | |
|---|---|
| Geometry | dish 56 mm = 0.203 D ✓ torispherical |
| C−B | +4.9 mm (+1.3 %) — systematic #2 |
| Re-verify | nothing required |

## RX-023 · Cambrex R-901 &nbsp;·&nbsp; RX-024 · R-902 &nbsp;·&nbsp; RX-025 · R-401 &nbsp;·&nbsp; RX-026 · R-402
| | |
|---|---|
| Geometry | dish 308 mm = 0.253 D ✓ 2:1 elliptical |
| C−B | −17.8 / −18.4 mm (−1.0 %) — impeller displacement (systematic #1) |
| Re-verify | nothing required |

## RX-036 · CHP_500mL_01 (Cambrex, ChemGlass 500 mL)
| | |
|---|---|
| Edited | heights re-measured from the ChemGlass drawing: tan-tan 0.036, H_max 0.0816 (= 500 mL line), dish 0.0456; labels Spherical → Hemispherical (bottom) / Flat (top) (#13, #16, #17) |
| Remaining | `imp1_clearance_m` = text `"Variable"` → treated as 0, schematic uses a default clearance; `V_L_max` 0.5 L vs brim 0.48 L (the 9 mL difference is impeller displacement — fine) |
| C−B | 0.0 mm ✓ (both clamped at the 500 mL brim) |
| Re-verify | a numeric working clearance for the CBT turbine |

## RX-037 · CHP_5L_01 (Cambrex, ChemGlass 5 L)
| | |
|---|---|
| Edited | labels Spherical → Hemispherical (#14) |
| Geometry | dish 88.3 mm vs R 87.8 mm — 0.5 mm over the hemisphere limit, within measurement tolerance ✓ |
| Remaining | `imp1_clearance_m` = text `"Variable"` |
| Re-verify | numeric clearance only |

## RX-032 · Cambrex R-A01 &nbsp;·&nbsp; RX-033 · Cambrex R-A02
| | |
|---|---|
| Geometry | dish 308 mm = 0.253 D ✓ |
| C−B | −20.8 mm (−1.2 %) — impeller displacement |
| Re-verify | nothing required |

## RX-038 · TMA 100 mL Chemspeed
| | |
|---|---|
| Edited | `H_max_m` 0.7443 → 0.07443 (#5) |
| Missing | `imp1_clearance_m` |
| Geometry | dish 9.1 mm = 0.224 D, labelled 2:1 Elliptical (0.25 D, −10 %) — acceptable |
| C−B | −0.1 mm ✓ |
| Re-verify | impeller clearance |

## RX-040 · TMA 10 L Chemglass
| | |
|---|---|
| Edited | `bottom_dish` blank → 2:1 Elliptical → **Torispherical** (#10, #19) |
| **Missing** | `top_dish`, `V_L_min`, `V_L_max`, `D_imp_m`, `impeller_type`, `imp1_clearance_m` |
| Geometry | dish 40 mm = 0.20 D ✓ torispherical |
| C−B | +3.8 mm (+2.0 %) — systematic #2 only (no impeller recorded) |
| Re-verify | impeller data, working volumes, top closure |

## RX-041 · TMA 15 L Buchi
| | |
|---|---|
| Edited | `bottom_dish` Torispherical → 2:1 Elliptical (#15) |
| Remaining | **`V_L_max` 15 L exceeds the geometric brim to the top tangent (11.6 L) by 29 %** |
| C−B | −1.9 mm (−0.65 %) ✓ |
| Re-verify | whether "15 L" is the nominal vessel size rather than a working max; or whether `L_tan_tan_m` 0.229 is short (15 L above a 61 mm dish on D 235 would need tan-tan ≈ 0.31 m) |

---

## Summary by priority

| priority | reactor | one-line action |
|---|---|---|
| 1 | RX-021 Nalas 5 L | get dish depth (tangent → crown) from the Büchi sheet; fix `H_max_m` (~0.244) |
| 1 | RX-014 Optimax-1001 | re-measure `H_max_m` / `L_tan_tan_m` — dish cannot exceed 50.5 mm |
| 1 | RX-018, RX-019, RX-020 Nalas | complete geometry (user) |
| 2 | RX-009/010/011 Cambrex conical | confirm 45° vs 46.4° cone; check ⌀600 mm impeller fits the cone; add working volumes |
| 2 | RX-041 15 L Buchi | reconcile `V_L_max` 15 L with 11.6 L brim |
| 2 | RX-016 TSHO 102 EasyMax | confirm 17.6 mm dish (vs 4.7 mm on the other EasyMax-102s) |
| 3 | RX-040 10 L Chemglass | impeller data, working volumes, top closure |
| 3 | RX-036, RX-037 CHP | replace `"Variable"` clearance with a number |
| 3 | RX-013 Polyclave | confirm 1.5 L working max vs 1.43 L brim |
| 3 | RX-005, RX-038 | fill in `V_L_max` / `imp1_clearance_m` |
