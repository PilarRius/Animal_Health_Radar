"""Typed access to the YAML configuration in ``config/``.

Configuration is loaded once and cached. Modules never read YAML directly, so
that (a) defaults live in exactly one place and (b) tests can inject overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.utils.paths import CONFIG_DIR, resolve_path

__all__ = [
    "AppConfig",
    "CountrySpec",
    "DiseaseSpec",
    "get_config",
    "load_countries",
    "load_diseases",
    "load_thresholds",
    "clear_config_cache",
]


# --------------------------------------------------------------------------- #
# raw YAML loading
# --------------------------------------------------------------------------- #
def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        content = yaml.safe_load(handle)
    if not isinstance(content, dict):
        raise ValueError(f"Configuration file {path} did not parse to a mapping.")
    return content


@lru_cache(maxsize=None)
def _load_yaml_cached(name: str) -> dict[str, Any]:
    return _read_yaml(CONFIG_DIR / name)


# --------------------------------------------------------------------------- #
# lightweight typed views
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CountrySpec:
    """A country in the analysis panel."""

    iso3: str
    name: str
    region: str
    lat: float
    lon: float
    area_km2: float
    surveillance_capacity: str
    livestock: dict[str, float] = field(default_factory=dict)
    neighbours: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> CountrySpec:
        centroid = raw.get("centroid", {}) or {}
        return cls(
            iso3=str(raw["iso3"]).upper(),
            name=str(raw["name"]),
            region=str(raw.get("region", "Unknown")),
            lat=float(centroid.get("lat", 0.0)),
            lon=float(centroid.get("lon", 0.0)),
            area_km2=float(raw.get("area_km2", 0.0) or 0.0),
            surveillance_capacity=str(raw.get("surveillance_capacity", "medium")).lower(),
            livestock={k: float(v) for k, v in (raw.get("livestock") or {}).items()},
            neighbours=tuple(str(n).upper() for n in (raw.get("neighbours") or [])),
        )


@dataclass(frozen=True)
class DiseaseSpec:
    """A disease in the analysis panel."""

    code: str
    name: str
    wahis_name: str
    pathogen: str
    host_groups: tuple[str, ...]
    species: tuple[str, ...]
    incubation_days_mean: float
    incubation_days_sd: float
    seasonality: dict[str, float]
    environment: dict[str, float]
    exposure_layer: str
    outbreak_size: dict[str, float]
    baseline_hazard: float
    self_excitation: float
    spatial_excitation: float
    reporting_delay: dict[str, float]
    exceedance_threshold_weekly: float
    colour: str
    country_risk_multiplier: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> DiseaseSpec:
        return cls(
            code=str(raw["code"]).upper(),
            name=str(raw["name"]),
            wahis_name=str(raw.get("wahis_name", raw["name"])),
            pathogen=str(raw.get("pathogen", "")),
            host_groups=tuple(raw.get("host_groups", ())),
            species=tuple(raw.get("species", ())),
            incubation_days_mean=float(raw.get("incubation_days_mean", 5.0)),
            incubation_days_sd=float(raw.get("incubation_days_sd", 2.0)),
            seasonality={k: float(v) for k, v in (raw.get("seasonality") or {}).items()},
            environment={k: float(v) for k, v in (raw.get("environment") or {}).items()},
            exposure_layer=str(raw.get("exposure_layer", "")),
            outbreak_size={k: float(v) for k, v in (raw.get("outbreak_size") or {}).items()},
            baseline_hazard=float(raw.get("baseline_hazard", 0.05)),
            self_excitation=float(raw.get("self_excitation", 0.5)),
            spatial_excitation=float(raw.get("spatial_excitation", 0.3)),
            reporting_delay={k: float(v) for k, v in (raw.get("reporting_delay") or {}).items()},
            exceedance_threshold_weekly=float(raw.get("exceedance_threshold_weekly", 5)),
            colour=str(raw.get("colour", "#888888")),
            country_risk_multiplier={
                str(k).upper(): float(v)
                for k, v in (raw.get("country_risk_multiplier") or {}).items()
            },
        )


# --------------------------------------------------------------------------- #
# master config object
# --------------------------------------------------------------------------- #
class AppConfig:
    """Facade over ``config/config.yaml`` with typed accessors.

    Attribute access falls through to the raw mapping via :meth:`get`, using
    dotted paths (``cfg.get("time.data_cutoff")``).
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    # -- generic access ---------------------------------------------------- #
    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Fetch a nested value with a dotted path, e.g. ``"time.start_date"``."""
        node: Any = self._raw
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        value = self._raw.get(name, {})
        return value if isinstance(value, dict) else {}

    # -- frequently used, strongly typed ----------------------------------- #
    @property
    def random_seed(self) -> int:
        return int(self.get("project.random_seed", 12345))

    @property
    def data_mode(self) -> str:
        return str(os.environ.get("AHR_DATA_MODE", self.get("project.data_mode", "sample"))).lower()

    @property
    def start_date(self) -> date:
        return date.fromisoformat(str(self.get("time.start_date")))

    @property
    def end_date(self) -> date:
        return date.fromisoformat(str(self.get("time.end_date")))

    @property
    def data_cutoff(self) -> date:
        """The pipeline's 'today'. Nothing published after this may be used."""
        override = os.environ.get("AHR_DATA_CUTOFF")
        if override:
            return date.fromisoformat(override)
        return date.fromisoformat(str(self.get("time.data_cutoff")))

    @property
    def panel_frequency(self) -> str:
        return str(self.get("time.panel_frequency", "W-MON"))

    @property
    def quantiles(self) -> list[float]:
        return [float(q) for q in self.get("horizons.quantiles", [0.05, 0.5, 0.95])]

    @property
    def forecast_days(self) -> list[int]:
        return [int(h) for h in self.get("horizons.forecast_days", [7, 14, 28])]

    @property
    def central_interval(self) -> float:
        return float(self.get("horizons.central_interval", 0.90))

    @property
    def mc_draws(self) -> int:
        return int(self.get("horizons.mc_draws", 500))

    # -- paths -------------------------------------------------------------- #
    def path(self, key: str) -> Path:
        """Resolve one of the entries under ``paths:`` to an absolute path."""
        raw_path = self.get(f"paths.{key}")
        if raw_path is None:
            raise KeyError(f"Unknown configured path: paths.{key}")
        return resolve_path(str(raw_path))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AppConfig mode={self.data_mode!r} cutoff={self.data_cutoff.isoformat()}>"


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Load and cache ``config/config.yaml``."""
    return AppConfig(_load_yaml_cached("config.yaml"))


@lru_cache(maxsize=1)
def load_countries() -> dict[str, CountrySpec]:
    """Return the enabled countries keyed by ISO3 code, preserving file order."""
    raw = _load_yaml_cached("countries.yaml")
    enabled = {str(c).upper() for c in raw.get("enabled", [])}
    specs: dict[str, CountrySpec] = {}
    for entry in raw.get("countries", []):
        spec = CountrySpec.from_mapping(entry)
        if not enabled or spec.iso3 in enabled:
            specs[spec.iso3] = spec
    if not specs:
        raise ValueError("countries.yaml produced an empty country panel.")
    return specs


@lru_cache(maxsize=1)
def load_diseases() -> dict[str, DiseaseSpec]:
    """Return the enabled diseases keyed by code."""
    raw = _load_yaml_cached("diseases.yaml")
    enabled = {str(d).upper() for d in raw.get("enabled", [])}
    specs: dict[str, DiseaseSpec] = {}
    for code, entry in (raw.get("diseases") or {}).items():
        entry = dict(entry)
        entry.setdefault("code", code)
        spec = DiseaseSpec.from_mapping(entry)
        if not enabled or spec.code in enabled:
            specs[spec.code] = spec
    if not specs:
        raise ValueError("diseases.yaml produced an empty disease panel.")
    return specs


@lru_cache(maxsize=1)
def load_thresholds() -> dict[str, Any]:
    """Return the operational decision thresholds."""
    return _load_yaml_cached("thresholds.yaml")


def clear_config_cache() -> None:
    """Drop all cached configuration (used by tests that patch YAML)."""
    _load_yaml_cached.cache_clear()
    get_config.cache_clear()
    load_countries.cache_clear()
    load_diseases.cache_clear()
    load_thresholds.cache_clear()
