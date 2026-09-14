# Mixing Sensitivity Webapp: Prioritized Improvement Backlog

This document summarizes the recommended improvements to the mixing-sensitivity and Bourne Protocol workflows, ordered by their impact on calculation accuracy, scientific defensibility, and reactor-process fit assessment.

## Status as of 2026-09-14

Completed in the current implementation pass:
- Item 1: blend-time model corrected to use the flow-number-based circulation relation.
- Item 2: mixed KPI outcomes remain `inconclusive` instead of being promoted to a confirmed sensitivity verdict.
- Item 3: blank KPI cells remain missing (`NaN`) and zero is preserved as a valid analytical value.
- Item 5: upstream input changes invalidate prior Bourne assessments and require reassessment.
- Item 7: imported Bourne metadata is preserved as structured state instead of reconstructed caption text.
- Item 8: critical KPI values can override secondary metrics in the protocol verdict.
- Item 9: KPI-specific thresholds are now applied instead of a single universal 5% rule.
- Item 11: replicate / analytical variability is now treated as a noise floor that must be exceeded before a KPI is classified as sensitive.
- Item 14: the reaction-time cutoff bands are now explicitly flagged as preliminary screening heuristics and steered toward reactor-specific Damköhler numbers (Da_macro / Da_micro).
- Added targeted regression coverage for the above cases.

## Priority 1: Correct Calculation and Logic Defects

1. [x] **Verify the blend-time calculation uses flow number \(N_Q\), not power number \(N_P\).**
   - Inspect `blend_time_turbulent()` in `utils.calculations`.
   - Update both the Test 1 table and report calculations.
   - Add a unit test confirming that increasing \(N_Q\) decreases predicted blend time.

2. [x] **Preserve “possibly sensitive” as an inconclusive result.**
   - Do not export a mixed KPI response as confirmed sensitivity.
   - Use three states: `sensitive`, `not_sensitive`, and `inconclusive`.
   - Preserve this state through the CSV transfer between `bourne_protocol.py` and `mixing_sensitivity.py`.

3. [x] **Replace zero values as missing-data indicators.**
   - Initialize blank KPI responses as `NaN`.
   - Allow zero to be treated as a valid analytical result.
   - Explicitly flag partially completed KPI rows.

4. [x] **Fix the inconsistent ordering of Test 2 conditions.**
   - Use the same Slow, Center, Fast order in the conditions table, KPI table, PDF, and CSV.

5. [x] **Invalidate results when upstream inputs change.**
   - Clear prior assessments whenever reactor, fluid, volume, RPM, geometry, feed, or KPI inputs are edited.
   - Display “Inputs changed, reassessment required.”

6. [x] **Make critical unknowns override low-risk conclusions.**
   - Missing kinetics, enthalpy, or phase information should produce an incomplete assessment rather than a low-to-moderate-risk verdict.

7. [x] **Preserve imported Bourne metadata structurally.**
   - Store project, reactor, fluid, test status, and protocol version as state fields.
   - Do not reconstruct metadata by parsing a display caption.

## Priority 2: Improve Sensitivity Determination

8. [x] **Replace majority voting across KPIs.**
   - A critical impurity or safety-related response should not be outvoted by insensitive secondary KPIs.
   - Classify KPIs as critical, major, or supporting.

9. [x] **Replace the universal 5% threshold with KPI-specific criteria.**
   - Support relative change, absolute change, and specification or acceptance-limit criteria.
   - Include direction of concern, such as increase, decrease, or either.

10. [x] **Handle near-zero center values properly.**
    - Do not automatically assign a 100% change whenever the center value is zero.
    - Use an absolute-difference criterion for impurities or other near-zero measurements.

11. [x] **Add replicate and measurement-variability support.**
    - Capture mean, standard deviation, replicate count, and analytical-method precision.
    - Require both practical and statistical significance where data permit.

12. [x] **Verify that the intended experimental range was achieved.**
    - Calculate the actual low-to-high \(P/m\) ratio after RPM clamping.
    - Do not conclude “mixing-insensitive” if the test covered an inadequate hydrodynamic range.
    - Report “no sensitivity detected over the tested range” instead.

