"""Batch temperature against time from a jacketed energy balance (Vessel Assessment).

Same balance as the Heat Transfer reaction profile (``core.heat_transfer.
compute_reaction_profile``: fixed rate constant, constant-temperature jacket), extended
to a semi-batch feed:

    C(t)·dT/dt = Q_rxn + ṁ_f·cp_f·(T_f − T) + UA(t)·(T_cool − T)

with C(t) = m0·cp0 + m_f(t)·cp_f (J/K). Two scenarios:

* **batch** - both reagents charged at C0 (equimolar for 2nd order); runs to 99 %
  conversion (24 h cap).
* **dosed** - reagent A charged at C0 in V0; the stoichiometric co-reagent B
  (n = C0·V0) is dosed at a constant rate with the feed, so the heat release follows
  the dosing and unreacted B accumulates when the reaction is slower than the feed.
  Runs over the dosing time.

The linear jacket / feed terms and the consumption are integrated semi-implicitly, so the
step size is not limited by small vessels with a large UA/C or by fast reactions.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

MAX_BATCH_S = 86400.0
N_STEPS = 4000
N_OUT = 201


@dataclass(frozen=True)
class Kinetics:
    order: str
    k: float
    C0: float      # mol/L
    dH: float      # kJ/mol, negative = exothermic

    @property
    def active(self) -> bool:
        return self.k > 0 and self.C0 > 0


@dataclass(frozen=True)
class Dosing:
    time_s: float
    volume_L: float
    rho: float     # kg/m³
    cp: float      # J/(kg·K)
    T_C: float


def batch_duration(kin: Kinetics) -> float:
    """Time (s) to ~99.5 % conversion, as on the Heat Transfer page (60 s .. 24 h)."""
    o = kin.order.strip()
    if o in ("1", "pseudo-1"):
        t = -np.log(0.005) / kin.k
    elif o in ("2", "pseudo-2"):
        t = 0.995 / (0.005 * kin.k * kin.C0)
    else:  # zero order
        t = kin.C0 / kin.k
    return float(min(max(t, 60.0), MAX_BATCH_S))


def _react(order: str, k: float, n_a: float, n_b: float, v_l: float, dt: float) -> float:
    """Moles reacted in ``dt`` (A + B -> P), implicit in the limiting co-reagent B."""
    if n_b <= 0 or n_a <= 0:
        return 0.0
    if order in ("1", "pseudo-1"):
        return n_b - n_b / (1.0 + k * dt)
    if order in ("2", "pseudo-2"):
        return n_b - n_b / (1.0 + k * n_a / v_l * dt)
    return min(k * v_l * dt, n_b, n_a)


def profile(*, T0: float, T_cool: float, V0_L: float, rho0: float, cp0: float, kin: Kinetics,
            ua: Callable[[float], float], dosing: Dosing | None = None) -> dict:
    """Temperature, conversion and heat flows against time (see module docstring)."""
    t_end = dosing.time_s if dosing else (batch_duration(kin) if kin.active else 0.0)
    n0 = kin.C0 * V0_L if kin.active else 0.0
    c0 = rho0 * V0_L / 1000.0 * cp0
    if t_end <= 0 or c0 <= 0:
        return {}
    dt = t_end / N_STEPS
    qv = dosing.volume_L / dosing.time_s if dosing else 0.0          # L/s
    m_dot = qv / 1000.0 * dosing.rho if dosing else 0.0              # kg/s
    w_f = m_dot * dosing.cp if dosing else 0.0                       # W/K
    T_f = dosing.T_C if dosing else T0
    feed_mol = n0 / t_end if dosing else 0.0                         # mol/s of B
    q_per_mol = -kin.dH * 1000.0 + 0.0                               # J/mol (+ exothermic)

    n_a, n_b = n0, (0.0 if dosing else n0)
    T, reacted = T0, 0.0
    t_arr = np.linspace(0.0, t_end, N_STEPS + 1)
    out = {k: np.zeros(N_STEPS + 1) for k in
           ("T_C", "conversion", "Q_rxn_W", "Q_feed_W", "Q_jacket_W", "UA_W_K", "V_L")}
    ua0 = ua(0.0)
    out["T_C"][0], out["UA_W_K"][0], out["V_L"][0] = T0, ua0, V0_L
    out["Q_feed_W"][0] = w_f * (T_f - T0)
    out["Q_jacket_W"][0] = ua0 * (T_cool - T0)
    o = kin.order.strip()
    end = N_STEPS
    for i in range(1, N_STEPS + 1):
        t = t_arr[i]
        v = V0_L + qv * t
        n_b += feed_mol * dt
        dx = _react(o, kin.k, n_a, n_b, v, dt) if kin.active else 0.0
        n_a, n_b, reacted = n_a - dx, n_b - dx, reacted + dx
        q_rxn = q_per_mol * dx / dt
        heat_cap = c0 + w_f * t
        ua_t = ua(t)
        T = (T + dt * (q_rxn + w_f * T_f + ua_t * T_cool) / heat_cap) / \
            (1.0 + dt * (w_f + ua_t) / heat_cap)
        out["T_C"][i], out["V_L"][i], out["UA_W_K"][i] = T, v, ua_t
        out["conversion"][i] = reacted / n0 if n0 > 0 else 0.0
        out["Q_rxn_W"][i] = q_rxn
        out["Q_feed_W"][i] = w_f * (T_f - T)
        out["Q_jacket_W"][i] = ua_t * (T_cool - T)
        if not dosing and out["conversion"][i] >= 0.99:
            end = i
            break
    out["Q_rxn_W"][0] = out["Q_rxn_W"][1] if end >= 1 else 0.0
    out = {k: a[: end + 1] for k, a in out.items()}
    t_arr = t_arr[: end + 1]

    # Heat balance over the whole process with no jacket (all reagent consumed).
    c_end = c0 + w_f * t_end
    T_ad = (c0 * T0 + w_f * t_end * T_f + q_per_mol * n0) / c_end
    i_max, i_min = int(np.argmax(out["T_C"])), int(np.argmin(out["T_C"]))
    x_end = float(out["conversion"][-1])
    keep = np.unique(np.linspace(0, end, min(N_OUT, end + 1)).round().astype(int))
    return {
        "scenario": "dosed" if dosing else "batch",
        "time_min": t_arr[keep] / 60.0,
        **{k: a[keep] for k, a in out.items()},
        "T_start_C": T0, "T_end_C": float(out["T_C"][-1]),
        "T_max_C": float(out["T_C"][i_max]), "t_T_max_min": float(t_arr[i_max] / 60.0),
        "T_min_C": float(out["T_C"][i_min]), "t_T_min_min": float(t_arr[i_min] / 60.0),
        "T_ad_C": float(T_ad), "dT_ad_K": float(T_ad - T0),
        "final_conversion": x_end,
        "t_99_min": float(t_arr[-1] / 60.0) if not dosing and x_end >= 0.99 else None,
        "Q_rxn_total_kJ": q_per_mol * n0 / 1000.0,
    }
