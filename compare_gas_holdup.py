"""Compare gas-holdup correlations:

1. Eq. 17 (CEJ 2005 paper, vessel-averaged gas holdup, implicit form):
       eps = (U_s * eps / U_t)^0.5
             + 0.000216 * [(P_g/V)^0.4 * rho_c^0.2 / sigma^0.6] * (U_s/U_t)^0.5

   Implicit in eps, but closed-form solvable. Let a = sqrt(U_s/U_t),
   K = 0.000216 * (P_g/V)^0.4 * rho_c^0.2 / sigma^0.6, s = sqrt(eps):
       s^2 - a*s - K*a = 0   ->   s = [a + sqrt(a^2 + 4*K*a)] / 2,  eps = s^2

2. Old code/Excel "Hughmark" re-fit (row 34, since removed from codebase):
       eps_G = 0.505 * v_s^0.47 * (P/V)^0.4 * (mu/sigma)^0.08

All inputs SI: P/V in W/m^3, rho in kg/m^3, sigma in N/m, velocities in m/s.
U_t = terminal bubble rise velocity, ~0.2 m/s for 2-5 mm air bubbles in water.

Usage:  python compare_gas_holdup.py
"""

import numpy as np
import matplotlib.pyplot as plt


def holdup_eq17(v_s, P_V, rho_c=1000.0, sigma=0.072, U_t=0.2):
    """Vessel-averaged gas holdup, CEJ 2005 eq. 17 (closed-form solution)."""
    v_s = np.asarray(v_s, dtype=float)
    K = 0.000216 * P_V**0.4 * rho_c**0.2 / sigma**0.6
    a = np.sqrt(v_s / U_t)
    s = (a + np.sqrt(a**2 + 4.0 * K * a)) / 2.0
    return s**2


def holdup_old_hughmark_refit(v_s, P_V, mu=0.001, sigma=0.072):
    """Old codebase re-fit (nominally 'Hughmark', not the published form)."""
    v_s = np.asarray(v_s, dtype=float)
    return 0.505 * v_s**0.47 * P_V**0.4 * (mu / sigma) ** 0.08


def main():
    # Water-like liquid
    rho_c = 1000.0   # kg/m^3
    mu = 0.001       # Pa.s
    sigma = 0.072    # N/m
    U_t = 0.2        # m/s bubble terminal rise velocity

    v_s = np.linspace(0.001, 0.05, 300)          # superficial gas velocity, m/s
    P_V_levels = [500.0, 1000.0, 2000.0, 4000.0]  # W/m^3

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5), sharex=True)

    colors = plt.cm.viridis(np.linspace(0.0, 0.85, len(P_V_levels)))
    for P_V, c in zip(P_V_levels, colors):
        eps17 = holdup_eq17(v_s, P_V, rho_c, sigma, U_t)
        eps_old = holdup_old_hughmark_refit(v_s, P_V, mu, sigma)
        ax1.plot(v_s * 1000, eps17 * 100, color=c, label=f"P/V = {P_V:.0f} W/m³")
        ax1.plot(v_s * 1000, eps_old * 100, color=c, ls="--")
        ratio = np.where(eps17 > 0, eps_old / eps17, np.nan)
        ax2.plot(v_s * 1000, ratio, color=c, label=f"P/V = {P_V:.0f} W/m³")

    ax1.plot([], [], "k-", label="Eq. 17 (CEJ 2005, implicit)")
    ax1.plot([], [], "k--", label="Old Excel/code re-fit")
    ax1.set_xlabel("Superficial gas velocity $v_s$ (mm/s)")
    ax1.set_ylabel("Gas holdup $\\varepsilon_G$ (%)")
    ax1.set_title("Gas holdup vs superficial velocity (water, $U_t$ = 0.2 m/s)")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)

    ax2.axhline(1.0, color="k", lw=0.8)
    ax2.set_xlabel("Superficial gas velocity $v_s$ (mm/s)")
    ax2.set_ylabel("Old re-fit / Eq. 17 (–)")
    ax2.set_title("Ratio: old re-fit over Eq. 17")
    ax2.set_yscale("log")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3, which="both")

    fig.tight_layout()
    fig.savefig("gas_holdup_comparison.png", dpi=150)
    print("Saved gas_holdup_comparison.png")

    # Spot table at v_s = 10 mm/s
    print(f"\n{'P/V (W/m³)':>12} {'Eq.17 (%)':>10} {'Old re-fit (%)':>15}")
    for P_V in P_V_levels:
        e17 = holdup_eq17(0.01, P_V, rho_c, sigma, U_t) * 100
        eo = holdup_old_hughmark_refit(0.01, P_V, mu, sigma) * 100
        print(f"{P_V:>12.0f} {e17:>10.2f} {eo:>15.2f}")

    plt.show()


if __name__ == "__main__":
    main()
