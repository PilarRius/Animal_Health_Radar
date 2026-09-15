"""Typed, side-effect-safe reading and writing of pipeline artefacts.

All pipeline stages write Parquet (columnar, typed, fast for the app to load)
plus JSON for small metadata documents. Writes are atomic-ish: content goes to
a temporary file in the destination directory and is then moved into place, so
a crashed run never leaves a half-written Parquet that the app would load.
"""

from __future__ import annotations

import json
import os
import pickle
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.utils.logging_utils import get_logger
from src.utils.paths import ensure_parent, resolve_path

LOGGER = get_logger(__name__)

__all__ = [
    "read_parquet",
    "write_parquet",
    "read_json",
    "write_json",
    "read_csv",
    "write_csv",
    "save_pickle",
    "load_pickle",
    "JsonSafeEncoder",
]


class JsonSafeEncoder(json.JSONEncoder):
    """JSON encoder that understands dates, numpy scalars and Paths."""

    def default(self, o: Any) -> Any:  # noqa: D102
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            value = float(o)
            return None if (np.isnan(value) or np.isinf(value)) else value
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, Path):
            return str(o)
        if isinstance(o, pd.Timestamp):
            return None if pd.isna(o) else o.isoformat()
        if o is pd.NaT:
            return None
        return super().default(o)


def _atomic_replace(tmp: Path, target: Path) -> None:
    os.replace(tmp, target)


# --------------------------------------------------------------------------- #
# parquet
# --------------------------------------------------------------------------- #
def write_parquet(frame: pd.DataFrame, path: str | Path, *, index: bool = False) -> Path:
    """Write a DataFrame to Parquet atomically and return the resolved path."""
    target = ensure_parent(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    frame.to_parquet(tmp, index=index, engine="pyarrow", compression="snappy")
    _atomic_replace(tmp, target)
    LOGGER.debug("Wrote %s rows x %s cols -> %s", len(frame), frame.shape[1], target.name)
    return target


def read_parquet(path: str | Path, *, columns: list[str] | None = None) -> pd.DataFrame:
    """Read a Parquet artefact, raising a helpful error when the pipeline has not run."""
    target = resolve_path(path)
    if not target.is_file():
        raise FileNotFoundError(
            f"Missing pipeline artefact: {target}\n"
            "Run `python scripts/run_pipeline.py` to generate the processed data."
        )
    return pd.read_parquet(target, columns=columns, engine="pyarrow")


# --------------------------------------------------------------------------- #
# csv
# --------------------------------------------------------------------------- #
def write_csv(frame: pd.DataFrame, path: str | Path, *, index: bool = False) -> Path:
    target = ensure_parent(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    frame.to_csv(tmp, index=index, encoding="utf-8", lineterminator="\n")
    _atomic_replace(tmp, target)
    LOGGER.debug("Wrote %s rows -> %s", len(frame), target.name)
    return target


def read_csv(path: str | Path, *, parse_dates: list[str] | None = None) -> pd.DataFrame:
    target = resolve_path(path)
    if not target.is_file():
        raise FileNotFoundError(
            f"Missing input file: {target}\n"
            "Run `python scripts/ingest.py` to generate the sample corpus."
        )
    return pd.read_csv(target, parse_dates=parse_dates, encoding="utf-8")


# --------------------------------------------------------------------------- #
# json
# --------------------------------------------------------------------------- #
def write_json(payload: Mapping[str, Any] | list[Any], path: str | Path, *, indent: int = 2) -> Path:
    target = ensure_parent(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=indent, cls=JsonSafeEncoder, ensure_ascii=False)
    _atomic_replace(tmp, target)
    return target


def read_json(path: str | Path) -> Any:
    target = resolve_path(path)
    if not target.is_file():
        raise FileNotFoundError(f"Missing JSON artefact: {target}")
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------- #
# model persistence
# --------------------------------------------------------------------------- #
def save_pickle(obj: Any, path: str | Path) -> Path:
    """Persist a fitted model. Pickle is acceptable here: artefacts are produced
    and consumed by this repository only, never loaded from untrusted input."""
    target = ensure_parent(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("wb") as handle:
        pickle.dump(obj, handle, protocol=pickle.HIGHEST_PROTOCOL)
    _atomic_replace(tmp, target)
    return target


def load_pickle(path: str | Path) -> Any:
    target = resolve_path(path)
    if not target.is_file():
        raise FileNotFoundError(
            f"Missing model artefact: {target}\nRun `python scripts/train.py` first."
        )
    with target.open("rb") as handle:
        return pickle.load(handle)
