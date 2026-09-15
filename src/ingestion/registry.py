"""Adapter registry and the ingestion run.

The registry is the single place that knows which sources exist. Everything
downstream -- the pipeline, the provenance ledger, the source catalogue shown
in the dashboard -- is derived from it, so adding a source is a one-line change
plus an adapter module.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

from src.ingestion.base import AdapterOutput, LiveSourceUnavailable, SourceAdapter
from src.ingestion.beacon import BEACONAdapter
from src.ingestion.eios import EIOSAdapter
from src.ingestion.empresi import EMPRESiAdapter
from src.ingestion.era5 import ERA5Adapter, ERA5LandAdapter
from src.ingestion.faostat import FAOSTATAdapter
from src.ingestion.gdelt import GDELTAdapter
from src.ingestion.glw4 import GLW4Adapter
from src.ingestion.healthmap import HealthMapAdapter
from src.ingestion.padiweb import PADIWebAdapter
from src.ingestion.promed import ProMEDAdapter
from src.ingestion.wahis import WAHISAdapter
from src.ingestion.worldclim import WorldClimAdapter
from src.utils.config import AppConfig, get_config
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = [
    "ADAPTER_REGISTRY",
    "IngestionResult",
    "build_adapters",
    "run_ingestion",
    "source_catalogue",
]

#: Ordered so that the primary official source is always ingested first.
ADAPTER_REGISTRY: dict[str, type[SourceAdapter]] = {
    "wahis": WAHISAdapter,
    "empresi": EMPRESiAdapter,
    "beacon": BEACONAdapter,
    "padiweb": PADIWebAdapter,
    "gdelt": GDELTAdapter,
    "eios": EIOSAdapter,
    "promed": ProMEDAdapter,
    "healthmap": HealthMapAdapter,
    "era5": ERA5Adapter,
    "era5_land": ERA5LandAdapter,
    "worldclim": WorldClimAdapter,
    "glw4": GLW4Adapter,
    "faostat": FAOSTATAdapter,
}


class IngestionResult:
    """Aggregated output of every adapter, as tidy frames."""

    def __init__(self, outputs: Sequence[AdapterOutput]) -> None:
        self.outputs = list(outputs)

    # -- tidy frames ------------------------------------------------------ #
    @property
    def events(self) -> pd.DataFrame:
        rows = [event.to_flat() for output in self.outputs for event in output.events]
        frame = pd.DataFrame(rows)
        return self._sort(frame, ["available_from", "event_id"])

    @property
    def signals(self) -> pd.DataFrame:
        rows = [signal.to_flat() for output in self.outputs for signal in output.signals]
        frame = pd.DataFrame(rows)
        return self._sort(frame, ["available_from", "signal_id"])

    @property
    def covariates(self) -> pd.DataFrame:
        rows = [cov.to_flat() for output in self.outputs for cov in output.covariates]
        frame = pd.DataFrame(rows)
        return self._sort(frame, ["available_from", "covariate_id"])

    @property
    def provenance(self) -> pd.DataFrame:
        seen: dict[str, dict[str, Any]] = {}
        for output in self.outputs:
            for prov in output.provenance:
                seen.setdefault(prov.fingerprint(), prov.to_flat())
        return pd.DataFrame(list(seen.values()))

    @property
    def notes(self) -> pd.DataFrame:
        rows = [
            {"source_name": output.source_name, "note": note}
            for output in self.outputs
            for note in output.notes
        ]
        return pd.DataFrame(rows)

    def summary(self) -> pd.DataFrame:
        return pd.DataFrame([output.summary() for output in self.outputs])

    @staticmethod
    def _sort(frame: pd.DataFrame, by: list[str]) -> pd.DataFrame:
        if frame.empty:
            return frame
        available = [column for column in by if column in frame.columns]
        return frame.sort_values(available).reset_index(drop=True) if available else frame


def build_adapters(
    config: AppConfig | None = None, only: Iterable[str] | None = None
) -> list[SourceAdapter]:
    """Instantiate the registered adapters, optionally filtered by key."""
    config = config or get_config()
    keys = list(only) if only is not None else list(ADAPTER_REGISTRY)
    unknown = [key for key in keys if key not in ADAPTER_REGISTRY]
    if unknown:
        raise KeyError(f"Unknown adapter key(s): {unknown}. Known: {list(ADAPTER_REGISTRY)}")
    return [ADAPTER_REGISTRY[key](config=config) for key in keys]


def run_ingestion(
    config: AppConfig | None = None,
    only: Iterable[str] | None = None,
    *,
    strict: bool = False,
) -> IngestionResult:
    """Run every adapter and collect the results.

    Parameters
    ----------
    strict:
        When ``True`` an unavailable source aborts the run. When ``False``
        (the default) the source is skipped with a loud warning, so a partial
        corpus still produces a partial -- and clearly labelled -- analysis.
    """
    config = config or get_config()
    LOGGER.info("Ingesting sources in '%s' mode (cut-off %s)", config.data_mode, config.data_cutoff)

    outputs: list[AdapterOutput] = []
    for adapter in build_adapters(config=config, only=only):
        try:
            outputs.append(adapter.run())
        except (LiveSourceUnavailable, FileNotFoundError) as exc:
            if strict:
                raise
            LOGGER.warning("Skipping %s: %s", adapter.source_name, str(exc).splitlines()[0])
            outputs.append(
                AdapterOutput(
                    source_name=adapter.source_name,
                    notes=[f"SOURCE UNAVAILABLE: {exc}"],
                )
            )
    return IngestionResult(outputs)


def source_catalogue(config: AppConfig | None = None) -> pd.DataFrame:
    """Static description of every registered source, for the provenance screen."""
    return pd.DataFrame([adapter.describe() for adapter in build_adapters(config=config)])