13. [x] **Reduce certainty in mechanism assignments.**
    - Replace “micromixing-controlled,” “mesomixing-controlled,” and “macromixing-controlled” with “consistent with” unless confirmed by additional calculations or experiments.
    - Allow multiple plausible mechanisms.

## Priority 3: Strengthen Engineering Methodology

14. [x] **Use reactor-specific Damköhler numbers instead of reaction-time cutoffs alone.**

    \[
    Da_{\mathrm{micro}} = \frac{t_{\mathrm{micro}}}{t_{\mathrm{rxn}}}
    \]

    \[
    Da_{\mathrm{macro}} = \frac{t_{\mathrm{blend}}}{t_{\mathrm{rxn}}}
    \]

    - Retain the existing reaction-time bands only as preliminary screening heuristics.

15. [~] **Improve the reaction-timescale model.**
    - Support general rate laws, unequal reactant concentrations, parallel and consecutive pathways, catalysis, and semi-batch concentration trajectories.
    - Evaluate the worst-case reaction timescale during the process rather than only the initial bulk condition.
    - Current implementation supports zero-, first-, second-, and pseudo-order laws with a conservative 90%-conversion process-window estimate; direct `t_rxn` overrides remain unchanged.
    - Remaining work: add explicit inputs and trajectory calculations for unequal reactants, parallel/consecutive pathways, catalysis, and semi-batch concentration profiles.

16. [x] **Do not automatically mark every semi-batch process as mesomixing-sensitive.**
    - Treat semi-batch operation as requiring a feed-zone assessment.
    - Consider feed rate, feed concentration, pipe geometry, location, local circulation, reaction time, and accumulation potential.

17. [x] **Separate thermal severity from heat-transfer capability.**
    - Thermal severity: \(\Delta T_{\mathrm{ad}}\), MTSR, and decomposition margin.
    - Heat-transfer fit: peak heat generation versus \(UA\Delta T\).
    - Mixing-thermal coupling: feed-point hot spots and local reagent accumulation.

18. [x] **Separate exothermic and endothermic conclusions.**
    - Use distinct categories for heat-removal risk and heat-input or temperature-collapse risk.
    - Treat reaction-class keywords as prompts for calorimetry, not proof of heat-transfer sensitivity.

19. **Validate hydrodynamic-correlation applicability.**
    - Check Reynolds-number regime, baffling, impeller submergence, liquid height, impeller clearance, non-Newtonian behavior, multiple impellers, gas loading, and solids loading.

20. **Treat Test 3 local energy-dissipation ratios as configurable estimates.**
    - Clearly label the current 0.1, 1.0, and 3.0 ratios as illustrative.
    - Allow user-entered, experimentally derived, or CFD-derived local values.

## Priority 4: Expand Reactor-Process Fit Coverage

21. **Add solids suspension and dissolution assessments.**

22. **Add gas-liquid and liquid-solid mass-transfer capacity-to-demand calculations.**

23. **Add liquid-liquid dispersion and emulsion behavior.**

24. **Add crystallization and precipitation sensitivity.**
    - Include local supersaturation, nucleation, agglomeration, and particle-size effects.

25. **Add local pH and local stoichiometry sensitivity.**

26. **Capture feed-system details.**
    - Feed-pipe diameter, insertion depth, coordinates, velocity, momentum, and distance from the impeller.

27. **Connect feed locations to CFD-derived zones.**
    - Use local energy dissipation, circulation, residence time, and compartment exchange rates from the larger webapp.

28. **Add a confidence rating to every conclusion.**
    - High, medium, low, or indeterminate based on data quality, test range, replicates, and use of measured versus proxy inputs.

## Recommended Implementation Sequence

### Immediate Release Blockers

Complete items **1 through 7** before treating the app outputs as internally consistent.

### Next Development Sprint

Complete items **8 through 13** to make the experimental sensitivity classification defensible.

### Methodology Upgrade

Complete items **14 through 20** to convert the workflow from a heuristic screen into a stronger engineering assessment.

### Longer-Term Integration

Complete items **21 through 28** to support comprehensive reactor-process fit and connect the sensitivity workflow to CFD and vessel-assessment tools.
