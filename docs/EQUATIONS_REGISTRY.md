# Mixing Lab — Equations Registry

Master list of every calculation in the app: the equation, variables and units, where it is coded, its source, and its verification status. Use it as the reference when comparing future changes, validating against measurements, or auditing a result.

*Last full review: 2026-10 (calculation-accuracy review, docs/README_code_changes.md §16o).*
The user-facing version of these equations is the **Equations Reference** page (`data/equations.md`). Keep the two in sync.

**Status legend**

| Status | Meaning |
|--------|---------|
| ✅ Verified | Formula, constants and units checked against the cited source or an exact derivation. The DOI or ISBN link resolves to the cited work. |
| ✅ Definition | A physical definition or identity, so no empirical constant is involved. |
| ⚠️ Heuristic | An engineering rule of thumb or screening threshold, not a published correlation. Treat the output as indicative. |
| ⚠️ Approx. | A published form used with a simplification. The simplification is noted. |
| ❓ Unverified | The source is cited but has not been traced to the primary document. |
| 🔧 Fixed | Corrected in the 2026 review. See the "Corrections" section. |

**Unit conventions (all code is SI)**

- N is in rev/s. The UI shows RPM, and RPM = 60 N.
- D, T and H are in m.
- V is in m³ inside calculations; the UI shows L.
- ρ is in kg/m³, μ in Pa·s and ν = μ/ρ in m²/s.
- **ε** without a qualifier is the mass-specific dissipation rate in **W/kg** (m²/s³), i.e. ε = P/(ρV). All turbulence time and length scales use it.
- **P/V** is in W/m³; the UI also shows W/L. van 't Riet's kLa takes P/V in W/m³.
- ΔH is in kJ/mol, with **negative = exothermic**.
- Temperatures are in °C. Temperature differences are in K.

---

## 1. Vessel geometry

