<!--
Equations Reference source (served by GET /api/v1/equations, parsed by core/equations.py).

Format
  # Section title           one per section; text before the first "##" is the section intro
  ## Entry title             one per equation / topic
  Used in: Page A, Page B    optional, first line of the entry
  ...body...                 Markdown with $inline$ and $$display$$ LaTeX; the first $$ block
                             is shown as the entry's headline equation
  Sources:                   optional, last block of the entry: one "- " bullet per source

Keep in sync with docs/EQUATIONS_REGISTRY.md (code locations and verification status).
-->

# Vessel geometry

## Liquid height from fill volume
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol, Heat Transfer Tool, Vessel Database

$$
H = \begin{cases} h_{d}\,\dfrac{V}{V_{d}} & V \le V_{d} \\[6pt] \min\!\left(h_{d} + \dfrac{V - V_{d}}{\pi {D_T}^2/4},\; H_{max}\right) & V > V_{d} \end{cases}
$$

| Bottom head | Depth $h_d$ | Volume $V_d$ |
|---|---|---|
| Flat | $0$ | $0$ |
| 2:1 semi-ellipsoidal (default) | $D_T/4$ | $\pi {D_T}^3/24$ |
| Torispherical (Klöpper, DIN 28011) | $0.1935\,D_T$ | $0.0990\,{D_T}^3$ |
| Hemispherical | $D_T/2$ | $\pi {D_T}^3/12$ |
| Shallow dished (spherical cap) | $0.1\,D_T$ | $\pi h_d\,(3R^2 + {h_d}^2)/6$ |
| Conical, wall angle $\theta$ (default 45°) | $R\tan\theta$ | $\pi {D_T}^2 h_d/12$ |
| Any curved head with a measured depth $h_d$ | $h_d$ | $\pi {D_T}^2 h_d/6$ (half-ellipsoid) |

$V$ is the working volume (m³), $D_T$ the tank diameter, $R = D_T/2$ and $H_{max}$ the brim height. A measured dish depth from the vessel database replaces the default depth. Inside the dish the height is interpolated linearly in volume, which is an approximation for curved heads. The Klöpper constants come from integrating the head profile (crown radius $D_T$, knuckle radius $0.1\,D_T$).

