"""Plot gas-flow limits for complete dispersion and flooding.

Uses the stirred-tank gas-handling relations:

    Flooding:
        Fl_G = 30 Fr (D/T)^3.5

    Complete dispersion:
        (Fl_G)_CD = 0.2 (D/T)^0.5 Fr_CD^0.5

with:
    Fl_G = Q_G / (N D^3)
    Fr = N^2 D / g

This script plots the corresponding Q_G vs N curves for a chosen impeller
diameter D and tank diameter T.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.calculations.gas_liquid import (  # noqa: E402
    complete_dispersion_flow_rate,
    complete_dispersion_speed,
    gas_flooding_flow_rate,
    gas_flooding_speed,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot flooding and complete-dispersion gas-flow limits."
    )
    parser.add_argument("--D", type=float, required=True, help="Impeller diameter, m")
    parser.add_argument("--T", type=float, required=True, help="Tank diameter, m")
    parser.add_argument(
        "--n-min", type=float, default=0.25, help="Minimum impeller speed, rev/s"
    )
    parser.add_argument(
        "--n-max", type=float, default=8.0, help="Maximum impeller speed, rev/s"
    )
    parser.add_argument(
        "--points", type=int, default=300, help="Number of speed points"
    )
    parser.add_argument(
        "--flow-units",
        choices=("m3/s", "m3/h", "L/min"),
        default="m3/h",
        help="Units for plotted gas flow rate",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output image path (e.g. gas_limits.png)",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open an interactive plot window",
    )
    return parser


def _flow_scale(units: str) -> tuple[float, str]:
    if units == "m3/s":
        return 1.0, "Gas flow rate, Q_G (m^3/s)"
    if units == "L/min":
        return 60_000.0, "Gas flow rate, Q_G (L/min)"
    return 3600.0, "Gas flow rate, Q_G (m^3/h)"


def main() -> int:
    args = _build_parser().parse_args()
    if args.D <= 0 or args.T <= 0:
        raise SystemExit("D and T must be positive.")
    if args.n_min <= 0 or args.n_max <= args.n_min:
        raise SystemExit("Use positive speed bounds with n-max > n-min.")
    if args.points < 2:
        raise SystemExit("points must be at least 2.")

    n_vals = np.linspace(args.n_min, args.n_max, args.points)
    q_flood = gas_flooding_flow_rate(n_vals, args.D, args.T)
    q_cd = complete_dispersion_flow_rate(n_vals, args.D, args.T)

    flow_scale, y_label = _flow_scale(args.flow_units)
    q_flood_plot = q_flood * flow_scale
    q_cd_plot = q_cd * flow_scale

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.plot(n_vals, q_cd_plot, label="Complete dispersion limit", linewidth=2.2)
    ax.plot(n_vals, q_flood_plot, label="Flooding limit", linewidth=2.2)

    valid_band = q_cd_plot <= q_flood_plot
    if np.any(valid_band):
        ax.fill_between(
            n_vals, 0.0, q_cd_plot, where=valid_band, alpha=0.15,
            label="Complete dispersion region"
        )
        ax.fill_between(
            n_vals, q_cd_plot, q_flood_plot, where=valid_band, alpha=0.08,
            label="Loaded / incomplete dispersion"
        )

    ax.set_title(
        f"Gas dispersion limits for D={args.D:.3g} m, T={args.T:.3g} m (D/T={args.D/args.T:.3f})"
    )
    ax.set_xlabel("Impeller speed, N (rev/s)")
    ax.set_ylabel(y_label)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.output, dpi=180, bbox_inches="tight")
        print(f"Saved plot to: {args.output}")

    sample_q = np.array([q_cd[0], q_cd[len(q_cd) // 2], q_cd[-1]])
    print("Sample complete-dispersion points:")
    for q in sample_q:
        print(f"  Q_G={q:.6g} m^3/s -> N_CD={complete_dispersion_speed(q, args.D, args.T):.4g} rev/s")

    sample_q = np.array([q_flood[0], q_flood[len(q_flood) // 2], q_flood[-1]])
    print("Sample flooding points:")
    for q in sample_q:
        print(f"  Q_G={q:.6g} m^3/s -> N_flood={gas_flooding_speed(q, args.D, args.T):.4g} rev/s")

    if not args.no_show:
        plt.show()
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
