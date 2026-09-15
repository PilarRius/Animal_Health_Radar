"""Repository path resolution.

Every other module asks this module where things live, so the project can be
executed from any working directory (``python scripts/run_pipeline.py``,
``shiny run app.py``, ``pytest``) without path juggling.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "PROJECT_ROOT",
    "CONFIG_DIR",
    "DATA_DIR",
    "ensure_dir",
    "resolve_path",
]


def _discover_project_root() -> Path:
    """Locate the repository root.

    Priority: ``AHR_PROJECT_ROOT`` env var, then the nearest ancestor of this
    file that contains ``pyproject.toml``, then a three-level walk-up fallback.
    """
    env_root = os.environ.get("AHR_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "config").is_dir():
            return candidate
    # src/utils/paths.py -> src/utils -> src -> root
    return here.parents[2]


PROJECT_ROOT: Path = _discover_project_root()
CONFIG_DIR: Path = PROJECT_ROOT / "config"
DATA_DIR: Path = PROJECT_ROOT / "data"


def resolve_path(path_like: str | Path) -> Path:
    """Resolve *path_like* against the project root unless it is absolute."""
    path = Path(path_like)
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def ensure_dir(path_like: str | Path) -> Path:
    """Create a directory (and parents) if needed and return it."""
    path = resolve_path(path_like)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path_like: str | Path) -> Path:
    """Create the parent directory of a file path and return the file path."""
    path = resolve_path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
