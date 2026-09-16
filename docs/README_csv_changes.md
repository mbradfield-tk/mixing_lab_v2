# `data/reactors.csv` — change log

Date: 2026-09-16. Every edit made to the reactor database during the vessel-height clarification, in the order it
happened, with the reason. Values in metres unless stated. "Round" numbers group edits by the review pass they came
from. Companion documents: `README_code_changes.md`, `README_reactor_review.md`.

## Column semantics (new)

| column | meaning | source |
|---|---|---|
| `D_tank_m` | inside diameter | measured |
| `L_tan_tan_m` | straight-wall length, bottom tangent line → top tangent line (**was `H_m`**) | measured |
| `H_max_m` | maximum fill height, bottom-dish apex → top tangent line | measured |
| `H_bot_dish_m` | bottom-dish height = `H_max_m − L_tan_tan_m` | **derived** |
| `H_m` | full height, dish apex → top of top dish — **new, intentionally empty** | to be measured |

---

## A. Structural changes (all rows)

| # | round | change | rationale |
|---|---|---|---|
| 1 | 1 | Column `H_m` **renamed** `L_tan_tan_m` | The values were the straight-wall tangent-to-tangent length, not a vessel height. Name now says what it is. |
| 2 | 1 | Column `H_bot_dish_m` **added** = `H_max_m − L_tan_tan_m` (populated for the 39 rows that have both inputs) | Bottom-dish height was never stored; every page guessed it from the dish-type text. It is now explicit and the schematic draws from it. |
| 3 | 1 | Column `H_m` **re-created empty** with label "Full Height [m]" | Reserved for the true overall height (apex → top-dish top). No code reads it. ⚠ Importing a legacy CSV via the Vessel Database Import dialog would drop old tan-tan values into this column. |

---

## B. Per-reactor value changes (chronological)

