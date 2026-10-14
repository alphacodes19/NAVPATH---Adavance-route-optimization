"""Deprecated compatibility shim for the former land-cell storage module.

The canonical mask now lives in :mod:`src.engine.land_data`. Internal project
code should import LAND_CELLS directly from that module. This shim remains for
older scripts that still access ``storage.Backup_black_cells``.
"""

import warnings

from src.engine.land_data import LAND_CELLS


def __getattr__(name: str):
    if name == "Backup_black_cells":
        warnings.warn(
            "storage.Backup_black_cells is deprecated; use "
            "src.engine.land_data.LAND_CELLS instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return LAND_CELLS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