| # | Quantity | Equation | Variables / units | Code | Source | Status |
|---|----------|----------|-------------------|------|--------|--------|
| G1 | Liquid height from volume | H = h_d·V/V_d if V ≤ V_d. Otherwise H = min(h_d + (V − V_d)/(πD²/4), H_max) | V: m³; D, H: m | `utils/calculations/geometry.liquid_height_from_volume` (`core/heat_transfer` delegates to it) | Geometry | ✅ for the cylinder part. ⚠️ The partial-dish branch is linear in V, which is not exact for a curved head. |
| G2 | 2:1 semi-ellipsoidal head (default) | h = D/4, V = πD³/24, A = 1.084 D² | – | `geometry.dish_geometry`, `heat_transfer.estimate_jacket_area` | DIN 28013, oblate-spheroid formulas | ✅ |
| G3 | Torispherical (Klöpper, DIN 28011: R = D, r = 0.1 D) | h = 0.1935 D, **V = 0.0990 D³**, A = 0.99 D² | – | same as G2 | DIN 28011; profile integration (`tests/test_calculation_review.py`) | 🔧 V was 0.0847 D³ (14 % low) |
| G4 | Hemispherical head | h = D/2, V = πD³/12 | – | `dish_geometry` | Geometry | ✅ |
| G5 | Shallow dished head | h = 0.1 D, V = πh(3R² + h²)/6 | – | `dish_geometry` | Spherical-cap formula. The 0.1 D depth is a heuristic. | ✅ / ⚠️ |
| G6 | Conical bottom | h = R·tanθ (θ is parsed from the label, default 45°), V = πD²h/12, A = (πD²/4)·√(1 + (h/R)²) | θ: deg | `cone_depth`, `dish_geometry`, `estimate_jacket_area` | Cone formulas | ✅ |
| G7 | Curved head with measured depth h | V = πD²h/6 (half-ellipsoid) | – | `dish_geometry` | Geometry | ⚠️ Approx. (an ellipsoid fitted to the measured depth) |
| G8 | Wetted jacket area | A = A_dish + πD(H − h_d). When H < h_d, A = A_dish·H/h_d. | m² | `estimate_jacket_area` (utils and core copies) | Geometry | ✅. ⚠️ Pro-rating by H/h_d is approximate. |
| G9 | Free-surface vortex profile | z − z₀ = ω²r²/2g (r ≤ r_c). For r > r_c: z − z₀ = ω²r_c²(2 − r_c²/r²)/2g. z₀ is set by volume conservation. | ω = 2πN; r_c = D/2; m | `core/vortex.vortex_state` (Vessel Database schematic) | Nagata (1975), ISBN 0470628634; Busciglio et al. (2013) [doi:10.1016/j.ces.2013.10.019](https://doi.org/10.1016/j.ces.2013.10.019) | ⚠️ Approx.: an upper bound (the core is assumed to rotate at the impeller speed). Unbaffled only; ≥ 3 baffles are drawn flat. |

## 2. Hydrodynamics and shear

| # | Quantity | Equation | Variables / units | Code | Source | Status |
|---|----------|----------|-------------------|------|--------|--------|
| H1 | Reynolds number | Re = ρND²/μ | – | `hydrodynamics.reynolds_number` | Handbook of Industrial Mixing (HIM), Ch. 6 [doi:10.1002/0471451452](https://doi.org/10.1002/0471451452) | ✅ Definition |
| H2 | Power number fallback | Laminar regime (Re ≤ 10): Np = 70/Re. Turbulent regime (Re ≥ 10⁴): Np = Np,turb. Transitional regime: log–log interpolation. | – | `power_number_correlation` | Rushton, Costich & Everett (1950); Bates, Fondy & Corpstein (1963); HIM Ch. 6 | ⚠️ Approx. (the interpolation) |
| H3 | Power | P = Np ρ N³ D⁵ | W | `impeller_power` | HIM Ch. 6 | ✅ Definition |
| H4 | Specific power | P/V (W/m³); ε = P/(ρV) (W/kg) | **V is the actual fill volume** | `reactor_hydro.hydro_basics` | HIM Ch. 6 | 🔧 Previously used V = πD²H/4, which overstated V by 12 % on average and up to 37 % (hemispherical heads), so P/V was understated. |
| H5 | Tip speed | u = πND | m/s | `tip_speed` | HIM Ch. 6 | ✅ |
| H6 | Pumping rate | Q = Nq N D³ (default Nq = 0.72) | m³/s | `pumping_rate`, `pumping_number_default` | HIM Ch. 6 | ✅ |
| H7 | Circulation time | t_c = V/(Nq N D³) | s | `circulation_time` | Nienow (1997) [doi:10.1016/S0009-2509(97)00072-9](https://doi.org/10.1016/S0009-2509%2897%2900072-9); HIM Ch. 9 | ✅ |
| H8 | Torque, torque/V | Λ = P/(2πN), Λ/V | N·m, N·m/m³ | `torque`, `torque_per_volume` | Definition | ✅ |
| H9 | Froude number | Fr = N²D/g | – | `froude_number` | HIM Ch. 6 | ✅ |
| H10 | Kolmogorov scale | η = (ν³/ε)^¼ | ε in W/kg | `mixing_times.kolmogorov_length` | Kolmogorov (1941/1991) [doi:10.1098/rspa.1991.0075](https://doi.org/10.1098/rspa.1991.0075) | ✅ |
| H11 | Maximum dissipation | ε_max = 1.04·x·Po^¾ N³ D², x = 15 (≈ 15.6 Po^¾ N³ D²) | W/kg | `epsilon_max_estimate` | Grenville, Giacomelli, Brown & Padron (2017), *Chem. Eng.* 124(8):42. The order of magnitude matches Kresta & Wood (1993) [doi:10.1016/0009-2509(93)80346-R](https://doi.org/10.1016/0009-2509%2893%2980346-R). | ❓ The coefficient is not traced to the primary article: the ResearchGate copy returns 403 to automated checks. Dimensionally consistent. |
| H12 | Average shear rate | γ̇_avg = √(P/(μV)) | 1/s | `average_shear_rate` | Camp & Stein (1943) | ✅ |
| H13 | Maximum shear rate | γ̇_max = √(ε_max/ν) | 1/s | `maximum_shear_rate` | ε = νγ̇² (Tennekes & Lumley 1972) | ✅ |
| H14 | Shear stress | τ = μγ̇ | Pa | `shear_stress` | Newton's law of viscosity | ✅ |
| H15 | EDCF | EDCF = ε_max/t_c | W/kg/s | `edcf` | A variant of Jüsten et al. (1996) [doi:10.1002/(SICI)1097-0290(19961220)52:6<672::AID-BIT5>3.0.CO;2-L](https://doi.org/10.1002/%28SICI%291097-0290%2819961220%2952:6%3C672::AID-BIT5%3E3.0.CO;2-L), which uses P/(kD³) in place of ε_max | ⚠️ Approx. (variant definition; not comparable in absolute terms with the literature) |

## 3. Mixing times and Damköhler numbers

| # | Quantity | Equation | Variables / units | Code | Source | Status |
|---|----------|----------|-------------------|------|--------|--------|
| M1 | Blend time (95 %) | θ95 = 5.2 T^1.5 H^0.5 / (Po^⅓ N D²) | s; T = tank diameter, H = liquid height | `blend_time_turbulent` | Grenville (1992); HIM Ch. 9 | ✅ (turbulent, H/T ≈ 1). ⚠️ An extrapolation for H/T ≫ 1 or Re < 10⁴. |
| M2 | Engulfment micromixing time | t_E = 17.3 (ν/ε)^½ | s | `micromixing_time_engulfment` | Bałdyga & Bourne (1999) [ISBN 0471981710](https://openlibrary.org/isbn/0471981710) | ✅ |
| M3 | Local t_E | t_E,loc = 17.3 (ν/ε_max)^½ | s | `micromixing_time_local` | same as M2 | ✅ |
| M4 | Mesomixing time | t_meso = 1.2 (d_feed²/ε_feed)^⅓ | d_feed: m | `mesomixing_time` | Bałdyga, Bourne & Hearn (1997) [doi:10.1016/S0009-2509(96)00430-7](https://doi.org/10.1016/S0009-2509%2896%2900430-7) | ✅ (A ≈ 1–2). ⚠️ Uses the feed-pipe diameter in place of Λ_c. |
| M5 | Feed-point ε | Bulk: P/(ρV). Near impeller: ε_max. Surface: 0.2·ε̄. | W/kg | `operating_point.feed_dissipation` | – | ⚠️ Heuristic (the surface factor) |
| M6 | Characteristic t_rxn | 1st order: 1/k. 2nd order: 1/(kC₀). 0th order: C₀/k. A specified time overrides all of these. | s | `damkohler.characteristic_reaction_time` | Levenspiel (1999) [ISBN 9780471254249](https://openlibrary.org/isbn/9780471254249) | ✅ |
| M7 | Damköhler numbers | Da_macro = θ95/t_rxn; Da_micro = t_E/t_rxn; Da_meso = t_meso/t_rxn; Da_GL = 1/(kLa·t_rxn); Da_SL = 1/(kLa_SL·t_rxn) | – | `damkohler.*`, `operating_point.evaluate_point` | HIM Ch. 13 | ✅ Definition |
| M8 | Da bands | < 0.01, 0.01–0.1, 0.1–1, 1–10, > 10 | – | `mixing_sensitivity_assessment` | – | ⚠️ Heuristic |

## 4. Gas–liquid and liquid–liquid

| # | Quantity | Equation | Variables / units | Code | Source | Status |
|---|----------|----------|-------------------|------|--------|--------|
| L1 | Sparged kLa (van 't Riet) | kLa = 0.026 (P/V)^0.4 v_s^0.5 for coalescing systems; 0.002 (P/V)^0.7 v_s^0.2 for non-coalescing systems | P/V: W/m³; v_s: m/s; kLa: 1/s | `gas_liquid.kla_vant_riet` | van 't Riet (1979) [doi:10.1021/i260071a001](https://doi.org/10.1021/i260071a001) | ✅. ⚠️ Uses the ungassed P/V. Validity is 500–10 000 W/m³, so lab-scale use is an extrapolation. |
| L2 | Surface kL (Lamont–Scott) | kL = 0.4 D_mol^½ (ε/ν)^¼; a = (πD_T²/4)/V | m/s, 1/m | `kla_surface` | Lamont & Scott (1970) [doi:10.1002/aic.690160403](https://doi.org/10.1002/aic.690160403) | ✅ (uses the actual V since the 2026 review) |
| L3 | Hansen distance | Ra = √(4Δδd² + Δδp² + Δδh²) | MPa^½ | `solvent_properties.hansen_distance` | Hansen (2007) [doi:10.1201/9781420006834](https://doi.org/10.1201/9781420006834) | ✅ |
| L4 | Miscibility bands | Ra < 15 miscible; 15–25 borderline; > 25 immiscible | – | `miscibility_assessment` | – | ⚠️ Heuristic |
| L5 | Weber number, d32 | We = ρ_c N² D³/σ; d32/D = 0.053 We^-0.6 (1 + 3φ_d) | – | `liquid_liquid.weber_number`, `sauter_drop_diameter` | Chen & Middleman (1967) [doi:10.1002/aic.690130529](https://doi.org/10.1002/aic.690130529); holdup term as in Calabrese et al. (1986) [doi:10.1002/aic.690320416](https://doi.org/10.1002/aic.690320416) | ✅ coefficient. ❓ Holdup constant 3 (valid for φ ≲ 0.2). |
| L6 | Separation time | t_sep = D_T/v_drop (v_drop from Stokes or Schiller–Naumann); bands at 1 / 10 / 60 min | s | `phase_separation_check` | – | ⚠️ Heuristic |
| L7 | Minimum dispersion speed | N_min = 1.03 √(σ/(ρ_c D³)) (1 + 2.5φ) | rev/s | `minimum_dispersion_speed` | – | ⚠️ Heuristic (not Skelland–Seksaria) |

## 5. Solid–liquid

| # | Quantity | Equation | Variables / units | Code | Source | Status |
|---|----------|----------|-------------------|------|--------|--------|
| S1 | Settling velocity | Stokes velocity, then Schiller–Naumann iteration, C_D = 24/Re(1 + 0.15 Re^0.687). The result is multiplied by sphericity φ. | m/s | `solid_liquid.settling_velocity` | Clift, Grace & Weber (1978) [ISBN 9780121769505](https://openlibrary.org/isbn/9780121769505); Schiller & Naumann (1935) | ✅ for Re_p ≲ 800. ⚠️ The φ multiplier is empirical, and there is no Newton-regime branch. |
| S2 | Zwietering N_js | N_js = S ν^0.1 d_p^0.2 (gΔρ/ρ_L)^0.45 X^0.13 D^-0.85 | X in wt-% (g solid per 100 g liquid) | `zwietering_njs` | Zwietering (1958) [doi:10.1016/0009-2509(58)85031-9](https://doi.org/10.1016/0009-2509%2858%2985031-9) | ✅ |
| S3 | GMB N_js | N_js = z Po^-⅓ D^-⅔ (gΔρ/ρ_L)^0.5 X_v^0.154 d_p^0.167 (C/D)^0.1 | X_v in vol-% | `gmb_njs` | Grenville, Mak & Brown (2015) [doi:10.1016/j.cherd.2015.05.026](https://doi.org/10.1016/j.cherd.2015.05.026) | ✅ |
| S4 | Design N_js | max(Zwietering, GMB) | rev/s | `operating_point.solids_static` | – | ✅ (conservative choice) |
| S5 | Suspension bands | N/N_js < 0.7 / 1.0 / 1.3 | – | `particle_suspension_criterion` | – | ⚠️ Heuristic |
| S6 | k_SL (Ranz–Marshall) | Sh = 2 + 0.6 Re_p^½ Sc^⅓, with Re_p based on the terminal velocity v_t | m/s | `solid_liquid_mass_transfer` | Ranz & Marshall (1952); slip approach of Harriott (1962) [doi:10.1002/aic.690080122](https://doi.org/10.1002/aic.690080122) | ✅. ⚠️ Conservative (no turbulent slip). |
| S7 | kLa_SL | a_s = 6φ_s/d_p; kLa_SL = k_SL·a_s | 1/s | `solid_liquid_kla` | Definition | ✅ |

## 6. Heat balance (Vessel Assessment, Comparison, Sensitivity)

| # | Quantity | Equation | Variables / units | Code | Source | Status |
|---|----------|----------|-------------------|------|--------|--------|
| Q1 | Molar rate | 1st order: r = kC₀. 2nd order: r = kC₀². **0th order: r = k**. Then r_tot = r·V_L. | mol/(L·s), mol/s | `heat_transfer.reaction_rate_mol_per_s` | Levenspiel (1999) | 🔧 Zero order used to return 0 |
| Q2 | Heat generation | **Q_gen = −ΔH·1000·r_tot** (positive when exothermic) | W | `heat_generation_rate` | Energy balance | 🔧 Previously used \|ΔH\|, so endothermic reactions were reported as heat generation |
| Q3 | Feed sensible heat | Q_feed = ṁ_f c_p,f (T_feed − T_process); Q_load = Q_gen + Q_feed | W | `core/services._feed`, `operating_point.evaluate_point` | Energy balance | ✅ |
| Q4 | Cooling capacity | Q_cool = U·A·(T_process − T_coolant), signed | W | `heat_removal_capacity` | Incropera (2007) [ISBN 0471457280](https://openlibrary.org/isbn/0471457280) | ✅ |
| Q5 | Heat-balance ratio | Q_load/Q_cool; bands 0.25 / 0.5 / 0.75 / 1.0 | % | `operating_point`, `heat_balance_assessment` | – | ⚠️ Heuristic bands |
| Q6 | Adiabatic rise | ΔT_ad = −ΔH·C₀/(ρc_p) (signed in the Heat Transfer tool; \|ΔH\| on the Sensitivity page). Stoessel bands 20 / 50 / 200 K. | K | `core/heat_transfer.adiabatic_rise`, `core/sensitivity_rules` | Stoessel (2020) [doi:10.1002/9783527696918](https://doi.org/10.1002/9783527696918) | ✅ |
| Q7 | Simple U | U = U_lo + min(N/3, 1)(U_hi − U_lo). Ranges: glass 100–250, SS 200–500, Hastelloy 200–450, CS 150–350. | W/(m²·K) | `estimate_U` | Perry's 9th ed., Sec. 11 [ISBN 0071834087](https://openlibrary.org/isbn/0071834087) | ✅ ranges. ⚠️ Heuristic interpolation. |
| Q8 | Detailed U | 1/U = 1/h_i + x_w/k_w + x_l/k_l + 1/h_o + R_f | – | `estimate_U_detailed`, `estimate_U_from_resistances` | Incropera Ch. 3 | ✅ |
| Q9 | Process-side h_i | Nu = C Re^⅔ Pr^⅓ (μ/μ_w)^0.14; h_i = Nu·k/D_T. C = 0.36 (Chilton–Drew–Jebens, default; the VA takes μ/μ_w = 1), 0.74 (flat-blade turbine, baffled), 0.33 (Brooks–Su, retreat blade) | – | `utils/calculations/heat_transfer.NUSSELT_CORRELATIONS`, `nusselt_jacket` | Chilton, Drew & Jebens (1944) [doi:10.1021/ie50414a006](https://doi.org/10.1021/ie50414a006); Uhl & Gray (1966) / Perry's Sec. 11; Brooks & Su (1959); Sieder & Tate (1936) [doi:10.1021/ie50324a027](https://doi.org/10.1021/ie50324a027) | ✅ CDJ (DOI). ✅ Flat-blade and Brooks–Su are traced to the cited texts (not re-read). 🔧 Four untraceable options were removed (see Corrections). |
| Q10 | Jacket-side h_o | Laminar (Re < 2300): **Nu = 3.66 + 0.0668 Gz/(1 + 0.04 Gz^⅔)**, Gz = (D_h/L)·Re·Pr with L = 1 m. Turbulent: Nu = 0.023 Re^0.8 Pr^0.4. | – | `utils/calculations/heat_transfer.jacket_side_htc` (`JACKET_PATH_L_M`) | Hausen (1943); Dittus & Boelter (1930); Incropera Ch. 8 | 🔧 The constant was 0.065. ⚠️ L = 1 m is an assumption. |
| Q11 | VA coolant defaults | v_j = 1.0 m/s, D_h = 0.05 m; otherwise h_o = 1500 W/(m²·K) | – | `core/services._heat`, `HeatSpec` | Perry's Sec. 11 | ⚠️ Typical values |
| Q12 | Wall and lining k | SS 15, 316 13.4, 304 14.4, CS 50, Hastelloy 12, glass 1.2, PTFE 0.25, etc. | W/(m·K) | `utils/calculations/heat_transfer.WALL_CONDUCTIVITY(_REF)`, `LINING_CONDUCTIVITY(_REF)` | ASM Handbook Vol. 1; Engineering ToolBox; De Dietrich / Pfaudler | ✅ |
| Q12b | Heat-transfer media (HTF) | Single-point ρ, Cp, μ, k at 25 °C | – | `data/HTM.csv` (vendor PDFs in `data/HTM_datasheets`) | Dow TDS (Syltherm 800/HF/XLT, Dowtherm A/Q); Eastman (Therminol 66 TF-8695, Marlotherm SH MT-10741); Huber; ASHRAE; IAPWS/CRC | ✅ All entries traced to a datasheet or handbook. 🔧 Dowtherm A μ, Dowtherm Q ρ/μ/k, Therminol 66 Cp and Marlotherm SH (all properties) corrected. ⚠️ DW-Therm Cp is read from a chart. |
| Q13 | Fouling | R_f = 2×10⁻⁴ m²·K/W | – | `FOULING_DEFAULT` | TEMA RGP-T-2.4 | ✅ |
| Q14 | Batch heating/cooling time | t = (ρVc_p/UA)·ln((T₀ − T_j)/(T_end − T_j)) | s | `utils/calculations/heat_transfer.time_to_cool_or_heat` | Incropera | ✅ |

## 7. Transient temperature models

| # | Quantity | Equation | Code | Source | Status |
|---|----------|----------|------|--------|--------|
| T1 | VA batch/dosed profile | C(t)·dT/dt = Q_rxn + ṁ_f c_p,f (T_f − T) + UA(t)(T_cool − T), with C(t) = m₀c_p₀ + ṁ_f c_p,f·t. Integrated semi-implicitly. The rate constant is fixed (no Arrhenius term). | `core/batch_temperature.profile` | Stoessel (2020), Ch. 7; Levenspiel | ✅ (balance verified) |
| T2 | T_ad of the whole process | T_ad = [C(0)T₀ + ṁ_f c_p,f t_end T_f − ΔH·1000·n₀]/C(t_end) | same | Energy balance | ✅ |
| T3 | Heat Transfer tool, constant jacket | dT/dt = [UA(T_j − T) + P_ag + Q_rxn]/(ρVc_p), forward Euler | `core/heat_transfer.profile_const_jacket` | Incropera | ✅ |
| T4 | Heat Transfer tool, variable jacket | NTU = UA/(ṁ_j c_p,j); ε = 1 − e^-NTU; Q = ε ṁ_j c_p,j (T_j,in − T) | `profile_variable_jacket` | Incropera Ch. 11 | ✅ |
| T5 | "Initial dT/dt" KPI | \|UA(T_j − T₀) + P_ag\|/(ρVc_p) × 60 | `compute_batch` | Energy balance | 🔧 Previously (q_max − P_ag), which was wrong for heating |
| T6 | Reaction profile (Heat Transfer tool) | Q_rxn = −ΔH·1000·r; ΔT_ad = −ΔH·n₀/(m c_p) | `compute_reaction_profile` | Energy balance | ✅ |

## 8. Fluid properties

| # | Quantity | Equation | Code | Source | Status |
|---|----------|----------|------|--------|--------|
| F1 | Density | ρ(T) = ρ₂₅ + dρ/dT·(T − 25) | `solvent_properties.density` | CRC / Yaws / NIST | ✅ (spot-checked: 12 solvents within 0.5–3 % of CRC/NIST at 25 °C) |
| F2 | Viscosity | μ(T) = μ₂₅ exp[(E_a/R)(1/T_K − 1/298.15)] | `viscosity` | Perry's / DIPPR | ✅ |
| F3 | Surface tension, Cp, k | Linear in T, anchored at 25 °C | `surface_tension`, `specific_heat`, `thermal_conductivity` | Yaws / CRC | ✅ |
| F4 | Diffusivity | D(T) = D_ref (T_K/298.15)(μ_ref/μ(T)) | `diffusivity` | Stokes–Einstein scaling | ✅ |
| F5 | Antoine equation | log₁₀P(mmHg) = A − B/(C + T); T_bp = B/(A − log₁₀P) − C | `vapor_pressure_mmHg`, `boiling_point_at_pressure` | NIST WebBook; Yaws | ✅ |
| F6 | Blend rules | 1/ρ = Σw/ρ; ln μ = Σw ln μ; ln D = Σw ln D; c_p = Σw c_p; σ = Σφσ; k = Σφk | `core/fluids.mixing_rules` | Poling, Prausnitz & O'Connell (2001), Ch. 9–10 | ✅ ρ and c_p (ideal mixing). ⚠️ μ uses mass fractions and no interaction term (it can be off by a factor of 2 or more for water/alcohol). ⚠️ σ and k use linear volume weighting. |

## 9. Scale-up and Bourne Protocol

| # | Quantity | Equation | Code | Source | Status |
|---|----------|----------|------|--------|--------|
| B1 | N for a target P/m | N = ((P/m)·V/(Np D⁵))^⅓, with V = the actual working volume | `core/bourne_plan.n_for_pm` | Definition from H3/H4 | ✅ |
| B2 | Test 1 set-points | 0.1×, 1× and 10× the centre P/m, clamped to the RPM window | `test1_conditions` | Bourne (2003) [doi:10.1021/op020074q](https://doi.org/10.1021/op020074q) | ✅ |
| B3 | Test 3 local ε | ε_loc = r·ε̄; t_E = 17.3(ν/ε_loc)^½ | `test3_conditions` | Bałdyga & Bourne (1999) | ✅ (r is user-supplied) |
| B4 | KPI sensitivity | max\|KPI − centre\|/centre > 5 % | `utils/bourne_kpi` | – | ⚠️ Heuristic threshold (configurable) |
| B5 | Scale-up match | Solve parameter(N or V) = basis value with the full hydro model; flag results outside the window | `core/scale_up.match_parameter` | HIM Ch. 6 and Ch. 9 | ✅ |

## 10. ROM / experimental correlations

| Item | Location | Status |
|------|----------|--------|
| Demo correlations | removed | 🔧 Removed in the second review. They cited untraceable studies and were registered under "Nalas – EasyMax 102", which is not in the vessel DB, so they were never applied. |
| Fitted correlations | `data/fitted_correlations.json` (one surface-kLa fit, for the same non-existent reactor) | ❓ Loaded but unreachable. Re-assign it to a real vessel or delete it. |

## 11. Unit conversions (`core/units.py`)

All factors were checked against NIST SP 811. 🔧 **US gal/h** was 1.0515×10⁻⁵ m³/s, 10× too large; it is now 1.0515×10⁻⁶ m³/s (1 US gal = 3.785411784 L).

---

## Corrections made in the 2026 review

| Item | Before | After | Effect |
|------|--------|-------|--------|
| G3 Klöpper head volume | 0.0847 D³ | 0.0990 D³ | The liquid height in torispherical vessels without a measured dish depth is now slightly lower. |
| H4 Volume in P/V, ε, t_c, γ̇, kLa_surface | πD²H/4 | The actual fill V (L → m³) | In dished vessels, P/V and ε rise by about 12 % (up to 37 %); t_E and η fall; Da_micro falls by about 6 %. "Volume (L)" now equals the entered fill. In Bourne Test 1, the detail table and the planning are now consistent. |
| Q1 Zero-order rate | 0 | r = k | Zero-order reactions now contribute to the heat balance. |
| Q2 Q_gen sign | \|ΔH\| | −ΔH (signed) | Endothermic reactions are no longer counted as heat load. |
| Q10 Hausen constant | 0.065 | 0.0668 | +2.8 % on the laminar jacket h_o. |
| T5 Initial dT/dt | q_max − P_ag | \|UA(T_j − T₀) + P_ag\| | Correct for heating duties. |
| Unit conversion | gal/h 1.0515e-5 | 1.0515e-6 | Conversion fixed. |
| Q9 Nusselt options (second round) | 7 options | 3 options | Removed: "DIN 28131" (that standard covers agitator types, and its constants duplicated CDJ); "Lehrer (anchor/helical)" (Lehrer 1970, [doi:10.1021/i260036a010](https://doi.org/10.1021/i260036a010), is a jacket-side correlation); "Stein–Schmidt" (Chem. Eng. Process. 32:305 is a filtration paper; no such article exists); "Nagata 0.18" (not traceable). The default is now CDJ. |
| Q12b HTF properties (second round) | see the row | datasheets | Dowtherm A μ 2.5 → 3.8 mPa·s. Dowtherm Q ρ 993 → 962, μ 2.2 → 3.5, k 0.114 → 0.121. Therminol 66 Cp 1680 → 1580. Marlotherm SH (dibenzyltoluene): range −15–325 °C, ρ 1039, Cp 1580, **μ 2.8 → 36 mPa·s**, k 0.130. |

Regression tests: `tests/test_calculation_review.py`. The golden baselines in `tests/golden/*.json` were rewritten after confirming that every diff traces to one of these corrections.

## Open items (need a decision or a source)

1. **ε_max coefficient (H11)**: obtain the primary Grenville et al. (2017) article and confirm the 1.04·x form, with x = 15.
2. **`data/fitted_correlations.json`**: its one fit targets a vessel that is not in the database.
3. **Blend viscosity (F6)**: consider mole-fraction Grunberg–Nissan with an interaction parameter, at least for water/alcohol blends.
4. **Partial-dish liquid height (G1)**: replace the linear fill with the exact cap volume–height relation if accuracy at very low fill matters.

Resolved in the second review: the Nusselt and HTF sources (see Corrections), the demo ROM correlations (removed), and duplicate or dead code. `utils/calculations/heat_transfer.py` is now the single home of the heat-transfer correlations and tables; `core/heat_transfer.py` keeps only the Heat Transfer tool simulations. The unused gas-holdup, flooding, complete-dispersion and liquid–liquid mass-transfer functions were removed.