| # | round | reactor | field | before | after | rationale |
|---|---|---|---|---|---|---|
| 4 | 1 | **RX-015** TMA EasyMax-102 HP | `L_tan_tan_m` / `H_max_m` | 0.088 / 0.0833 | 0.0833 / 0.088 | The two values were swapped in the source (gave a −4.7 mm dish). Tan-tan cannot exceed max fill. |
| 5 | 1 | **RX-038** TMA 100 mL Chemspeed | `H_max_m` | 0.7443 | 0.07443 | Decimal-point typo — implied a 0.68 m dish on a 41 mm tank. User confirmed; left as-is in later rounds. |
| 6 | 1 | **RX-013** TMA 1.6 L Polyclave | `L_tan_tan_m` | 0.285 | 0.24 | Was recorded equal to `H_max_m` (zero dish) on a spherical-bottom vessel. User-specified value (dish 45 mm). Superseded by #11. |
| 7 | 1 | **RX-017** Nalas EasyMax-102 | `L_tan_tan_m` | 0.088 | 0.078 | Was equal to `H_max_m` (zero dish). User's first request (0.24) would give a −152 mm dish; 0.078 derived from the torispherical heuristic 0.1935·D and confirmed. Superseded by #8. |
| 8 | 2 | **RX-017** Nalas EasyMax-102 | `L_tan_tan_m` | 0.078 | 0.0833 | User aligned all EasyMax-102 vessels to a common geometry 0.0833 / 0.088 (dish 4.7 mm). |
| 9 | 2 | **RX-027** TMA EasyMax-102 | `L_tan_tan_m` / `H_max_m` | 0.088 / *blank* | 0.0833 / 0.088 | `H_max_m` was missing (page code fell back to tan-tan). Aligned to the EasyMax-102 family. |
| 10 | 2 | **RX-040** TMA 10 L Chemglass | `bottom_dish` | *blank* | 2:1 Elliptical | No dish type recorded although the heights imply a 40 mm dish. User assumption. Superseded by #19. |
| 11 | 3 | **RX-013** TMA 1.6 L Polyclave | `bottom_dish` / `H_bot_dish_m` / `L_tan_tan_m` | Spherical / 0.045 / 0.24 | Hemispherical / 0.041 / 0.244 | User forced a true hemisphere: dish = R = D/2 = 41 mm, tan-tan = 0.285 − 0.041. `H_max_m` 0.285 kept. ("Spherical" was also not recognised by either dish heuristic.) |
| 12 | 4 | **RX-015, RX-017, RX-027** (EasyMax-102 family) | `bottom_dish` | Torispherical | Dished | Round-bottom glass reactors with a 4.7 mm cap on a ~50 mm ID are a shallow dish, not a welded torispherical head. The "Dished" formula (0.1 D ≈ 5 mm) matches the CSV; torispherical (0.1935 D ≈ 10 mm) did not. |
| 13 | 5 | **RX-036** CHP_500mL_01 | `bottom_dish` / `top_dish` | Spherical / Spherical | Hemispherical / Hemispherical | User: relabel only (heights fixed later in #16). |
| 14 | 5 | **RX-037** CHP_5L_01 | `bottom_dish` / `top_dish` | Spherical / Spherical | Hemispherical / Hemispherical | User. CSV dish 88.3 mm ≈ R 87.8 mm, already consistent with a hemisphere. |
| 15 | 6 | **RX-041** TMA 15 L Buchi | `bottom_dish` | Torispherical | 2:1 Elliptical | CSV dish 60.9 mm on D 235 mm = 0.259 D → matches 2:1 elliptical (0.25 D, +2 %), not torispherical (0.1935 D, −25 %). B/C now agree within 0.65 %. |
| 16 | 6 | **RX-036** CHP_500mL_01 | `L_tan_tan_m` / `H_max_m` / `H_bot_dish_m` | 0.035518 / 0.046354 / 0.010836 | 0.036 / 0.0816 / 0.0456 | User, from the ChemGlass drawing (ID 97 mm, hemispherical bottom, 120.4 mm to the joint). `H_max_m` = the **500 mL graduation** (working max), not the joint. Derived dish 45.6 mm is 6 % under a true hemisphere (48.5 mm). Geometry to the 500 mL line = 491 mL. Old values could only hold ~0.3 L. |
| 17 | 6 | **RX-036** CHP_500mL_01 | `top_dish` | Hemispherical | Flat | Drawing shows a straight joint flange at the top. Affects the schematic outline only. |
| 18 | 6 | **RX-014** TSHO Optimax-1001 | `bottom_dish` | Dished | Hemispherical | CSV dish 60 mm on D 101 mm (0.59 D) is deeper than a hemisphere (50.5 mm); "Dished" (10 mm) was far off. B−C improves from −15.5 mm (−7.0 %) to −3.6 mm (−1.7 %). See review notes — heights still ~10 mm inconsistent. |
| 19 | 6 | **RX-040** TMA 10 L Chemglass | `bottom_dish` | 2:1 Elliptical | Torispherical | CSV dish 40 mm on D 200 mm = 0.20 D → torispherical (0.1935 D, +3 %), not elliptical (0.25 D, −20 %). |

---

## C. Rows explicitly **left unchanged** by decision

| reactor | what is off | decision |
|---|---|---|
| RX-018 Nalas 1 L MP06, RX-019 Nalas 1 L MP10 | only `H_max_m` present | user will handle individually |
| RX-020 Nalas 2 L Buchi | no `L_tan_tan_m`, no dish types | user will handle individually |
| RX-021 Nalas 5 L Buchi | dish 86.6 mm deeper than a hemisphere on D 148 | awaiting dish-depth dimension from the Büchi drawing |
| RX-038 | — | kept at the round-1 typo fix (0.07443) |

---

## D. Final state of every row (height columns + dish labels)

Bold = changed from the committed version (`git show HEAD:data/reactors.csv`).

| ID | Name | D_tank | L_tan_tan (was H_m) | H_max | H_bot_dish | bottom_dish | top_dish |
|---|---|---|---|---|---|---|---|
| RX-001 | Cambrex R-3156 | 1.3716 | 3.048 | 3.38125 | 0.333248 | 2:1 Elliptical | 2:1 Elliptical |
| RX-002 | Cambrex R-3156 Mod | 1.3716 | 3.048 | 3.38125 | 0.333248 | 2:1 Elliptical | 2:1 Elliptical |
| RX-003 | Cambrex R-5103 | 1.016 | 1.0064 | 1.261 | 0.2546 | 2:1 Elliptical | 2:1 Elliptical |
| RX-004 | Cambrex R-B01 | 1.218 | 1.467 | 1.775 | 0.308 | 2:1 Elliptical | 2:1 Elliptical |
| RX-005 | Cambrex R-B02 | 1.35 | 1.466 | 1.80494 | 0.338938 | 2:1 Elliptical | 2:1 Elliptical |
| RX-006 | Cambrex R-C01 | 1.218 | 0.832 | 1.14 | 0.308 | 2:1 Elliptical | 2:1 Elliptical |
| RX-007 | Cambrex R-101 | 0.8128 | 0.804 | 1.008 | 0.204 | 2:1 Elliptical | 2:1 Elliptical |
| RX-008 | Cambrex R-102 | 0.8128 | 0.792141 | 0.995341 | 0.2032 | 2:1 Elliptical | 2:1 Elliptical |
| RX-009 | Cambrex R-301 | 0.972 | 1.072 | 1.583 | 0.511 | 45 deg conical | Torispherical |
| RX-010 | Cambrex R-302 | 0.972 | 1.072 | 1.583 | 0.511 | 45 deg conical | Torispherical |
| RX-011 | Cambrex R-801 | 0.972 | 1.072 | 1.583 | 0.511 | 45 deg conical | Torispherical |
| RX-012 | Cambrex R-802 | 0.972 | 1.072 | 1.259 | 0.187 | Torispherical | Torispherical |
| RX-013 | TMA 1.6 L Polyclave | 0.082 | **0.244** (was 0.285) | 0.285 | 0.041 | **Hemispherical** (was Spherical) | Flat |
| RX-014 | TSHO Optimax-1001 | 0.101 | 0.16 | 0.22 | 0.06 | **Hemispherical** (was Dished) | Flat |
| RX-015 | TMA EasyMax-102 HP | 0.0449 | **0.0833** (was 0.088) | **0.088** (was 0.0833) | 0.0047 | **Dished** (was Torispherical) | Flat |
| RX-016 | TSHO 102 EasyMax | 0.05 | 0.07622 | 0.09384 | 0.01762 | 2:1 Elliptical | Flat |
| RX-017 | Nalas EasyMax-102 | 0.052 | **0.0833** (was 0.088) | 0.088 | 0.0047 | **Dished** (was Torispherical) | Torispherical |
| RX-018 | Nalas 1 L MP06 | blank | blank | 0.22 | blank | blank | blank |
| RX-019 | Nalas 1 L MP10 | blank | blank | 0.22 | blank | blank | blank |
| RX-020 | Nalas 2 L Buchi | 0.102 | blank | 0.2254 | blank | blank | blank |
| RX-021 | Nalas 5 L Buchi | 0.148 | 0.215 | 0.3016 | 0.0866 | DIN Torispherical | Flat |
| RX-022 | Nalas 20 L Buchi | 0.276 | 0.325 | 0.381 | 0.056 | DIN Torispherical | DIN Torispherical |
| RX-023 | Cambrex R-901 | 1.218 | 1.467 | 1.775 | 0.308 | 2:1 Elliptical | 2:1 Elliptical |
| RX-024 | Cambrex R-902 | 1.218 | 1.467 | 1.775 | 0.308 | 2:1 Elliptical | 2:1 Elliptical |
| RX-025 | Cambrex R-401 | 1.218 | 1.467 | 1.775 | 0.308 | 2:1 Elliptical | 2:1 Elliptical |
| RX-026 | Cambrex R-402 | 1.218 | 1.467 | 1.775 | 0.308 | 2:1 Elliptical | 2:1 Elliptical |
| RX-027 | TMA EasyMax-102 | 0.052 | **0.0833** (was 0.088) | **0.088** (was blank) | 0.0047 | **Dished** (was Torispherical) | Flat |
| RX-028 | Cambrex R-4140 | 2.452 | 2.744 | 3.366 | 0.622 | 2:1 Elliptical | 2:1 Elliptical |
| RX-029 | Cambrex R-4550 | 1.524 | 1.8288 | 2.21 | 0.3812 | 2:1 Elliptical | 2:1 Elliptical |
| RX-030 | Cambrex R-4552 | 1.219 | 1.473 | 1.7779 | 0.3049 | 2:1 Elliptical | 2:1 Elliptical |
| RX-034 | Cambrex R-5102 | 1.219 | 1.473 | 1.7779 | 0.3049 | 2:1 Elliptical | 2:1 Elliptical |
| RX-035 | Cambrex R-5104 | 1.524 | 1.8288 | 2.21 | 0.3812 | 2:1 Elliptical | 2:1 Elliptical |
| RX-036 | CHP_500mL_01 | 0.097 | **0.036** (was 0.035518) | **0.0816** (was 0.046354) | 0.0456 | **Hemispherical** (was Spherical) | **Flat** (was Spherical) |
| RX-037 | CHP_5L_01 | 0.17555 | 0.14866 | 0.23694 | 0.08828 | **Hemispherical** (was Spherical) | **Hemispherical** (was Spherical) |
| RX-031 | Cambrex R-202 | 1.218 | 0.832 | 1.14 | 0.308 | 2:1 Elliptical | 2:1 Elliptical |
| RX-032 | Cambrex R-A01 | 1.218 | 1.467 | 1.775 | 0.308 | 2:1 Elliptical | 2:1 Elliptical |
| RX-033 | Cambrex R-A02 | 1.218 | 1.467 | 1.775 | 0.308 | 2:1 Elliptical | 2:1 Elliptical |
| RX-038 | TMA 100 mL Chemspeed | 0.0408 | 0.0653 | **0.07443** (was 0.7443) | 0.00913 | 2:1 Elliptical | Flat |
| RX-039 | TMA EasyMax-402 | 0.0726 | 0.122 | 0.1368 | 0.0148 | Torispherical | Flat |
| RX-040 | TMA 10 L Chemglass | 0.2 | 0.15 | 0.19 | 0.04 | **Torispherical** (was blank) | blank |
| RX-041 | TMA 15 L Buchi | 0.23497 | 0.22905 | 0.29 | 0.06095 | **2:1 Elliptical** (was Torispherical) | Flat |
| RX-042 | TMA 30 Kilo GLS | 0.379 | 0.30413 | 0.37422 | 0.07009 | Torispherical | Flat |

(Row order is the CSV's own order — RX-031…033 are stored after RX-037.)

Dish-type vocabulary now in use — bottom: `2:1 Elliptical`, `45 deg conical`, `DIN Torispherical`, `Dished`,
`Hemispherical`, `Torispherical`; top: the same plus `Flat`. No `Spherical` entries remain.