Sources:
- DIN 28011 (torispherical heads) and DIN 28013 (semi-ellipsoidal heads)
- Perry, R.H. & Green, D.W. (2019). [*Perry's Chemical Engineers' Handbook*](https://openlibrary.org/isbn/0071834087), 9th ed., Sec. 10

## Wetted heat-transfer area
Used in: Vessel Assessment, Vessel Comparison, Heat Transfer Tool

$$
A = A_{dish} + \pi D_T\,(H - h_d), \qquad A = A_{dish}\,\frac{H}{h_d} \quad (H < h_d)
$$

| Bottom head | Full head area $A_{dish}$ |
|---|---|
| Flat | $\pi {D_T}^2/4$ |
| 2:1 semi-ellipsoidal | $1.084\,{D_T}^2$ |
| Torispherical (Klöpper) | $0.99\,{D_T}^2$ |
| Conical | $\dfrac{\pi {D_T}^2}{4}\sqrt{1 + (h_d/R)^2}$ ($\sqrt{2}\,\pi {D_T}^2/4$ at 45°) |

The jacket is assumed to cover the whole wetted wall. When the liquid is inside the head, the head area is pro-rated by $H/h_d$ (approximate).

Sources:
- DIN 28011 / DIN 28013 head geometry; oblate-spheroid and cone surface-area formulas

## Free-surface vortex (Nagata)
Used in: Vessel Database

$$
z(r) - z_0 = \begin{cases} \dfrac{\omega^2 r^2}{2g} & r \le r_c \\[6pt] \dfrac{\omega^2 {r_c}^2}{2g}\left(2 - \dfrac{{r_c}^2}{r^2}\right) & r > r_c \end{cases}
$$

$\omega = 2\pi N$ (rad/s), $r_c$ is the critical radius (taken as the impeller radius $D/2$), $g = 9.81$ m/s² and $z_0$ the surface height on the shaft. $z_0$ is found so that the liquid volume above the bottom head equals the static fill volume. The core rotates as a solid body and the outer region as a free vortex (combined Rankine vortex). Because the core is assumed to rotate at the full impeller speed, the depth is an upper bound. With three or more baffles the surface is drawn flat; with one or two baffles the unbaffled result is shown as an upper bound. Water properties are used for the reported $Re$ and $Fr$.

Sources:
- Nagata, S. (1975). [*Mixing: Principles and Applications*](https://openlibrary.org/isbn/0470628634), Ch. 1
- Busciglio, A., Scargiali, F., Grisafi, F. & Brucato, A. (2013). Vortex shape in unbaffled stirred vessels. *Chem. Eng. Sci.* 104, 868–880. [doi:10.1016/j.ces.2013.10.019](https://doi.org/10.1016/j.ces.2013.10.019)
- Rieger, F., Ditl, P. & Novák, V. (1979). Vortex depth in mixed unbaffled vessels. *Chem. Eng. Sci.* 34, 397–403. [doi:10.1016/0009-2509(79)85073-3](https://doi.org/10.1016/0009-2509%2879%2985073-3)

# Power & flow

## Impeller Reynolds number
Used in: all hydrodynamic pages

$$
Re = \frac{\rho\,N\,D^2}{\mu}
$$

| Symbol | Description | Units |
|---|---|---|
| $\rho$ | Liquid density | kg/m³ |
| $N$ | Impeller speed | rev/s |
| $D$ | Impeller diameter | m |
| $\mu$ | Dynamic viscosity | Pa·s |

$Re < 10$ laminar, $10$–$10^4$ transitional, $Re > 10^4$ fully turbulent.

Sources:
- Paul, E.L., Atiemo-Obeng, V.A. & Kresta, S.M. (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Wiley, Ch. 6

## Power number and impeller power
Used in: all hydrodynamic pages, Heat Transfer Tool (agitator heat input)

$$
P = N_p\,\rho\,N^3 D^5
$$

| Impeller | Turbulent $N_p$ |
|---|---|
| Rushton turbine (6-blade) | 5.0 |
| Pitched-blade turbine (45°, 4-blade) | 1.27 |
| Retreat-curve impeller | 0.3–0.5 |
| A310 / A320 hydrofoil | 0.3 |

The vessel's measured $N_p$ is used when available. Otherwise a baffled-Rushton fallback applies: laminar $N_p = 70/Re$ for $Re \le 10$; the turbulent plateau for $Re \ge 10^4$; and log–log interpolation in between (an approximation of the measured curve). All impeller power ends up as heat in the batch, so the Heat Transfer tool adds $P$ to the energy balance.

Sources:
- Rushton, J.H., Costich, E.W. & Everett, H.J. (1950). Power characteristics of mixing impellers. *Chem. Eng. Prog.* 46, 395–404, 467–476
- Bates, R.L., Fondy, P.L. & Corpstein, R.R. (1963). *Ind. Eng. Chem. Process Des. Dev.* 2(4), 310–314
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 6

## Specific power input
Used in: all hydrodynamic pages

$$
\frac{P}{V}\ [\mathrm{W/m^3}], \qquad \bar\varepsilon = \frac{P}{\rho V}\ [\mathrm{W/kg}]
$$

$V$ is the **actual fill volume**, including the bottom head, not the cylinder $\pi {D_T}^2 H/4$. All turbulence time and length scales use the mass-specific $\bar\varepsilon$ in W/kg (= m²/s³). The van 't Riet $k_La$ uses $P/V$ in W/m³.

Sources:
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 6

## Tip speed
Used in: Vessel Assessment, Vessel Comparison

$$
u_{tip} = \pi N D
$$

A common scale-up criterion for shear-sensitive systems.

Sources:
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 6

## Pumping rate and circulation time
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol

$$
Q = N_Q\,N D^3, \qquad t_c = \frac{V}{N_Q\,N D^3}
$$

| Impeller | $N_Q$ |
|---|---|
| Rushton turbine | 0.72 (default) |
| Pitched-blade turbine, down-pumping | 0.79 |
| A310 hydrofoil | 0.56 |

$t_c$ is the mean time for a fluid element to make one loop through the impeller zone.

Sources:
- Nienow, A.W. (1997). On impeller circulation and mixing effectiveness in the turbulent flow regime. [*Chem. Eng. Sci.*](https://doi.org/10.1016/S0009-2509%2897%2900072-9) 52(15), 2557–2565
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 6 and 9

## Torque
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol

$$
\Lambda = \frac{P}{2\pi N}
$$

Torque (N·m). Torque per unit volume $\Lambda/V$ is reported as a scale-independent measure of mechanical load.

Sources:
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 6

## Froude number
Used in: Vessel Assessment, Vessel Comparison

$$
Fr = \frac{N^2 D}{g}
$$

Ratio of inertial to gravitational forces; it indicates free-surface vortexing in unbaffled or partially baffled vessels.

Sources:
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 6

# Turbulence & shear

## Kolmogorov length scale
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol

$$
\eta = \left(\frac{\nu^3}{\bar\varepsilon}\right)^{1/4}
$$

The smallest eddy size, typically 10–100 µm in stirred tanks. $\nu = \mu/\rho$ (m²/s) and $\bar\varepsilon$ is in W/kg.

Sources:
- Kolmogorov, A.N. (1991). The local structure of turbulence in incompressible viscous fluid for very large Reynolds numbers. [*Proc. R. Soc. Lond. A*](https://doi.org/10.1098/rspa.1991.0075) 434, 9–13 (translation of the 1941 paper)

## Maximum local energy dissipation
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol

$$
\varepsilon_{max} = 1.04\,x\,{N_p}^{3/4} N^3 D^2 \approx 15.6\,{N_p}^{3/4} N^3 D^2 \quad (x = 15)
$$

The dissipation rate in the impeller discharge (W/kg), typically one to two orders of magnitude above the mean.

Sources:
- Grenville, R.K., Giacomelli, J.J., Brown, D.A.R. & Padron, G.A. (2017). Mixing: Impeller performance in stirred tanks. *Chemical Engineering* 124(8), 42 ([ResearchGate copy](https://www.researchgate.net/publication/319042061_Mixing_Impeller_performance_in_stirred_tanks), opens in a browser only)
- Kresta, S.M. & Wood, P.E. (1993). [*Chem. Eng. Sci.*](https://doi.org/10.1016/0009-2509%2893%2980346-R) 48(10), 1761–1774 (measured $\varepsilon_{max}/\bar\varepsilon$)

## Average and maximum shear rate
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol

$$
\dot\gamma_{avg} = \sqrt{\frac{P}{\mu V}}, \qquad \dot\gamma_{max} = \sqrt{\frac{\varepsilon_{max}}{\nu}}
$$

$\dot\gamma_{avg}$ is the Camp–Stein RMS velocity gradient, from equating volume-averaged viscous dissipation $\mu\dot\gamma^2$ to $P/V$. $\dot\gamma_{max}$ applies the same identity $\varepsilon = \nu\dot\gamma^2$ to the impeller-zone dissipation. The Newtonian shear stress follows as $\tau = \mu\dot\gamma$ (Pa).

Sources:
- Camp, T.R. & Stein, P.C. (1943). Velocity gradients and internal work in fluid motion. *J. Boston Soc. Civ. Eng.* 30, 219–237
- Tennekes, H. & Lumley, J.L. (1972). *A First Course in Turbulence*, MIT Press, Ch. 3

## Energy dissipation / circulation function (EDCF)
Used in: Vessel Assessment, Vessel Comparison

$$
\text{EDCF} = \frac{\varepsilon_{max}}{t_c}\quad [\mathrm{W/(kg\,s)}]
$$

Combines the intensity of the impeller zone with how often fluid passes through it. Mixing Lab uses $\varepsilon_{max}$ as the intensity term, whereas the original definition uses $P/(kD^3)$, so absolute values are not comparable with literature EDCF values.

Sources:
- Jüsten, P., Paul, G.C., Nienow, A.W. & Thomas, C.R. (1996). Dependence of mycelial morphology on impeller type and agitation intensity. [*Biotechnol. Bioeng.*](https://doi.org/10.1002/%28SICI%291097-0290%2819961220%2952:6%3C672::AID-BIT5%3E3.0.CO;2-L) 52(6), 672–684

# Mixing times

## Blend time (95 %)
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol, Reaction Sensitivity

$$
\theta_{95} = \frac{5.2\,T^{1.5} H^{0.5}}{{N_p}^{1/3}\,N D^2}
$$

Time to 95 % homogeneity on the bulk scale; equivalent to $N\theta_{95} = 5.2\,{N_p}^{-1/3}(T/D)^2(H/T)^{1/2}$. $T$ is the tank diameter and $H$ the liquid height. The correlation is valid for fully turbulent flow ($Re > 10^4$) and $H/T \approx 1$; outside that range treat the value as indicative.

Sources:
- Grenville, R.K. (1992). *Blending of viscous Newtonian and pseudo-plastic fluids*, PhD thesis, Cranfield
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 9

## Engulfment micromixing time
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol, Reaction Sensitivity

$$
t_E = 17.3\left(\frac{\nu}{\varepsilon}\right)^{1/2}
$$

Time for mixing at the smallest (molecular) scales. It is evaluated with the mean $\bar\varepsilon$, and with $\varepsilon_{max}$ for $t_{E,local}$, which is relevant when the feed enters the impeller discharge.

Sources:
- Bałdyga, J. & Bourne, J.R. (1999). [*Turbulent Mixing and Chemical Reactions*](https://openlibrary.org/isbn/0471981710), Wiley

## Mesomixing time
Used in: Vessel Assessment, Vessel Comparison

$$
t_{meso} = A\left(\frac{{\Lambda_c}^2}{\varepsilon_{feed}}\right)^{1/3} \approx 1.2\left(\frac{{d_{feed}}^2}{\varepsilon_{feed}}\right)^{1/3}
$$

Inertial-convective break-up of the feed plume. The feed-pipe inner diameter $d_{feed}$ (m) stands in for the integral scale $\Lambda_c$. The literature constant is $A \approx 1$–2; 1.2 is used here.

Sources:
- Bałdyga, J., Bourne, J.R. & Hearn, S.J. (1997). Interaction between chemical reactions and mixing on various scales. [*Chem. Eng. Sci.*](https://doi.org/10.1016/S0009-2509%2896%2900430-7) 52(4), 457–466

## Energy dissipation at the feed point
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol

$$
\varepsilon_{feed} = r\,\bar\varepsilon
$$

| Feed location | $\varepsilon_{feed}$ |
|---|---|
| Bulk (default) | $\bar\varepsilon$ |
| Near impeller | $\varepsilon_{max}$ |
| Liquid surface | $0.2\,\bar\varepsilon$ |

The surface factor is a heuristic; measured near-surface ratios are about 0.1–0.5. In Bourne Test 3 you enter the ratio $r$ for each feed location.

Sources:
- Kresta, S.M. & Wood, P.E. (1993). [*Chem. Eng. Sci.*](https://doi.org/10.1016/0009-2509%2893%2980346-R) 48(10), 1761–1774

# Reaction time & Damköhler numbers

## Characteristic reaction time
Used in: Vessel Assessment, Vessel Comparison, Reaction Sensitivity

$$
t_{rxn} = \frac{1}{k}\ \text{(1st order)}, \qquad \frac{1}{k\,C_0}\ \text{(2nd order)}, \qquad \frac{C_0}{k}\ \text{(0th order)}
$$

| Symbol | Description | Units |
|---|---|---|
| $k$ | Rate constant | 1/s (1st), L/(mol·s) (2nd), mol/(L·s) (0th) |
| $C_0$ | Initial (limiting) concentration | mol/L |

$t_{rxn}$ is the initial-rate time constant (the e-folding time for first order), not the half-life. The second-order form assumes equimolar reagents. A directly specified $t_{rxn}$ overrides these. The 90 % conversion time is shown for information only: it is longer and therefore not conservative for $Da$.

Sources:
- Levenspiel, O. (1999). [*Chemical Reaction Engineering*](https://openlibrary.org/isbn/9780471254249), 3rd ed., Wiley, Ch. 3

## Damköhler numbers
Used in: Vessel Assessment, Vessel Comparison, Reaction Sensitivity

$$
Da_{macro} = \frac{\theta_{95}}{t_{rxn}}, \quad Da_{meso} = \frac{t_{meso}}{t_{rxn}}, \quad Da_{micro} = \frac{t_E}{t_{rxn}}, \quad Da_{GL} = \frac{1}{k_La\,t_{rxn}}, \quad Da_{SL} = \frac{1}{k_La_{SL}\,t_{rxn}}
$$

| $Da$ | Interpretation |
|---|---|
| $< 0.01$ | Reaction-limited, insensitive to mixing / transfer |
| $0.01$–$0.1$ | Likely insensitive |
| $0.1$–$1$ | Potentially sensitive |
| $1$–$10$ | Mixing- or transfer-sensitive |
| $> 10$ | Strongly mixing- or transfer-limited |

The bands are order-of-magnitude screening thresholds. $Da_{GL}$ uses the larger of the sparged and free-surface $k_La$; $Da_{GL}$ and $Da_{SL}$ are zero when that phase is absent.

Sources:
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 13

# Mass transfer

## Sparged gas–liquid kLa (van 't Riet)
Used in: Vessel Assessment, Vessel Comparison

$$
k_La = C_1 \left(\frac{P}{V}\right)^{C_2} {v_s}^{C_3}
$$

| System | $C_1$ | $C_2$ | $C_3$ |
|---|---|---|---|
| Coalescing (pure liquids) | 0.026 | 0.4 | 0.5 |
| Non-coalescing (electrolytes) | 0.002 | 0.7 | 0.2 |

$P/V$ in W/m³ and the superficial gas velocity $v_s$ in m/s give $k_La$ in 1/s. The app uses the ungassed $P/V$, which overestimates $k_La$ when gassing lowers the power. The fitted range is $V$ = 0.002–4.4 m³ and $P/V$ = 500–10 000 W/m³ (±20–40 %), so lab vessels below 500 W/m³ are an extrapolation. No sparging means $k_La = 0$.

Sources:
- van 't Riet, K. (1979). Review of measuring methods and results in non-viscous gas–liquid mass transfer in stirred vessels. [*Ind. Eng. Chem. Process Des. Dev.*](https://doi.org/10.1021/i260071a001) 18(3), 357–364

## Free-surface kLa (Lamont–Scott)
Used in: Vessel Assessment, Vessel Comparison, Bourne Protocol

$$
k_La_{surf} = 0.4\,{D_{mol}}^{1/2}\left(\frac{\bar\varepsilon}{\nu}\right)^{1/4}\cdot\frac{\pi {D_T}^2/4}{V}
$$

| Gas in water, 25 °C | $D_{mol}$ (m²/s) |
|---|---|
| O₂ | 2.1 × 10⁻⁹ |
| CO₂, N₂ | 1.9 × 10⁻⁹ |
| H₂ | 4.5 × 10⁻⁹ |

Headspace transfer through the flat free surface. This is the eddy-cell surface-renewal model.

Sources:
- Lamont, J.C. & Scott, D.S. (1970). An eddy cell model of mass transfer into the surface of a turbulent liquid. [*AIChE J.*](https://doi.org/10.1002/aic.690160403) 16(4), 513–519

## Solid–liquid mass transfer
Used in: Vessel Assessment, Vessel Comparison

$$
Sh = 2 + 0.6\,{Re_p}^{1/2} Sc^{1/3}, \qquad k_{SL} = \frac{Sh\,D_{mol}}{d_p}, \qquad k_La_{SL} = k_{SL}\,\frac{6\,\phi_s}{d_p}
$$

$Re_p = \rho_L v_t d_p/\mu$ uses the terminal settling velocity $v_t$ (Harriott's slip approach). This is a conservative lower bound, because turbulence raises the true slip velocity. $Sc = \nu/D_{mol}$ and $\phi_s$ is the solids volume fraction.

Sources:
- Ranz, W.E. & Marshall, W.R. (1952). Evaporation from drops. *Chem. Eng. Prog.* 48, 141–146, 173–180
- Harriott, P. (1962). Mass transfer to particles: Part I. Suspended in agitated tanks. [*AIChE J.*](https://doi.org/10.1002/aic.690080122) 8(1), 93–101

## Liquid–liquid dispersion screen
Used in: Fluid Database (blends)

$$
We = \frac{\rho_c N^2 D^3}{\sigma_{LL}}, \qquad \frac{d_{32}}{D} = 0.053\,We^{-0.6}(1 + 3\phi_d)
$$

$$
t_{sep} = \frac{D_T}{v_{drop}}, \qquad N_{min} = 1.03\sqrt{\frac{\sigma_{LL}}{\rho_c D^3}}\,(1 + 2.5\,\phi_d)
$$

$\rho_c$ is the continuous-phase density and $\sigma_{LL}$ the interfacial tension (N/m). $\phi_d$ is the dispersed volume fraction, capped at 0.95. $v_{drop}$ is computed like particle settling (Stokes / Schiller–Naumann).

Separation bands are heuristic: < 1 min rapid, 1–10 min moderate, 10–60 min slow, > 1 h very stable. $N_{min}$ is a critical-Weber heuristic, not a published correlation. The $(1 + 3\phi_d)$ term holds for $\phi_d \lesssim 0.2$.

Sources:
- Chen, H.T. & Middleman, S. (1967). Drop size distribution in agitated liquid–liquid systems. [*AIChE J.*](https://doi.org/10.1002/aic.690130529) 13(5), 989–995
- Calabrese, R.V., Chang, T.P.K. & Dang, P.T. (1986). Drop breakup in turbulent stirred-tank contactors, Part I. [*AIChE J.*](https://doi.org/10.1002/aic.690320416) 32(4), 657–666

# Solid suspension

## Terminal settling velocity
Used in: Vessel Assessment, Vessel Comparison

$$
v_t = \sqrt{\frac{4\,g\,d_p\,\Delta\rho}{3\,C_D\,\rho_L}}\cdot\phi, \qquad C_D = \frac{24}{Re_p}\left(1 + 0.15\,{Re_p}^{0.687}\right)
$$

The calculation starts from Stokes' law, $v_t = {d_p}^2 g\,\Delta\rho/(18\mu)$, and iterates with the Schiller–Naumann drag. That drag correlation is valid for $Re_p \lesssim 800$; there is no Newton-regime branch. The particle Reynolds number is $Re_p = \rho_L v_t d_p/\mu$. Multiplying by the sphericity $\phi$ is a simple empirical shape correction.

Sources:
- Clift, R., Grace, J.R. & Weber, M.E. (1978). [*Bubbles, Drops, and Particles*](https://openlibrary.org/isbn/9780121769505), Academic Press
- Schiller, L. & Naumann, A. (1935). *Z. Ver. Dtsch. Ing.* 77, 318–320

## Just-suspended speed (Zwietering)
Used in: Vessel Assessment, Vessel Comparison

$$
N_{js} = S\,\nu^{0.1} {d_p}^{0.2}\left(\frac{g\,\Delta\rho}{\rho_L}\right)^{0.45} X^{0.13} D^{-0.85}
$$

| Impeller / geometry | $S$ |
|---|---|
| Pitched-blade turbine (down-pumping), $D/T \approx 0.4$ | 4.5–6.5 |
| Rushton turbine, $D/T \approx 0.33$ | 7–9 |
| A310 hydrofoil, $D/T \approx 0.4$ | 3–5 |

$X$ is the solids loading in wt-% (g solid per 100 g liquid), $d_p$ in m and $N_{js}$ in rev/s.

Sources:
- Zwietering, Th.N. (1958). Suspending of solid particles in liquid by agitators. [*Chem. Eng. Sci.*](https://doi.org/10.1016/0009-2509%2858%2985031-9) 8(3–4), 244–253

## Just-suspended speed (Grenville–Mak–Brown)
Used in: Vessel Assessment, Vessel Comparison

$$
N_{js} = z\,{N_p}^{-1/3} D^{-2/3}\left(\frac{g\,\Delta\rho}{\rho_L}\right)^{1/2} {X_v}^{0.154} {d_p}^{0.167}\left(\frac{C}{D}\right)^{0.1}
$$

$X_v$ is the solids volume percentage and $C/D$ the clearance-to-diameter ratio. The design value is $N_{js} = \max(N_{js,Zw}, N_{js,GMB})$, which is conservative.

Sources:
- Grenville, R.K., Mak, A.T.C. & Brown, D.A.R. (2015). Suspension of solid particles in vessels agitated by axial flow impellers. [*Chem. Eng. Res. Des.*](https://doi.org/10.1016/j.cherd.2015.05.026) 100, 282–291

## Suspension quality
Used in: Vessel Assessment, Vessel Comparison

| $N/N_{js}$ | Assessment |
|---|---|
| $< 0.7$ | Poorly suspended |
| $0.7$–$1.0$ | Partially suspended |
| $1.0$–$1.3$ | Just suspended |
| $> 1.3$ | Fully / homogeneously suspended |

The band edges are screening heuristics.

Sources:
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 10

# Heat balance

## Reaction heat release
Used in: Vessel Assessment, Vessel Comparison

$$
Q_{gen} = -\Delta H_{rxn}\cdot 1000\cdot r\,V_L, \qquad r = k\ \text{(0th)},\quad k\,C_0\ \text{(1st)},\quad k\,{C_0}^2\ \text{(2nd)}
$$

$\Delta H_{rxn}$ is in kJ/mol (**negative = exothermic**), $r$ in mol/(L·s) at the initial concentration (worst case) and $V_L$ in L. $Q_{gen}$ is in W: positive for exothermic, negative for endothermic.

Sources:
- Levenspiel, O. (1999). [*Chemical Reaction Engineering*](https://openlibrary.org/isbn/9780471254249), Ch. 9

## Adiabatic temperature rise
Used in: Reaction Sensitivity, Heat Transfer Tool

$$
\Delta T_{ad} = \frac{-\Delta H_{rxn}\,C_0}{\rho\,C_p}
$$

$\Delta H$ is in J/mol, $C_0$ in mol/m³ and $\rho C_p$ in J/(m³·K). Severity bands (Stoessel): < 20 K low, 20–50 K moderate, 50–200 K high, > 200 K very high. For high severity, assess the MTSR and secondary decomposition.

Sources:
- Stoessel, F. (2020). [*Thermal Safety of Chemical Processes*](https://doi.org/10.1002/9783527696918), 2nd ed., Wiley-VCH, Ch. 2–3

## Feed sensible heat and net heat load
Used in: Vessel Assessment

$$
Q_{feed} = \dot m_f\,C_{p,f}\,(T_{feed} - T_{process}), \qquad Q_{load} = Q_{gen} + Q_{feed}
$$

$\dot m_f = \dot V_f\rho_f$. Feed properties are taken at the feed temperature. A feed warmer than the batch adds to the cooling duty; a colder feed reduces it.

Sources:
- Incropera, F.P. *et al.* (2007). [*Fundamentals of Heat and Mass Transfer*](https://openlibrary.org/isbn/0471457280), 6th ed., Wiley, Ch. 1

## Cooling capacity and heat-balance ratio
Used in: Vessel Assessment, Vessel Comparison

$$
Q_{cool} = U A\,(T_{process} - T_{coolant}), \qquad \text{ratio} = \frac{Q_{load}}{Q_{cool}}
$$

| $Q_{load}/Q_{cool}$ | Assessment |
|---|---|
| $< 0.25$ | Easily manageable |
| $0.25$–$0.5$ | Comfortable margin |
| $0.5$–$0.75$ | Moderate, monitor closely |
| $0.75$–$1.0$ | Tight, limited safety margin |
| $> 1.0$ | Insufficient cooling |

The driving force is signed: a coolant warmer than the batch gives no cooling. The bands are heuristic margins.

Sources:
- Incropera *et al.* (2007). [*Fundamentals of Heat and Mass Transfer*](https://openlibrary.org/isbn/0471457280), Ch. 3

## Batch and dosed temperature profile
Used in: Vessel Assessment

$$
C(t)\,\frac{dT}{dt} = Q_{rxn} + \dot m_f C_{p,f}(T_f - T) + UA(t)\,(T_{cool} - T), \qquad C(t) = m_0 C_{p,0} + \dot m_f C_{p,f}\,t
$$

$Q_{rxn} = -\Delta H\cdot 1000\cdot dn/dt$, with $n$ the moles reacted.
- **Batch:** both reagents are charged at $C_0$ and the run goes to 99 % conversion (capped at 24 h).
- **Dosed:** the co-reagent ($n_0 = C_0V_0$) is fed at a constant rate, so unreacted reagent can accumulate.

$UA(t)$ follows the wetted area as the volume grows. The rate constant is fixed (no Arrhenius term). The balance is integrated semi-implicitly. The adiabatic end temperature is $T_{ad} = [C(0)T_0 + \dot m_f C_{p,f} t_{end} T_f - \Delta H\cdot 1000\cdot n_0]/C(t_{end})$.

Sources:
- Stoessel, F. (2020). [*Thermal Safety of Chemical Processes*](https://doi.org/10.1002/9783527696918), Ch. 7 (semi-batch reactors)

# Heat-transfer coefficients

## Overall heat-transfer coefficient
Used in: Vessel Assessment, Vessel Comparison, Heat Transfer Tool

$$
\frac{1}{U} = \frac{1}{h_i} + \frac{x_w}{k_w} + \frac{x_l}{k_l} + \frac{1}{h_o} + R_f
$$

| Symbol | Description | Units |
|---|---|---|
| $h_i$ | Process-side film coefficient | W/(m²·K) |
| $x_w/k_w$ | Wall thickness / conductivity | m, W/(m·K) |
| $x_l/k_l$ | Lining thickness / conductivity (if lined) | m, W/(m·K) |
| $h_o$ | Jacket-side film coefficient | W/(m²·K) |
| $R_f$ | Fouling resistance, default $2\times10^{-4}$ | m²·K/W |

If the data for the film coefficients are missing, the Vessel Assessment falls back to a material-based estimate:

$$
U = U_{lo} + \min(N/3,\,1)\,(U_{hi} - U_{lo})
$$

This interpolation is a heuristic. The $U$ ranges (W/(m²·K)) by material are:

| Material | $U_{lo}$–$U_{hi}$ |
|---|---|
| Glass-lined | 100–250 |
| Stainless steel | 200–500 |
| Hastelloy | 200–450 |
| Carbon steel | 150–350 |

Sources:
- Incropera *et al.* (2007). [*Fundamentals of Heat and Mass Transfer*](https://openlibrary.org/isbn/0471457280), Ch. 3
- TEMA (2019). *Standards of the Tubular Exchanger Manufacturers Association*, 10th ed., RGP-T-2.4 (fouling)
- Perry & Green (2019). [*Perry's Chemical Engineers' Handbook*](https://openlibrary.org/isbn/0071834087), Sec. 11 (typical $U$)

## Process-side film coefficient
Used in: Vessel Assessment, Vessel Comparison, Heat Transfer Tool

$$
Nu = \frac{h_i D_T}{k_f} = C\,Re^{2/3} Pr^{1/3}\left(\frac{\mu}{\mu_w}\right)^{0.14}, \qquad Pr = \frac{C_p\,\mu}{k_f}
$$

| Correlation | $C$ | Application |
|---|---|---|
| Chilton–Drew–Jebens (paddle), default | 0.36 | Jacketed vessel, paddle-type impeller, turbulent |
| Flat-blade turbine (baffled) | 0.74 | Baffled vessel with a Rushton-type turbine |
| Brooks–Su (retreat blade) | 0.33 | Retreat-curve impeller in a glass-lined vessel |

$Re$ uses the impeller diameter. The Vessel Assessment uses Chilton–Drew–Jebens with $\mu/\mu_w = 1$; the Heat Transfer tool lets you choose the correlation and the wall viscosity.

The 2026 review removed four options that could not be traced to a primary source:
- "DIN 28131": that standard defines agitator types, not a heat-transfer correlation.
- "Lehrer": Lehrer (1970) is a jacket-side correlation.
- "Stein–Schmidt 1993": no such paper exists at the cited reference.
- "Nagata 0.18 exponent".

Sources:
- Chilton, T.H., Drew, T.B. & Jebens, R.H. (1944). Heat transfer coefficients in agitated vessels. [*Ind. Eng. Chem.*](https://doi.org/10.1021/ie50414a006) 36(6), 510–516
- Uhl, V.W. & Gray, J.B. (1966). *Mixing: Theory and Practice*, Vol. 1, Academic Press; Perry & Green (2019), Sec. 11
- Brooks, G. & Su, G.-J. (1959). Heat transfer in agitated kettles. *Chem. Eng. Prog.* 55(10), 54–57
- Sieder, E.N. & Tate, G.E. (1936). [*Ind. Eng. Chem.*](https://doi.org/10.1021/ie50324a027) 28(12), 1429–1435 (wall-viscosity term)

## Jacket-side film coefficient
Used in: Vessel Assessment, Heat Transfer Tool

$$
Nu_j = \begin{cases} 3.66 + \dfrac{0.0668\,Gz}{1 + 0.04\,Gz^{2/3}}, \quad Gz = \dfrac{D_h}{L}Re_j Pr_j & Re_j < 2300 \\[8pt] 0.023\,{Re_j}^{0.8} {Pr_j}^{0.4} & Re_j \ge 2300 \end{cases}
$$

$h_o = Nu_j k_j/D_h$ and $Re_j = \rho_j v_j D_h/\mu_j$, using the coolant (HTF) properties. The flow length is taken as $L$ = 1 m. The Vessel Assessment defaults are $v_j$ = 1.0 m/s and $D_h$ = 0.05 m. Condensing steam uses a fixed $h_o$ = 8000 W/(m²·K). Without a coolant, $h_o$ = 1500 W/(m²·K), a typical simple-jacket value.

Sources:
- Hausen, H. (1943). *VDI Z. Beiheft Verfahrenstechnik* 4, 91–98
- Dittus, F.W. & Boelter, L.M.K. (1930). *Univ. Calif. Publ. Eng.* 2, 443–461
- Incropera *et al.* (2007). [*Fundamentals of Heat and Mass Transfer*](https://openlibrary.org/isbn/0471457280), Ch. 8
- Perry & Green (2019). [*Perry's Chemical Engineers' Handbook*](https://openlibrary.org/isbn/0071834087), Sec. 11

## Wall and lining conductivity
Used in: Vessel Assessment, Vessel Comparison, Heat Transfer Tool

| Wall | $k_w$ (W/(m·K)) | | Lining | $k_l$ (W/(m·K)) | Default thickness |
|---|---|---|---|---|---|
| Stainless steel (generic) | 15 | | Glass enamel | 1.2 | 1.5 mm |
| 304 / 316L | 14.4 / 13.4 | | PTFE / PFA | 0.25 | 2 mm |
| Carbon steel | 50 | | PVDF | 0.19 | 3 mm |
| Hastelloy C-276 | 12 | | Rubber | 0.16 | 6 mm |
| Inconel 600 | 15 | | Epoxy | 0.20 | 3 mm |
| Titanium | 22 | | Ti / Hastelloy / Ta clad | 22 / 12 / 57 | 2 / 2 / 1 mm |
| Nickel / Monel | 61 / 26 | | | | |
| Zirconium / Tantalum / Copper | 23 / 57 / 390 | | | | |

Values are at about 20–25 °C. Alloy conductivity varies with grade and temperature, so confirm against a mill certificate for critical duty. For a glass-lined vessel, the wall resistance is $x_{glass}/k_{glass} + x_{steel}/k_{steel}$.

Sources:
- ASM International. *ASM Handbook*, Vol. 1
- Engineering ToolBox, thermal conductivity of metals and plastics
- De Dietrich / Pfaudler glass-lining technical data

## Heat-transfer media (coolants)
Used in: Vessel Assessment, Heat Transfer Tool

| Medium | Range (°C) | $\rho$ (kg/m³) | $C_p$ (J/(kg·K)) | $\mu$ (mPa·s) | $k$ (W/(m·K)) | Source |
|---|---|---|---|---|---|---|
| Water | 5–95 | 997 | 4182 | 0.89 | 0.607 | IAPWS-IF97 / CRC |
| Water–glycol 50/50 | −30–105 | 1075 | 3350 | 3.5 | 0.400 | ASHRAE Fundamentals |
| Brine (CaCl₂ 25 %) | −40–60 | 1230 | 2810 | 4.5 | 0.540 | ASHRAE Fundamentals |
| Syltherm 800 | −40–400 | 936 | 1617 | 9.1 | 0.134 | Dow TDS |
| Syltherm HF | −73–260 | 864 | 1695 | 1.70 | 0.106 | Dow TDS |
| Syltherm XLT | −100–260 | 852 | 1784 | 1.4 | 0.109 | Dow TDS |
| Huber DW-Therm M90.200.02 | −90–200 | 875 | 1800 | 1.75 | 0.116 | Huber brochure / SDS |
| Dowtherm A | 15–400 | 1056 | 1587 | 3.8 | 0.138 | Dow TDS 176-01472 |
| Dowtherm Q | −35–330 | 962 | 1668 | 3.5 | 0.121 | Dow TDS 176-01467 |
| Therminol 66 | −3–345 | 1005 | 1580 | 82 | 0.117 | Eastman bulletin TF-8695 |
| Marlotherm SH (dibenzyltoluene) | −15–325 | 1039 | 1580 | 36 | 0.130 | Eastman guide MT-10741 |
| Steam (condensing) | 100–250 | — | — | — | — | Fixed $h_o$ = 8000 W/(m²·K) |

Values are single-point at 25 °C, interpolated from the vendor tables held in `data/HTM_datasheets`. Viscosity is interpolated as $\ln\mu$ vs $1/T$. Synthetic oils change viscosity by orders of magnitude across their range, so for duty far from 25 °C, re-enter $\mu$ at the operating temperature. The DW-Therm $C_p$ is read from a chart and is approximate.

Sources:
- Vendor technical data sheets (Dow, Eastman, Huber), held in `data/HTM_datasheets`
- ASHRAE (2021). *ASHRAE Handbook — Fundamentals*, Ch. 31

# Transient heating & cooling

## Batch heating or cooling time
Used in: Heat Transfer Tool

$$
t = \frac{\rho V C_p}{U A}\,\ln\frac{T_{start} - T_{jacket}}{T_{end} - T_{jacket}}
$$

This is the analytical solution for a well-mixed batch with constant $U$, $A$ and jacket temperature, with no agitator or reaction heat.

Sources:
- Incropera *et al.* (2007). [*Fundamentals of Heat and Mass Transfer*](https://openlibrary.org/isbn/0471457280), Ch. 5

## Batch energy balance (constant jacket temperature)
Used in: Heat Transfer Tool

$$
\rho V C_p\,\frac{dT}{dt} = U A\,(T_{jacket} - T) + P_{agitator} + Q_{rxn}
$$

The balance is integrated with forward Euler, $T_{n+1} = T_n + \Delta t\cdot dT/dt$. The integration stops at $T_{target}$ or $t_{max}$.
- The jacket term is positive when the jacket heats the batch.
- $P_{agitator}$ (impeller power) always adds heat.
- $Q_{rxn}$ is positive when the reaction is exothermic.

The *Initial dT/dt* indicator is $\lvert UA(T_{jacket} - T_{start}) + P_{agitator}\rvert/(\rho VC_p)$ in K/min, so agitator heat slows cooling and speeds heating. In the reaction profile, $Q_{rxn} = -\Delta H\cdot 1000\cdot r V$, and the adiabatic rise is $-\Delta H\,n_0/(mC_p)$.

Sources:
- Incropera *et al.* (2007). [*Fundamentals of Heat and Mass Transfer*](https://openlibrary.org/isbn/0471457280), Ch. 5

## Variable jacket temperature (NTU–effectiveness)
Used in: Heat Transfer Tool

$$
NTU = \frac{UA}{\dot m_j C_{p,j}}, \qquad \varepsilon_{HX} = 1 - e^{-NTU}, \qquad Q_{jacket} = \varepsilon_{HX}\,\dot m_j C_{p,j}\,(T_{j,in} - T)
$$

The jacket outlet temperature is $T_{j,out} = T_{j,in} - Q_{jacket}/(\dot m_j C_{p,j})$. A lower coolant flow gives a higher effectiveness but a warmer outlet, which reduces the mean driving force. The batch temperature is then advanced as in the constant-jacket model.

Sources:
- Incropera *et al.* (2007). [*Fundamentals of Heat and Mass Transfer*](https://openlibrary.org/isbn/0471457280), Ch. 11

# Fluid properties

## Temperature-dependent solvent properties
Used in: Fluid Database, all calculation pages

$$
\mu(T) = \mu_{25}\exp\!\left[\frac{E_a}{R}\left(\frac{1}{T_K} - \frac{1}{298.15}\right)\right], \qquad D(T) = D_{25}\,\frac{T_K}{298.15}\,\frac{\mu_{25}}{\mu(T)}
$$

Density, surface tension, heat capacity and thermal conductivity are linear in temperature and anchored at 25 °C: $X(T) = X_{25} + (dX/dT)(T - 25)$, with $T$ in °C. Surface tension is clamped at $\sigma \ge 0$. Viscosity follows Arrhenius with $R$ = 8.314 J/(mol·K). Diffusivity uses Stokes–Einstein scaling, $D \propto T/\mu$.

Sources:
- Perry & Green (2019). [*Perry's Chemical Engineers' Handbook*](https://openlibrary.org/isbn/0071834087), Sec. 2
- CRC Handbook of Chemistry and Physics; Yaws' Handbook; DIPPR

## Vapour pressure and boiling point (Antoine)
Used in: Fluid Database

$$
\log_{10} P_{mmHg} = A - \frac{B}{C + T}, \qquad T_{bp} = \frac{B}{A - \log_{10} P_{mmHg}} - C
$$

$T$ is in °C. At $P$ = 760 mmHg (1 atm = 101.325 kPa), $T_{bp}$ recovers the normal boiling point.

Sources:
- [NIST Chemistry WebBook](https://webbook.nist.gov/chemistry/)
- Yaws' Handbook of Vapor Pressure

## Liquid blend mixing rules
Used in: Fluid Database (blends)

$$
\frac{1}{\rho_m} = \sum_i \frac{w_i}{\rho_i}, \qquad \ln\mu_m = \sum_i w_i\ln\mu_i, \qquad C_{p,m} = \sum_i w_i C_{p,i}
$$

$$
\ln D_m = \sum_i w_i\ln D_i, \qquad \sigma_m = \sum_i \varphi_i\sigma_i, \qquad k_m = \sum_i \varphi_i k_i
$$

$w_i$ is the mass fraction and $\varphi_i$ the volume fraction; mixing is assumed ideal. The density and $C_p$ rules are standard ideal-mixture estimates.

The viscosity rule is the Arrhenius / Grunberg–Nissan form without an interaction term, applied with mass fractions. It can be off by a factor of 2 or more for strongly non-ideal blends such as water/alcohol. Surface tension of real mixtures is usually below the linear value.

Sources:
- Poling, B.E., Prausnitz, J.M. & O'Connell, J.P. (2001). *The Properties of Gases and Liquids*, 5th ed., McGraw-Hill, Ch. 9–10

## Miscibility screening (Hansen)
Used in: Fluid Database

$$
R_a = \sqrt{4(\delta_{d1} - \delta_{d2})^2 + (\delta_{p1} - \delta_{p2})^2 + (\delta_{h1} - \delta_{h2})^2}
$$

Known-pair data from Perry's, the CRC Handbook and the Merck Index are used first. Otherwise: $R_a$ < 15 MPa$^{1/2}$ likely miscible, 15–25 borderline, > 25 likely immiscible. The cut-offs are screening heuristics.

Sources:
- Hansen, C.M. (2007). [*Hansen Solubility Parameters: A User's Handbook*](https://doi.org/10.1201/9781420006834), 2nd ed., CRC Press

# Scale-up & Bourne Protocol

## Scale-up matching
Used in: Vessel Comparison

$$
N_2 = N_1\left(\frac{N_{p,1}}{N_{p,2}}\,\frac{{D_1}^5\,V_2}{{D_2}^5\,V_1}\right)^{1/3}\ \text{(equal } P/V\text{)}, \qquad N_2 = N_1\frac{D_1}{D_2}\ \text{(equal tip speed)}
$$

The selected parameter (P/V, tip speed, $t_E$, blend time, …) is evaluated in the basis vessel. For each target vessel, the RPM (at fixed volume) or the volume (at fixed RPM) is then solved numerically with the full hydrodynamic model. The two expressions above are the closed forms for the simplest cases. A target outside the vessel's RPM / volume window is flagged *Not achievable*.

Sources:
- Paul *et al.* (2004). [*Handbook of Industrial Mixing*](https://doi.org/10.1002/0471451452), Ch. 6 and 9

## Bourne Protocol set-points
Used in: Bourne Protocol, Reaction Sensitivity

$$
N = \left(\frac{(P/m)\,V}{N_p D^5}\right)^{1/3}
$$

- **Test 1** runs at 0.1×, 1× and 10× the centre $P/m$ (W/kg), a 100-fold span (≈ 4.6× in $N$). Set-points outside the RPM range are clamped, and the achieved span is reported.
- **Test 3** uses $\varepsilon_{loc} = r\,\bar\varepsilon$ for each feed location, with $t_E$ from the engulfment model.

A KPI is flagged sensitive when its largest change from the centre value exceeds the threshold (default 5 %).

Sources:
- Bourne, J.R. (2003). Mixing and the selectivity of chemical reactions. [*Org. Process Res. Dev.*](https://doi.org/10.1021/op020074q) 7(4), 471–508

# Reactor-specific correlations

Vessel-specific correlations (ROM fits from CFD, or fits to measured data) can replace a literature correlation for one parameter: blend time, $t_E$, sparged or surface $k_La$, $N_p$ or $\varepsilon_{max}$. They are selectable on the Vessel Assessment and Vessel Comparison pages when the selected vessel has a registered fit.

## Registering a correlation
Used in: Vessel Assessment, Vessel Comparison

Correlations are registered in `utils/rom_registry.py` (`register()`) or loaded from `data/fitted_correlations.json`. The illustrative demo correlations were removed in the 2026 review, because they cited untraceable studies and were registered to a vessel that is not in the database. Every correlation should carry a traceable source: report ID, data set, fit statistics and validity range.
