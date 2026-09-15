"""Harmonisation of adapter output into the analysis tables.

The adapters already emit canonical objects, so this stage is not about
reshaping: it is about **alignment and quality control** across sources that
were validated independently.

What happens here
-----------------
1. Country and disease labels are re-resolved through the shared resolvers, so
   a source that slipped a variant spelling past its own adapter is caught.
2. Dates are coerced to a single dtype and the causal ordering of the
   observation chain is checked (onset <= suspicion <= ... <= publication).
3. Every record is snapped onto the weekly panel grid twice: by
   ``reference_week`` (when it happened) and ``available_week`` (when it became
   knowable). Keeping both is what allows the reporting triangle to be built.
4. A data-quality report is produced rather than silently dropping rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.normalization.country_codes import resolve_iso3, unresolved_report
from src.normalization.disease_codes import resolve_disease, unresolved_disease_report
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["QualityReport", "canonicalise_events", "canonicalise_signals", "canonicalise_covariates"]

_EVENT_DATE_COLUMNS = [
    "onset_date", "suspicion_date", "confirmation_date",
    "notification_date", "publication_date", "resolved_date",
    "reference_date", "available_from",
]


@dataclass
class QualityReport:
    """What the harmonisation stage found. Surfaced in the app, not swallowed."""

    stage: str
    n_input: int = 0
    n_output: int = 0
    issues: dict[str, int] = field(default_factory=dict)
    unresolved_countries: dict[str, int] = field(default_factory=dict)
    unresolved_diseases: dict[str, int] = field(default_factory=dict)

    def add(self, issue: str, count: int = 1) -> None:
        if count:
            self.issues[issue] = self.issues.get(issue, 0) + int(count)

    @property
    def n_dropped(self) -> int:
        return self.n_input - self.n_output

    def to_frame(self) -> pd.DataFrame:
        rows = [{"stage": self.stage, "issue": k, "n_records": v} for k, v in self.issues.items()]
        rows.append({"stage": self.stage, "issue": "records_in", "n_records": self.n_input})
        rows.append({"stage": self.stage, "issue": "records_out", "n_records": self.n_output})
        return pd.DataFrame(rows)

    def log(self) -> None:
        LOGGER.info(
            "%s: %s in -> %s out (%s dropped)%s",
            self.stage, self.n_input, self.n_output, self.n_dropped,
            f"; issues={self.issues}" if self.issues else "",
        )


def _to_datetime(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _week_start(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    return (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.normalize()


def canonicalise_events(events: pd.DataFrame) -> tuple[pd.DataFrame, QualityReport]:
    """Align the event table and build its two time axes."""
    report = QualityReport(stage="canonicalise_events", n_input=len(events))
    if events.empty:
        return events, report

    frame = events.copy()
    frame = _to_datetime(frame, _EVENT_DATE_COLUMNS)

    # -- re-resolve identifiers ------------------------------------------ #
    resolved_iso = frame["country_iso3"].map(lambda v: resolve_iso3(v))
    changed_iso = int((resolved_iso.notna() & (resolved_iso != frame["country_iso3"])).sum())
    report.add("country_code_rewritten", changed_iso)
    report.add("country_unresolved", int(resolved_iso.isna().sum()))
    frame["country_iso3"] = resolved_iso

    resolved_disease = frame["disease"].map(lambda v: resolve_disease(v))
    report.add("disease_unresolved", int(resolved_disease.isna().sum()))
    frame["disease"] = resolved_disease

    frame = frame.loc[frame["country_iso3"].notna() & frame["disease"].notna()].copy()
    frame["entity_key"] = frame["country_iso3"] + "|" + frame["disease"]

    # -- availability is mandatory ---------------------------------------- #
    missing_availability = int(frame["available_from"].isna().sum())
    report.add("missing_available_from", missing_availability)
    frame = frame.loc[frame["available_from"].notna()].copy()

    # -- causal ordering of the observation chain -------------------------- #
    chain = ["onset_date", "suspicion_date", "confirmation_date", "notification_date", "publication_date"]
    present = [c for c in chain if c in frame.columns]
    violation = pd.Series(False, index=frame.index)
    for earlier, later in zip(present, present[1:], strict=False):
        both = frame[earlier].notna() & frame[later].notna()
        violation |= both & (frame[earlier] > frame[later])
    frame["timeline_inconsistent"] = violation
    report.add("timeline_inconsistent", int(violation.sum()))

    # -- the two time axes -------------------------------------------------- #
    frame["reference_week"] = _week_start(frame["reference_date"])
    frame["available_week"] = _week_start(frame["available_from"])
    negative_delay = int(
        (frame["available_from"] < frame["reference_date"]).fillna(False).sum()
    )
    report.add("available_before_reference", negative_delay)

    # Reporting delay used by the delay model; keep only plausible values.
    if "reporting_delay_days" in frame.columns:
        delays = pd.to_numeric(frame["reporting_delay_days"], errors="coerce")
        implausible = int(((delays < 0) | (delays > 365)).fillna(False).sum())
        report.add("implausible_reporting_delay", implausible)
        frame["reporting_delay_days"] = delays.where((delays >= 0) & (delays <= 365))

    # -- magnitude sanity --------------------------------------------------- #
    for column in ("cases", "deaths", "outbreaks", "killed_disposed", "susceptible"):
        if column in frame.columns:
            values = pd.to_numeric(frame[column], errors="coerce")
            frame[column] = values.where(values >= 0)
    if {"cases", "deaths"}.issubset(frame.columns):
        impossible = int((frame["deaths"] > frame["cases"]).fillna(False).sum())
        report.add("deaths_exceed_cases", impossible)

    frame = frame.sort_values(["available_from", "event_id"]).reset_index(drop=True)
    report.n_output = len(frame)
    report.unresolved_countries = unresolved_report()
    report.unresolved_diseases = unresolved_disease_report()
    report.log()
    return frame, report


def canonicalise_signals(signals: pd.DataFrame) -> tuple[pd.DataFrame, QualityReport]:
    """Align the signal table onto the weekly grid."""
    report = QualityReport(stage="canonicalise_signals", n_input=len(signals))
    if signals.empty:
        return signals, report

    frame = signals.copy()
    frame = _to_datetime(frame, ["reference_date", "available_from"])
    frame["country_iso3"] = frame["country_iso3"].map(lambda v: resolve_iso3(v))
    frame["disease"] = frame["disease"].map(lambda v: resolve_disease(v))
    report.add("country_unresolved", int(frame["country_iso3"].isna().sum()))
    report.add("disease_unresolved", int(frame["disease"].isna().sum()))
    frame = frame.loc[frame["country_iso3"].notna() & frame["disease"].notna()].copy()
    frame["entity_key"] = frame["country_iso3"] + "|" + frame["disease"]

    non_finite = int((~np.isfinite(pd.to_numeric(frame["value"], errors="coerce"))).sum())
    report.add("non_finite_value", non_finite)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.loc[np.isfinite(frame["value"])].copy()

    leaking = int((frame["available_from"] < frame["reference_date"]).sum())
    report.add("available_before_reference", leaking)
    frame = frame.loc[frame["available_from"] >= frame["reference_date"]].copy()

    frame["reference_week"] = _week_start(frame["reference_date"])
    report.n_output = len(frame)
    report.log()
    return frame.reset_index(drop=True), report


def canonicalise_covariates(covariates: pd.DataFrame) -> tuple[pd.DataFrame, QualityReport]:
    """Align the covariate table; these are disease-agnostic by default."""
    report = QualityReport(stage="canonicalise_covariates", n_input=len(covariates))
    if covariates.empty:
        return covariates, report

    frame = covariates.copy()
    frame = _to_datetime(frame, ["reference_date", "available_from"])
    frame["country_iso3"] = frame["country_iso3"].map(lambda v: resolve_iso3(v))
    report.add("country_unresolved", int(frame["country_iso3"].isna().sum()))
    frame = frame.loc[frame["country_iso3"].notna()].copy()

    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    report.add("non_finite_value", int(frame["value"].isna().sum()))
    frame = frame.loc[frame["value"].notna()].copy()

    leaking = int((frame["available_from"] < frame["reference_date"]).sum())
    report.add("available_before_reference", leaking)
    frame = frame.loc[frame["available_from"] >= frame["reference_date"]].copy()

    frame["reference_week"] = _week_start(frame["reference_date"])
    report.n_output = len(frame)
    report.log()
    return frame.reset_index(drop=True), report


def combined_quality_frame(reports: list[QualityReport]) -> pd.DataFrame:
    """Stack several quality reports for the dashboard's data-quality panel."""
    frames = [report.to_frame() for report in reports if report.n_input]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["stage", "issue", "n_records"]
    )


def describe_dtypes(frame: pd.DataFrame) -> dict[str, Any]:
    """Compact dtype summary used in pipeline logs."""
    return {column: str(dtype) for column, dtype in frame.dtypes.items()}
