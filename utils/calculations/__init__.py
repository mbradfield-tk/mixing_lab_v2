"""
Hydrodynamic and mixing calculations for stirred-tank and continuous-flow reactors.

This package re-exports all public names from its submodules so that existing
``from utils.calculations import X`` imports continue to work unchanged.
"""

from .hydrodynamics import *          # noqa: F401,F403
from .mixing_times import *           # noqa: F401,F403
from .solid_liquid import *           # noqa: F401,F403
from .gas_liquid import *             # noqa: F401,F403
from .liquid_liquid import *          # noqa: F401,F403
from .damkohler import *             # noqa: F401,F403
from .scale_up import *              # noqa: F401,F403
from .geometry import *              # noqa: F401,F403
from .reactor_hydro import *         # noqa: F401,F403
from .heat_transfer import *         # noqa: F401,F403
from .heat_transfer import (         # noqa: F401 – private helpers used by pages
    _lookup_wall_k, _lookup_lining_k, _lookup_solvent_thermal, _compute_hi,
)
