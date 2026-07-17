"""
Temperature-dependent physical properties for common pharmaceutical solvents.
=============================================================================

Provides density (ρ), dynamic viscosity (μ), surface tension (σ),
molecular diffusivity (D_mol), specific heat capacity (Cp), and thermal
conductivity (k) as functions of temperature for solvents routinely used
in small-molecule organic synthesis and pharmaceutical development.

Correlations
------------
* **Density** – linear:  ρ(T) = ρ₂₅ + dρ/dT · (T − 25)  [kg/m³]
* **Viscosity** – Arrhenius:  μ(T) = μ₂₅ · exp[B·(1/T_K − 1/298.15)]
  where B = E_a/R  [K] is the activation-energy parameter.
* **Surface tension** – linear:  σ(T) = σ₂₅ + dσ/dT · (T − 25)  [N/m]
* **Diffusivity** – Stokes-Einstein scaling:
       D(T) = D₂₅ · (T_K / 298.15) · (μ₂₅ / μ(T))
* **Specific heat capacity** – linear:  Cp(T) = Cp₂₅ + dCp/dT · (T − 25)  [J/(kg·K)]
* **Thermal conductivity** – linear:  k(T) = k₂₅ + dk/dT · (T − 25)  [W/(m·K)]

All correlations are anchored at 25 °C so that the known reference values
are recovered exactly at that temperature.

Data sources: Perry's Chemical Engineers' Handbook 9th ed., CRC Handbook
of Chemistry and Physics, Yaws' Handbook, DIPPR, and primary literature.

Usage
-----
>>> from utils.solvent_properties import get_properties, list_solvents
>>> props = get_properties("Water", 37.0)
>>> props["rho_kg_m3"], props["mu_Pa_s"]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict

R_GAS = 8.314  # J/(mol·K)

# ---------------------------------------------------------------------------
# Data class for a single solvent
# ---------------------------------------------------------------------------

@dataclass
class SolventData:
    """Container for temperature-dependent correlation parameters."""
    name: str                          # Display name
    cas: str                           # CAS number
    mw: float                          # Molecular weight (g/mol)

    # Phase boundaries
    mp_C: float                        # Melting point (°C)
    bp_C: float                        # Normal boiling point (°C)

    # Density at 25 °C and linear slope
    rho_25: float                      # kg/m³ at 25 °C
    drho_dT: float                     # kg/m³/°C  (negative = typical)

    # Viscosity at 25 °C and Arrhenius activation energy
    mu_25: float                       # Pa·s at 25 °C
    Ea_mu: float                       # Activation energy for viscous flow (J/mol)

    # Surface tension at 25 °C and linear slope
    sig_25: float                      # N/m at 25 °C
    dsig_dT: float                     # N/m/°C  (negative = typical)

    # Reference diffusivity at 25 °C [m²/s]
    D_ref_25: float

    # Specific heat capacity at 25 °C and linear slope
    Cp_25: float                       # J/(kg·K) at 25 °C
    dCp_dT: float                      # J/(kg·K)/°C

    # Thermal conductivity at 25 °C and linear slope
    k_25: float                        # W/(m·K) at 25 °C
    dk_dT: float                       # W/(m·K)/°C

    # Antoine equation: log10(P_mmHg) = A - B / (C + T_°C)
    antoine_A: float = 0.0
    antoine_B: float = 0.0
    antoine_C: float = 0.0

    # Hansen Solubility Parameters (MPa^0.5) at 25 °C
    # Sources: Hansen (2007) Handbook, Barton (1991), HSPiP database
    hsp_d: float = 0.0                 # Dispersion component δ_d
    hsp_p: float = 0.0                 # Polar component δ_p
    hsp_h: float = 0.0                 # Hydrogen-bonding component δ_h

    # Optional
    aliases: tuple[str, ...] = ()      # Common synonyms / abbreviations
    notes: str = ""


# ---------------------------------------------------------------------------
# Solvent database
# ---------------------------------------------------------------------------

SOLVENT_DB: Dict[str, SolventData] = {}

def _add(s: SolventData):
    SOLVENT_DB[s.name] = s

# ─── Water ────────────────────────────────────────────────────────────────
_add(SolventData(
    name="Water", cas="7732-18-5", mw=18.015,
    mp_C=0.0, bp_C=100.0,
    rho_25=997.0, drho_dT=-0.26,
    mu_25=8.90e-4, Ea_mu=15500.0,
    sig_25=0.0720, dsig_dT=-1.50e-4,
    D_ref_25=2.3e-9,
    Cp_25=4182.0, dCp_dT=0.4,
    k_25=0.607, dk_dT=0.0013,
    antoine_A=8.07131, antoine_B=1730.63, antoine_C=233.426,
    hsp_d=15.5, hsp_p=16.0, hsp_h=42.3,
    aliases=("H2O", "DI Water", "Deionized Water", "Purified Water"),
))

# ─── Methanol ────────────────────────────────────────────────────────────
_add(SolventData(
    name="Methanol", cas="67-56-1", mw=32.04,
    mp_C=-97.6, bp_C=64.7,
    rho_25=787.0, drho_dT=-0.94,
    mu_25=5.44e-4, Ea_mu=10800.0,
    sig_25=0.0223, dsig_dT=-7.7e-5,
    D_ref_25=1.6e-9,
    Cp_25=2531.0, dCp_dT=3.5,
    k_25=0.200, dk_dT=-0.00020,
    antoine_A=8.08097, antoine_B=1582.27, antoine_C=239.726,
    hsp_d=15.1, hsp_p=12.3, hsp_h=22.3,
    aliases=("MeOH", "Methyl Alcohol", "CH3OH"),
))

# ─── Ethanol ─────────────────────────────────────────────────────────────
_add(SolventData(
    name="Ethanol", cas="64-17-5", mw=46.07,
    mp_C=-114.1, bp_C=78.4,
    rho_25=789.0, drho_dT=-0.85,
    mu_25=1.09e-3, Ea_mu=14000.0,
    sig_25=0.0220, dsig_dT=-8.3e-5,
    D_ref_25=1.2e-9,
    Cp_25=2440.0, dCp_dT=4.5,
    k_25=0.167, dk_dT=-0.00020,
    antoine_A=8.20417, antoine_B=1642.89, antoine_C=230.300,
    hsp_d=15.8, hsp_p=8.8, hsp_h=19.4,
    aliases=("EtOH", "Ethyl Alcohol", "C2H5OH"),
))

# ─── Isopropanol (IPA) ──────────────────────────────────────────────────
_add(SolventData(
    name="Isopropanol (IPA)", cas="67-63-0", mw=60.10,
    mp_C=-89.5, bp_C=82.6,
    rho_25=786.0, drho_dT=-0.87,
    mu_25=2.04e-3, Ea_mu=18000.0,
    sig_25=0.0210, dsig_dT=-8.0e-5,
    D_ref_25=1.0e-9,
    Cp_25=2604.0, dCp_dT=5.0,
    k_25=0.135, dk_dT=-0.00018,
    antoine_A=8.11778, antoine_B=1580.92, antoine_C=219.610,
    hsp_d=15.8, hsp_p=6.1, hsp_h=16.4,
    aliases=("IPA", "iPrOH", "2-Propanol", "Isopropyl Alcohol"),
))

# ─── Acetone ─────────────────────────────────────────────────────────────
_add(SolventData(
    name="Acetone", cas="67-64-1", mw=58.08,
    mp_C=-94.7, bp_C=56.1,
    rho_25=784.0, drho_dT=-1.19,
    mu_25=3.06e-4, Ea_mu=7100.0,
    sig_25=0.0234, dsig_dT=-1.12e-4,
    D_ref_25=2.4e-9,
    Cp_25=2163.0, dCp_dT=4.0,
    k_25=0.161, dk_dT=-0.00020,
    antoine_A=7.11714, antoine_B=1210.595, antoine_C=229.664,
    hsp_d=15.5, hsp_p=10.4, hsp_h=7.0,
    aliases=("Me2CO", "Propan-2-one", "Dimethyl Ketone"),
))

# ─── MEK (Methyl Ethyl Ketone / 2-Butanone) ─────────────────────────────
_add(SolventData(
    name="MEK", cas="78-93-3", mw=72.11,
    mp_C=-86.7, bp_C=79.6,
    rho_25=800.0, drho_dT=-1.05,
    mu_25=4.05e-4, Ea_mu=8000.0,
    sig_25=0.0243, dsig_dT=-1.00e-4,
    D_ref_25=1.8e-9,
    Cp_25=2140.0, dCp_dT=4.0,
    k_25=0.145, dk_dT=-0.00018,
    antoine_A=7.06356, antoine_B=1261.339, antoine_C=221.969,
    hsp_d=16.0, hsp_p=9.0, hsp_h=5.1,
    aliases=("MEK", "Methyl Ethyl Ketone", "Butanone"),
))

# ─── Acetonitrile ────────────────────────────────────────────────────────
_add(SolventData(
    name="Acetonitrile", cas="75-05-8", mw=41.05,
    mp_C=-43.8, bp_C=82.0,
    rho_25=786.0, drho_dT=-1.00,
    mu_25=3.69e-4, Ea_mu=7500.0,
    sig_25=0.0290, dsig_dT=-1.04e-4,
    D_ref_25=2.4e-9,
    Cp_25=2229.0, dCp_dT=2.5,
    k_25=0.188, dk_dT=-0.00018,
    antoine_A=7.09363, antoine_B=1314.400, antoine_C=230.000,
    hsp_d=15.3, hsp_p=18.0, hsp_h=6.1,
    aliases=("MeCN", "ACN", "CH3CN"),
))

# ─── DCM (Dichloromethane) ───────────────────────────────────────────────
_add(SolventData(
    name="DCM", cas="75-09-2", mw=84.93,
    mp_C=-96.7, bp_C=39.6,
    rho_25=1326.0, drho_dT=-1.73,
    mu_25=4.13e-4, Ea_mu=6500.0,
    sig_25=0.0280, dsig_dT=-1.18e-4,
    D_ref_25=2.1e-9,
    Cp_25=1190.0, dCp_dT=2.5,
    k_25=0.140, dk_dT=-0.00016,
    antoine_A=7.08030, antoine_B=1138.91, antoine_C=231.450,
    hsp_d=18.2, hsp_p=6.3, hsp_h=6.1,
    aliases=("DCM", "Dichloromethane", "Methylene Chloride", "CH2Cl2"),
))

# ─── Chloroform ──────────────────────────────────────────────────────────
_add(SolventData(
    name="Chloroform", cas="67-66-3", mw=119.38,
    mp_C=-63.5, bp_C=61.2,
    rho_25=1480.0, drho_dT=-1.73,
    mu_25=5.36e-4, Ea_mu=7000.0,
    sig_25=0.0271, dsig_dT=-1.12e-4,
    D_ref_25=2.0e-9,
    Cp_25=960.0, dCp_dT=2.0,
    k_25=0.117, dk_dT=-0.00015,
    antoine_A=6.95465, antoine_B=1170.966, antoine_C=226.232,
    hsp_d=17.8, hsp_p=3.1, hsp_h=5.7,
    aliases=("CHCl3", "Trichloromethane"),
))

# ─── Ethyl Acetate ───────────────────────────────────────────────────────
_add(SolventData(
    name="Ethyl Acetate", cas="141-78-6", mw=88.11,
    mp_C=-83.6, bp_C=77.1,
    rho_25=902.0, drho_dT=-1.17,
    mu_25=4.26e-4, Ea_mu=7500.0,
    sig_25=0.0238, dsig_dT=-1.10e-4,
    D_ref_25=2.2e-9,
    Cp_25=1930.0, dCp_dT=4.0,
    k_25=0.151, dk_dT=-0.00018,
    antoine_A=7.10179, antoine_B=1244.951, antoine_C=217.881,
    hsp_d=15.8, hsp_p=5.3, hsp_h=7.2,
    aliases=("EtOAc", "EA"),
))

# ─── THF (Tetrahydrofuran) ──────────────────────────────────────────────
_add(SolventData(
    name="THF", cas="109-99-9", mw=72.11,
    mp_C=-108.4, bp_C=66.0,
    rho_25=889.0, drho_dT=-1.05,
    mu_25=4.63e-4, Ea_mu=7200.0,
    sig_25=0.0268, dsig_dT=-9.5e-5,
    D_ref_25=2.0e-9,
    Cp_25=1720.0, dCp_dT=3.5,
    k_25=0.120, dk_dT=-0.00015,
    antoine_A=6.99515, antoine_B=1202.290, antoine_C=226.254,
    hsp_d=16.8, hsp_p=5.7, hsp_h=8.0,
    aliases=("Tetrahydrofuran",),
))

# ─── Toluene ─────────────────────────────────────────────────────────────
_add(SolventData(
    name="Toluene", cas="108-88-3", mw=92.14,
    mp_C=-95.0, bp_C=110.6,
    rho_25=867.0, drho_dT=-0.87,
    mu_25=5.54e-4, Ea_mu=8500.0,
    sig_25=0.0280, dsig_dT=-1.04e-4,
    D_ref_25=2.0e-9,
    Cp_25=1690.0, dCp_dT=3.0,
    k_25=0.131, dk_dT=-0.00018,
    antoine_A=6.95334, antoine_B=1343.943, antoine_C=219.377,
    hsp_d=18.0, hsp_p=1.4, hsp_h=2.0,
    aliases=("PhMe", "Tol", "Methylbenzene"),
))

# ─── DMF (Dimethylformamide) ────────────────────────────────────────────
_add(SolventData(
    name="DMF", cas="68-12-2", mw=73.09,
    mp_C=-60.5, bp_C=153.0,
    rho_25=944.0, drho_dT=-0.87,
    mu_25=8.02e-4, Ea_mu=10000.0,
    sig_25=0.0370, dsig_dT=-1.12e-4,
    D_ref_25=1.5e-9,
    Cp_25=2060.0, dCp_dT=2.5,
    k_25=0.184, dk_dT=-0.00015,
    antoine_A=6.97780, antoine_B=1451.380, antoine_C=202.000,
    hsp_d=17.4, hsp_p=13.7, hsp_h=11.3,
    aliases=("Dimethylformamide", "N,N-Dimethylformamide"),
))

# ─── DMSO (Dimethyl sulfoxide) ──────────────────────────────────────────
_add(SolventData(
    name="DMSO", cas="67-68-5", mw=78.13,
    mp_C=18.5, bp_C=189.0,
    rho_25=1100.0, drho_dT=-0.73,
    mu_25=1.99e-3, Ea_mu=14500.0,
    sig_25=0.0436, dsig_dT=-1.10e-4,
    D_ref_25=0.9e-9,
    Cp_25=1960.0, dCp_dT=2.0,
    k_25=0.200, dk_dT=-0.00015,
    antoine_A=7.91178, antoine_B=1956.140, antoine_C=199.820,
    hsp_d=18.4, hsp_p=16.4, hsp_h=10.2,
    aliases=("Dimethyl Sulfoxide", "Dimethylsulfoxide"),
))

# ─── Heptane ─────────────────────────────────────────────────────────────
_add(SolventData(
    name="Heptane", cas="142-82-5", mw=100.20,
    mp_C=-90.6, bp_C=98.4,
    rho_25=684.0, drho_dT=-0.81,
    mu_25=3.87e-4, Ea_mu=7500.0,
    sig_25=0.0200, dsig_dT=-8.8e-5,
    D_ref_25=2.5e-9,
    Cp_25=2240.0, dCp_dT=4.5,
    k_25=0.124, dk_dT=-0.00018,
    antoine_A=6.89385, antoine_B=1264.370, antoine_C=216.640,
    hsp_d=15.3, hsp_p=0.0, hsp_h=0.0,
    aliases=("n-Heptane", "C7H16"),
))

# ─── Hexane ──────────────────────────────────────────────────────────────
_add(SolventData(
    name="Hexane", cas="110-54-3", mw=86.18,
    mp_C=-95.3, bp_C=68.7,
    rho_25=655.0, drho_dT=-0.90,
    mu_25=2.94e-4, Ea_mu=6500.0,
    sig_25=0.0179, dsig_dT=-9.6e-5,
    D_ref_25=2.7e-9,
    Cp_25=2270.0, dCp_dT=5.0,
    k_25=0.120, dk_dT=-0.00020,
    antoine_A=6.87776, antoine_B=1171.530, antoine_C=224.366,
    hsp_d=14.9, hsp_p=0.0, hsp_h=0.0,
    aliases=("n-Hexane", "C6H14"),
))

# ─── MTBE (Methyl tert-butyl ether) ─────────────────────────────────────
_add(SolventData(
    name="MTBE", cas="1634-04-4", mw=88.15,
    mp_C=-108.6, bp_C=55.2,
    rho_25=740.0, drho_dT=-1.09,
    mu_25=3.40e-4, Ea_mu=7000.0,
    sig_25=0.0190, dsig_dT=-9.8e-5,
    D_ref_25=2.3e-9,
    Cp_25=2120.0, dCp_dT=4.0,
    k_25=0.112, dk_dT=-0.00018,
    antoine_A=6.64473, antoine_B=1065.940, antoine_C=228.000,
    hsp_d=15.2, hsp_p=4.3, hsp_h=5.0,
    aliases=("Methyl tert-Butyl Ether", "tert-Butyl Methyl Ether", "TBME"),
))

# ─── Acetic Acid ────────────────────────────────────────────────────────
_add(SolventData(
    name="Acetic Acid", cas="64-19-7", mw=60.05,
    mp_C=16.6, bp_C=117.9,
    rho_25=1049.0, drho_dT=-0.82,
    mu_25=1.13e-3, Ea_mu=10500.0,
    sig_25=0.0271, dsig_dT=-8.4e-5,
    D_ref_25=1.3e-9,
    Cp_25=2050.0, dCp_dT=2.0,
    k_25=0.158, dk_dT=-0.00015,
    antoine_A=7.38782, antoine_B=1533.313, antoine_C=222.309,
    hsp_d=14.5, hsp_p=8.0, hsp_h=13.5,
    aliases=("AcOH", "HOAc", "Glacial Acetic Acid", "CH3COOH"),
))

# ─── NMP (N-Methyl-2-pyrrolidone) ───────────────────────────────────────
_add(SolventData(
    name="NMP", cas="872-50-4", mw=99.13,
    mp_C=-24.4, bp_C=202.0,
    rho_25=1028.0, drho_dT=-0.70,
    mu_25=1.67e-3, Ea_mu=12000.0,
    sig_25=0.0410, dsig_dT=-9.0e-5,
    D_ref_25=1.1e-9,
    Cp_25=1680.0, dCp_dT=2.0,
    k_25=0.175, dk_dT=-0.00012,
    antoine_A=7.41282, antoine_B=1826.400, antoine_C=201.000,
    hsp_d=18.0, hsp_p=12.3, hsp_h=7.2,
    aliases=("N-Methyl-2-pyrrolidone", "N-Methylpyrrolidone"),
))

# ─── 2-MeTHF (2-Methyltetrahydrofuran) ─────────────────────────────────
_add(SolventData(
    name="2-MeTHF", cas="96-47-9", mw=86.13,
    mp_C=-136.0, bp_C=80.3,
    rho_25=855.0, drho_dT=-1.00,
    mu_25=4.60e-4, Ea_mu=7500.0,
    sig_25=0.0245, dsig_dT=-9.5e-5,
    D_ref_25=1.8e-9,
    Cp_25=1810.0, dCp_dT=3.5,
    k_25=0.118, dk_dT=-0.00015,
    antoine_A=6.97080, antoine_B=1228.550, antoine_C=221.380,
    hsp_d=16.9, hsp_p=5.0, hsp_h=4.3,
    aliases=("2-Methyltetrahydrofuran", "MeTHF", "2-MeOTHF"),
))

# ─── 1,4-Dioxane ────────────────────────────────────────────────────────
_add(SolventData(
    name="1,4-Dioxane", cas="123-91-1", mw=88.11,
    mp_C=11.8, bp_C=101.1,
    rho_25=1033.0, drho_dT=-0.88,
    mu_25=1.18e-3, Ea_mu=12000.0,
    sig_25=0.0330, dsig_dT=-1.02e-4,
    D_ref_25=1.7e-9,
    Cp_25=1740.0, dCp_dT=2.0,
    k_25=0.159, dk_dT=-0.00012,
    antoine_A=7.43155, antoine_B=1554.679, antoine_C=240.337,
    hsp_d=19.0, hsp_p=1.8, hsp_h=7.4,
    aliases=("Dioxane", "p-Dioxane"),
))

# ─── Diethyl Ether ──────────────────────────────────────────────────────
_add(SolventData(
    name="Diethyl Ether", cas="60-29-7", mw=74.12,
    mp_C=-116.3, bp_C=34.6,
    rho_25=713.0, drho_dT=-1.25,
    mu_25=2.22e-4, Ea_mu=5500.0,
    sig_25=0.0170, dsig_dT=-1.12e-4,
    D_ref_25=2.6e-9,
    Cp_25=2320.0, dCp_dT=3.5,
    k_25=0.130, dk_dT=-0.00020,
    antoine_A=6.92032, antoine_B=1064.070, antoine_C=228.799,
    hsp_d=14.5, hsp_p=2.9, hsp_h=5.1,
    aliases=("Et2O", "Ether", "DEE", "Ethoxyethane"),
))

# ─── Trifluoroacetic Acid ───────────────────────────────────────────────
# Refs: CRC Handbook 86th Ed (Lide 2005); Merck Index 13th Ed;
#       NIST WebBook (Kreglewski 1962); Hansen Handbook (2007)
_add(SolventData(
    name="Trifluoroacetic Acid", cas="76-05-1", mw=114.02,
    mp_C=-15.4, bp_C=72.4,
    rho_25=1480.0, drho_dT=-1.8,
    mu_25=8.50e-4, Ea_mu=10000.0,
    sig_25=0.0133, dsig_dT=-8.0e-5,
    D_ref_25=1.0e-9,
    Cp_25=1050.0, dCp_dT=1.5,
    k_25=0.105, dk_dT=-0.00012,
    antoine_A=7.4860, antoine_B=1392.0, antoine_C=230.0,
    hsp_d=15.6, hsp_p=9.7, hsp_h=11.4,
    aliases=("TFA", "CF3COOH", "Perfluoroacetic Acid", "Trifluoroethanoic Acid"),
    notes="Strong acid (pKa ~0.0). Miscible with water, ethanol, ether, acetone, benzene, hexane.",
))

# ─── Trifluoroacetic Anhydride ──────────────────────────────────────────
# Refs: Sigma-Aldrich SDS; CRC Handbook; Ullmann's Encyclopedia
_add(SolventData(
    name="Trifluoroacetic Anhydride", cas="407-25-0", mw=210.03,
    mp_C=-65.0, bp_C=40.0,
    rho_25=1501.0, drho_dT=-2.0,
    mu_25=5.50e-4, Ea_mu=7000.0,
    sig_25=0.0145, dsig_dT=-1.0e-4,
    D_ref_25=0.7e-9,
    Cp_25=1000.0, dCp_dT=2.0,
    k_25=0.095, dk_dT=-0.00012,
    antoine_A=6.8510, antoine_B=1072.0, antoine_C=230.0,
    hsp_d=14.0, hsp_p=7.0, hsp_h=5.0,
    aliases=("TFAA", "(CF3CO)2O", "Trifluoroacetic acid anhydride"),
    notes="Reacts violently with water. Soluble in benzene, DCM, ether, DMF, THF, MeCN.",
))

# ─── 6 M NaOH (aq) ──────────────────────────────────────────────────────
# ~19.3 wt% NaOH in water.
# Refs: CRC Handbook 97th Ed; International Critical Tables;
#       Perry's 9th Ed §2 (aqueous-solution properties).
_add(SolventData(
    name="6 M NaOH (aq)", cas="1310-73-2", mw=40.00,
    mp_C=-10.0, bp_C=106.0,
    rho_25=1219.0, drho_dT=-0.44,
    mu_25=2.50e-3, Ea_mu=20000.0,
    sig_25=0.0830, dsig_dT=-1.40e-4,
    D_ref_25=1.3e-9,
    Cp_25=3600.0, dCp_dT=0.3,
    k_25=0.620, dk_dT=0.0010,
    hsp_d=15.5, hsp_p=16.0, hsp_h=42.3,
    aliases=("6M NaOH", "NaOH 6M", "Sodium Hydroxide 6M",
             "Caustic Soda 6M"),
    notes="6 mol/L NaOH in water (~19.3 wt%). "
          "Properties from CRC / ICT solution tables.",
))

# ─── 36% HCl (aq) ───────────────────────────────────────────────────────
# Concentrated (fuming) hydrochloric acid, ~11.6 M.
# Refs: CRC Handbook 97th Ed; Perry's 9th Ed;
#       Zaytsev & Aseyev, Properties of Aqueous Solutions of Electrolytes.
_add(SolventData(
    name="36% HCl (aq)", cas="7647-01-0", mw=36.46,
    mp_C=-52.0, bp_C=50.0,
    rho_25=1175.0, drho_dT=-0.55,
    mu_25=1.70e-3, Ea_mu=16000.0,
    sig_25=0.0700, dsig_dT=-1.30e-4,
    D_ref_25=1.5e-9,
    Cp_25=2700.0, dCp_dT=0.3,
    k_25=0.480, dk_dT=0.0008,
    hsp_d=15.5, hsp_p=16.0, hsp_h=42.3,
    aliases=("Conc HCl", "Concentrated HCl", "HCl 36%",
             "Hydrochloric Acid 36%", "Fuming HCl"),
    notes="36 wt% HCl in water (~11.6 M). Fuming acid — "
          "bp reflects onset of significant HCl loss. "
          "Properties from CRC / Zaytsev & Aseyev.",
))

# ─── 47% K₂CO₃ (aq) ─────────────────────────────────────────────────────
# Concentrated aqueous potassium carbonate.
# Refs: CRC Handbook 97th Ed; Perry's 9th Ed;
#       Zaytsev & Aseyev, Properties of Aqueous Solutions of Electrolytes.
_add(SolventData(
    name="47% K2CO3 (aq)", cas="584-08-7", mw=138.21,
    mp_C=-36.0, bp_C=109.0,
    rho_25=1485.0, drho_dT=-0.50,
    mu_25=5.00e-3, Ea_mu=22000.0,
    sig_25=0.0950, dsig_dT=-1.30e-4,
    D_ref_25=0.7e-9,
    Cp_25=2600.0, dCp_dT=0.2,
    k_25=0.520, dk_dT=0.0008,
    hsp_d=15.5, hsp_p=16.0, hsp_h=42.3,
    aliases=("K2CO3 47%", "Potassium Carbonate 47%",
             "47% Potassium Carbonate"),
    notes="47 wt% K₂CO₃ in water. Dense, viscous alkaline solution. "
          "Properties from CRC / Zaytsev & Aseyev.",
))


# ---------------------------------------------------------------------------
# Property computation
# ---------------------------------------------------------------------------

_ATM_TO_MMHG = 760.0  # 1 atm = 760 mmHg


def vapor_pressure_mmHg(T_C: float, solvent: SolventData) -> float:
    """Vapor pressure [mmHg] at temperature T_C [°C] via the Antoine equation.

    log10(P_mmHg) = A - B / (C + T_°C)
    """
    if solvent.antoine_A == 0.0:
        return float('nan')
    denom = solvent.antoine_C + T_C
    if denom == 0:
        return float('nan')
    return 10.0 ** (solvent.antoine_A - solvent.antoine_B / denom)


def vapor_pressure_atm(T_C: float, solvent: SolventData) -> float:
    """Vapor pressure [atm] at temperature T_C [°C]."""
    return vapor_pressure_mmHg(T_C, solvent) / _ATM_TO_MMHG


def boiling_point_at_pressure(P_atm: float, solvent: SolventData) -> float:
    """Boiling point [°C] at pressure P_atm [atm] via the Antoine equation.

    Rearranged: T_°C = B / (A - log10(P_mmHg)) - C
    """
    if solvent.antoine_A == 0.0 or P_atm <= 0:
        return solvent.bp_C
    P_mmHg = P_atm * _ATM_TO_MMHG
    log_P = math.log10(P_mmHg)
    denom = solvent.antoine_A - log_P
    if denom <= 0:
        return float('nan')
    return solvent.antoine_B / denom - solvent.antoine_C


def _liquid_range(solvent: SolventData, P_atm: float = 1.0) -> tuple[float, float]:
    """Return (T_min_C, T_max_C) for the liquid phase at the given pressure.

    The boiling point is adjusted via the Antoine equation.
    The melting point is assumed pressure-insensitive (valid at moderate P).
    """
    bp = boiling_point_at_pressure(P_atm, solvent) if P_atm != 1.0 else solvent.bp_C
    return (solvent.mp_C, bp)


def density(T_C: float, solvent: SolventData) -> float:
    """Density [kg/m³] at temperature T_C [°C]."""
    return solvent.rho_25 + solvent.drho_dT * (T_C - 25.0)


def viscosity(T_C: float, solvent: SolventData) -> float:
    """Dynamic viscosity [Pa·s] at temperature T_C [°C].

    Arrhenius form: μ(T) = μ₂₅ · exp[B·(1/T − 1/T_ref)]
    where B = E_a / R.
    """
    T_K = T_C + 273.15
    T_ref_K = 298.15
    B = solvent.Ea_mu / R_GAS
    return solvent.mu_25 * math.exp(B * (1.0 / T_K - 1.0 / T_ref_K))


def surface_tension(T_C: float, solvent: SolventData) -> float:
    """Surface tension [N/m] at temperature T_C [°C]."""
    return max(solvent.sig_25 + solvent.dsig_dT * (T_C - 25.0), 0.0)


def diffusivity(T_C: float, solvent: SolventData) -> float:
    """Molecular diffusivity [m²/s] (Stokes-Einstein scaling from 25 °C ref).

    D(T) = D₂₅ · (T_K / 298.15) · (μ₂₅ / μ(T))
    """
    T_K = T_C + 273.15
    mu_T = viscosity(T_C, solvent)
    if mu_T <= 0:
        return solvent.D_ref_25
    return solvent.D_ref_25 * (T_K / 298.15) * (solvent.mu_25 / mu_T)


def specific_heat(T_C: float, solvent: SolventData) -> float:
    """Specific heat capacity [J/(kg·K)] at temperature T_C [°C]."""
    return solvent.Cp_25 + solvent.dCp_dT * (T_C - 25.0)


def thermal_conductivity(T_C: float, solvent: SolventData) -> float:
    """Thermal conductivity [W/(m·K)] at temperature T_C [°C]."""
    return solvent.k_25 + solvent.dk_dT * (T_C - 25.0)


# ---------------------------------------------------------------------------
# Hansen Solubility Parameters
# ---------------------------------------------------------------------------

def hansen_distance(
    d1: float, p1: float, h1: float,
    d2: float, p2: float, h2: float,
) -> float:
    """Hansen distance R_a between two solvents in Hansen space (MPa^0.5).

    R_a = sqrt(4*(δd1-δd2)² + (δp1-δp2)² + (δh1-δh2)²)
    """
    return math.sqrt(
        4.0 * (d1 - d2) ** 2 + (p1 - p2) ** 2 + (h1 - h2) ** 2
    )


def miscibility_assessment(
    Ra: float,
) -> dict:
    """Assess miscibility based on Hansen distance R_a.

    Returns dict with keys: Ra, miscible (bool), assessment (str), color (str).

    Thresholds are calibrated for solvent–solvent pairs (larger than
    the polymer–solvent thresholds in Hansen 2007).  Aqueous systems
    involving water tend to produce high R_a values due to water's
    extreme δ_h; experimental data should always be consulted.
    """
    if Ra < 15.0:
        return {"Ra": Ra, "miscible": True,
                "assessment": "Likely miscible",
                "color": "red"}
    elif Ra < 25.0:
        return {"Ra": Ra, "miscible": True,
                "assessment": "Partially miscible / borderline",
                "color": "orange"}
    else:
        return {"Ra": Ra, "miscible": False,
                "assessment": "Likely immiscible",
                "color": "green"}


def get_hsp(name: str, custom_fluids=None) -> tuple[float, float, float] | None:
    """Return (hsp_d, hsp_p, hsp_h) for a solvent name, or None if not found.

    Checks built-in SOLVENT_DB first, then falls back to *custom_fluids*
    (a pandas DataFrame with columns ``fluid_name``, ``hsp_d``, ``hsp_p``, ``hsp_h``).
    """
    s = SOLVENT_DB.get(name)
    if s is not None:
        if s.hsp_d == 0.0 and s.hsp_p == 0.0 and s.hsp_h == 0.0:
            return None
        return (s.hsp_d, s.hsp_p, s.hsp_h)
    # Fallback: custom-fluid dataframe
    if custom_fluids is not None and not custom_fluids.empty:
        _rows = custom_fluids[custom_fluids["fluid_name"] == name]
        if not _rows.empty:
            _r = _rows.iloc[0]
            _d = float(_r.get("hsp_d", 0.0) or 0.0)
            _p = float(_r.get("hsp_p", 0.0) or 0.0)
            _h = float(_r.get("hsp_h", 0.0) or 0.0)
            if _d != 0.0 or _p != 0.0 or _h != 0.0:
                return (_d, _p, _h)
    return None


# ---------------------------------------------------------------------------
# Known miscibility lookup (experimental data)
# ---------------------------------------------------------------------------
# Encoding immiscible & partially-miscible pairs is more compact than
# listing all miscible ones (most organic solvents are mutually miscible).
# Source: Perry's 9e, CRC Handbook, Merck Index, practical experience.

_IMMISCIBLE: set[frozenset[str]] = {
    frozenset({a, b}) for a, b in [
        # Water–organic immiscible pairs
        ("Water", "Toluene"),
        ("Water", "DCM"),
        ("Water", "Chloroform"),
        ("Water", "Hexane"),
        ("Water", "Heptane"),
        ("Water", "Diethyl Ether"),
        # Aqueous solutions – same immiscibility as water
        ("6 M NaOH (aq)", "Toluene"),
        ("6 M NaOH (aq)", "DCM"),
        ("6 M NaOH (aq)", "Chloroform"),
        ("6 M NaOH (aq)", "Hexane"),
        ("6 M NaOH (aq)", "Heptane"),
        ("6 M NaOH (aq)", "Diethyl Ether"),
        ("36% HCl (aq)", "Toluene"),
        ("36% HCl (aq)", "DCM"),
        ("36% HCl (aq)", "Chloroform"),
        ("36% HCl (aq)", "Hexane"),
        ("36% HCl (aq)", "Heptane"),
        ("36% HCl (aq)", "Diethyl Ether"),
        ("47% K2CO3 (aq)", "Toluene"),
        ("47% K2CO3 (aq)", "DCM"),
        ("47% K2CO3 (aq)", "Chloroform"),
        ("47% K2CO3 (aq)", "Hexane"),
        ("47% K2CO3 (aq)", "Heptane"),
        ("47% K2CO3 (aq)", "Diethyl Ether"),
        # Hydrocarbon–polar aprotic
        ("Hexane", "DMSO"),
        ("Hexane", "DMF"),
        ("Hexane", "NMP"),
        ("Hexane", "Acetonitrile"),
        ("Heptane", "DMSO"),
        ("Heptane", "DMF"),
        ("Heptane", "NMP"),
        ("Heptane", "Acetonitrile"),
    ]
}

_PARTIALLY_MISCIBLE: set[frozenset[str]] = {
    frozenset({a, b}) for a, b in [
        ("Water", "Ethyl Acetate"),     # ~8% mutual solubility
        ("Water", "MTBE"),              # ~4% solubility
        ("Water", "2-MeTHF"),           # limited miscibility
        ("Water", "MEK"),               # ~24% in water at 20 °C
        # Aqueous solutions – same partial miscibility as water
        ("6 M NaOH (aq)", "Ethyl Acetate"),
        ("6 M NaOH (aq)", "MTBE"),
        ("6 M NaOH (aq)", "2-MeTHF"),
        ("6 M NaOH (aq)", "MEK"),
        ("36% HCl (aq)", "Ethyl Acetate"),
        ("36% HCl (aq)", "MTBE"),
        ("36% HCl (aq)", "2-MeTHF"),
        ("36% HCl (aq)", "MEK"),
        ("47% K2CO3 (aq)", "Ethyl Acetate"),
        ("47% K2CO3 (aq)", "MTBE"),
        ("47% K2CO3 (aq)", "2-MeTHF"),
        ("47% K2CO3 (aq)", "MEK"),
        ("Hexane", "Methanol"),         # UCST ~34 °C
        ("Heptane", "Methanol"),        # partial at RT
        ("Toluene", "DMSO"),            # limited mutual solubility
    ]
}


def solvent_miscibility(name1: str, name2: str, custom_fluids=None) -> dict:
    """Assess miscibility between two fluids.

    Uses a known-pairs lookup for built-in solvents; falls back to
    Hansen distance for custom / unknown pairs.

    Parameters
    ----------
    custom_fluids : DataFrame, optional
        Custom-fluid table with ``fluid_name``, ``hsp_d``, ``hsp_p``, ``hsp_h``
        columns.  Passed through to :func:`get_hsp` so Hansen distance can be
        computed for non-built-in fluids.

    Returns dict with keys:
        miscible (bool), assessment (str), source (str),
        Ra (float | None), hsp_1 (tuple | None), hsp_2 (tuple | None)
    """
    # Resolve aliases to canonical names
    _n1 = resolve_solvent_name(name1) or name1
    _n2 = resolve_solvent_name(name2) or name2

    pair = frozenset({_n1, _n2})
    hsp1 = get_hsp(_n1, custom_fluids)
    hsp2 = get_hsp(_n2, custom_fluids)
    Ra = hansen_distance(*hsp1, *hsp2) if (hsp1 and hsp2) else None

    # Same solvent → miscible
    if _n1 == _n2:
        return {"miscible": True, "assessment": "Same solvent — miscible",
                "source": "identity", "Ra": 0.0, "hsp_1": hsp1, "hsp_2": hsp2}

    # Check known lookup
    if pair in _IMMISCIBLE:
        return {"miscible": False, "assessment": "Immiscible (known pair)",
                "source": "lookup", "Ra": Ra, "hsp_1": hsp1, "hsp_2": hsp2}
    if pair in _PARTIALLY_MISCIBLE:
        return {"miscible": False,
                "assessment": "Partially miscible (known pair — limited mutual solubility)",
                "source": "lookup", "Ra": Ra, "hsp_1": hsp1, "hsp_2": hsp2}

    # Both solvents are built-in? Then if they're not in the immiscible/partial
    # lists, they are known to be miscible.
    both_builtin = (_n1 in SOLVENT_DB) and (_n2 in SOLVENT_DB)
    if both_builtin:
        return {"miscible": True,
                "assessment": "Miscible (known pair)",
                "source": "lookup", "Ra": Ra, "hsp_1": hsp1, "hsp_2": hsp2}

    # Fall back to Hansen distance for custom fluids
    if Ra is not None:
        m = miscibility_assessment(Ra)
        return {**m, "source": "Hansen estimate",
                "hsp_1": hsp1, "hsp_2": hsp2}

    # No data at all
    return {"miscible": None, "assessment": "Unknown — no HSP data available",
            "source": "none", "Ra": None, "hsp_1": None, "hsp_2": None}


def get_properties(solvent_name: str, T_C: float, P_atm: float = 1.0) -> dict:
    """Return a dict of all physical properties at the given temperature and pressure.

    Keys: rho_kg_m3, mu_Pa_s, D_mol_m2_s, surface_tension_N_m,
          Cp_J_per_kgK, k_W_per_mK,
          T_C, P_atm, solvent, bp_C, bp_at_P_C, mp_C, in_range,
          vapor_pressure_atm
    """
    if solvent_name not in SOLVENT_DB:
        raise KeyError(f"Unknown solvent: {solvent_name!r}.  "
                       f"Available: {sorted(SOLVENT_DB.keys())}")
    s = SOLVENT_DB[solvent_name]
    T_lo, T_hi = _liquid_range(s, P_atm)
    in_range = (T_lo <= T_C <= T_hi)
    bp_at_P = boiling_point_at_pressure(P_atm, s)
    Pvap = vapor_pressure_atm(T_C, s)
    return {
        "solvent": solvent_name,
        "T_C": T_C,
        "P_atm": P_atm,
        "in_range": in_range,
        "rho_kg_m3": density(T_C, s),
        "mu_Pa_s": viscosity(T_C, s),
        "D_mol_m2_s": diffusivity(T_C, s),
        "surface_tension_N_m": surface_tension(T_C, s),
        "Cp_J_per_kgK": specific_heat(T_C, s),
        "k_W_per_mK": thermal_conductivity(T_C, s),
        "bp_C": s.bp_C,
        "bp_at_P_C": bp_at_P,
        "mp_C": s.mp_C,
        "mw": s.mw,
        "cas": s.cas,
        "vapor_pressure_atm": Pvap,
        "hsp_d": s.hsp_d,
        "hsp_p": s.hsp_p,
        "hsp_h": s.hsp_h,
    }


def list_solvents() -> list[str]:
    """Return sorted list of available solvent names."""
    return sorted(SOLVENT_DB.keys())


def solvent_info_table() -> list[dict]:
    """Return a list-of-dicts summary for display (one row per solvent)."""
    rows = []
    for name, s in sorted(SOLVENT_DB.items()):
        rows.append({
            "Solvent": s.name,
            "Aliases": ", ".join(s.aliases) if s.aliases else "",
            "CAS": s.cas,
            "MW": s.mw,
            "m.p. (°C)": s.mp_C,
            "b.p. (°C)": s.bp_C,
            "ρ₂₅ (kg/m³)": f"{s.rho_25:.1f}",
            "μ₂₅ (mPa·s)": f"{s.mu_25 * 1000:.3f}",
            "σ₂₅ (mN/m)": f"{s.sig_25 * 1000:.1f}",
            "D₂₅ (m²/s)": f"{s.D_ref_25:.2e}",
            "Cp₂₅ (J/kg·K)": f"{s.Cp_25:.0f}",
            "k₂₅ (W/m·K)": f"{s.k_25:.3f}",
            "δd (MPa½)": f"{s.hsp_d:.1f}" if s.hsp_d else "—",
            "δp (MPa½)": f"{s.hsp_p:.1f}" if s.hsp_p else "—",
            "δh (MPa½)": f"{s.hsp_h:.1f}" if s.hsp_h else "—",
        })
    return rows


# Alias map: common abbreviation → canonical SOLVENT_DB key
_SOLVENT_ALIAS_MAP: dict[str, str] = {}

def _build_alias_map():
    """Populate the alias map from SOLVENT_DB names and their aliases field."""
    for key, sd in SOLVENT_DB.items():
        _SOLVENT_ALIAS_MAP[key.lower()] = key
        # Add common short forms from the display name
        base = key.split("(")[0].strip().lower()
        if base not in _SOLVENT_ALIAS_MAP:
            _SOLVENT_ALIAS_MAP[base] = key
        # Register all aliases from the aliases field
        for alias in sd.aliases:
            _SOLVENT_ALIAS_MAP[alias.lower()] = key

_build_alias_map()


def resolve_solvent_name(name: str) -> str | None:
    """Return the canonical SOLVENT_DB key for a name/alias, or None."""
    if name in SOLVENT_DB:
        return name
    return _SOLVENT_ALIAS_MAP.get(name.strip().lower())


def is_known_solvent(name: str) -> bool:
    """Return True if *name* matches a solvent name or alias."""
    return resolve_solvent_name(name) is not None
