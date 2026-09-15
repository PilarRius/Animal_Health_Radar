"""Make the repository importable when scripts are run directly.

``python scripts/train.py`` puts ``scripts/`` on ``sys.path``, not the project
root, so ``import src...`` would fail. Importing this module first fixes that
without requiring the package to be pip-installed.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Empty-slice and all-NA-concat warnings are expected at the edges of the panel
# (an entity with no history yet, a feature family with no rows for a vintage).
# They are handled explicitly in the code that raises them, so silence the noise
# rather than let it bury the pipeline log.
warnings.filterwarnings("ignore", category=RuntimeWarning, message="Mean of empty slice")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="All-NaN slice encountered")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="invalid value encountered")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="Degrees of freedom <= 0")
warnings.filterwarnings("ignore", category=FutureWarning)

__all__ = ["PROJECT_ROOT"]
