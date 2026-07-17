"""Scale-up helpers for stirred-tank reactors.

UNIT CONVENTION
---------------
N in rev/s, D in m (consistent units; only ratios matter).  Returned N_large
is in the same speed units as N_small.

REFERENCES (per function)
-------------------------
The classic single-criterion scale-up rules (constant tip speed, constant P/V,
constant Re) and the impossibility of simultaneous Re/Fr/We similarity are
discussed in the context source:
    Myerson (ed.), *Handbook of Industrial Crystallization*, 3rd ed. (2019),
    Ch. 10 (Scale-Up) and Sec. 12.6 (Scale-Up of Batch Crystallization).
    [in context/]
Primary reference: Paul, Atiemo-Obeng & Kresta (eds.), *Handbook of Industrial
Mixing*, Wiley (2004), Ch. 2 & 6.  [NOT in context/ - verify]

    scale_up_constant_tip_speed (N2 = N1 D1/D2)
    scale_up_constant_P_V       (N2 = N1 [(Np1/Np2)(D1/D2)^2]^(1/3))
    scale_up_constant_Re        (N2 = N1 (D1/D2)^2)
"""


def scale_up_constant_tip_speed(N_small, D_small, D_large):
    """N_large such that tip speed is preserved."""
    return N_small * D_small / D_large


def scale_up_constant_P_V(N_small, D_small, D_large, Np_small=5.0, Np_large=5.0):
    """N_large such that P/V is preserved (geometric similarity assumed)."""
    ratio = (Np_small / Np_large) * (D_small / D_large)**2
    return N_small * ratio**(1.0/3.0)


def scale_up_constant_Re(N_small, D_small, D_large):
    """N_large for constant Re (same fluid)."""
    return N_small * (D_small / D_large)**2
