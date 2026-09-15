"""Stage 1 - ingestion, normalisation and linkage.

::

    python scripts/ingest.py [--force-sample] [--strict]

What it does
------------
1. Generates the labelled synthetic corpus (sample mode only).
2. Runs every registered adapter and collects canonical events, signals and
   covariates, each stamped with provenance and an availability date.
3. Harmonises country and disease labels and reports data-quality issues.
4. Resolves records across sources into canonical events, de-duplicates the
   official burden and builds the reporting triangle the nowcast needs.

Outputs land in ``data/interim/`` and are consumed by
``scripts/build_features.py``.
"""

from __future__ import annotations

import argparse
from typing import Any

import _bootstrap  # noqa: F401  (side effect: sys.path)
import pandas as pd

from src.ingestion import generate_sample_corpus, run_ingestion, source_catalogue
from src.linkage import (
    build_reporting_triangle,
    deduplicate_official,
    evidence_sets,
    resolve_entities,
)
from src.normalization import (
    canonicalise_covariates,
    canonicalise_events,
    canonicalise_signals,
    combined_quality_frame,
)
from src.utils.config import get_config
from src.utils.io import read_parquet, write_json, write_parquet
from src.utils.logging_utils import get_logger, setup_logging
from src.utils.paths import ensure_dir

LOGGER = get_logger("scripts.ingest")


def run(
    force_sample: bool = False, strict: bool = False, reuse_adapters: bool = False
) -> dict[str, Any]:
    """Execute the ingestion stage and return a manifest of what was written."""
    config = get_config()
    interim = ensure_dir(config.path("data_interim"))

    cached = {
        name: interim / f"{name}.parquet" for name in ("events", "signals", "covariates")
    }
    can_reuse = reuse_adapters and all(path.is_file() for path in cached.values())

    if can_reuse:
        LOGGER.info("Stage 1a-c | reusing cached adapter output in %s", interim)
        events = read_parquet(cached["events"])
        signals = read_parquet(cached["signals"])
        covariates = read_parquet(cached["covariates"])
        provenance = read_parquet(interim / "provenance.parquet")
        notes = read_parquet(interim / "adapter_notes.parquet")
        quality = read_parquet(interim / "data_quality.parquet")
    else:
        # -- 1. sample corpus --------------------------------------------- #
        if config.data_mode == "sample":
            LOGGER.info("Stage 1a | synthetic sample corpus")
            generate_sample_corpus(config=config, force=force_sample)
        else:
            LOGGER.info("Stage 1a | live mode: skipping synthetic corpus generation")

        # -- 2. adapters ---------------------------------------------------- #
        LOGGER.info("Stage 1b | source adapters")
        result = run_ingestion(config=config, strict=strict)
        provenance, notes = result.provenance, result.notes

        # -- 3. normalisation ------------------------------------------------ #
        LOGGER.info("Stage 1c | normalisation")
        events, event_report = canonicalise_events(result.events)
        signals, signal_report = canonicalise_signals(result.signals)
        covariates, covariate_report = canonicalise_covariates(result.covariates)
        quality = combined_quality_frame([event_report, signal_report, covariate_report])

    # -- 4. linkage ---------------------------------------------------------- #
    LOGGER.info("Stage 1d | entity resolution and de-duplication")
    linkage = resolve_entities(events)
    official = deduplicate_official(linkage.events)
    triangle = build_reporting_triangle(official)
    evidence = evidence_sets(linkage.events)

    # -- 5. persist ---------------------------------------------------------- #
    artefacts = {
        "events.parquet": events,
        "signals.parquet": signals,
        "covariates.parquet": covariates,
        "provenance.parquet": provenance,
        "adapter_notes.parquet": notes,
        "data_quality.parquet": quality,
        "linked_events.parquet": linkage.events,
        "linkage_clusters.parquet": linkage.clusters,
        "linkage_decisions.parquet": linkage.decisions,
        "canonical_events.parquet": official,
        "reporting_triangle.parquet": triangle,
        "evidence_sets.parquet": evidence,
        "source_catalogue.parquet": source_catalogue(config=config),
    }
    manifest: dict[str, Any] = {"stage": "ingest", "data_mode": config.data_mode,
                                "data_cutoff": config.data_cutoff.isoformat(), "files": {}}
    for filename, frame in artefacts.items():
        frame = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
        write_parquet(frame, interim / filename)
        manifest["files"][filename] = {"rows": int(len(frame)), "columns": list(frame.columns)}

    manifest["summary"] = {
        "events": int(len(events)),
        "signals": int(len(signals)),
        "covariates": int(len(covariates)),
        "canonical_events": int(len(official)),
        "duplication_ratio": round(linkage.summary()["duplication_ratio"], 3),
        "entities": int(events["entity_key"].nunique()) if not events.empty else 0,
    }
    write_json(manifest, interim / "ingest_manifest.json")

    LOGGER.info("Stage 1 complete | %s", manifest["summary"])
    _log_lead_time(linkage.clusters)
    return manifest


def _log_lead_time(clusters: pd.DataFrame) -> None:
    """Report how far intelligence ran ahead of the official record."""
    if clusters.empty or "intelligence_lead_days" not in clusters.columns:
        return
    lead = pd.to_numeric(clusters["intelligence_lead_days"], errors="coerce").dropna()
    lead = lead.loc[lead > 0]
    if lead.empty:
        LOGGER.info(
            "No cluster has a non-official record ahead of the official one. This is expected: "
            "media and aggregator adapters emit weekly SIGNALS rather than discrete events, so "
            "their lead over the official record is measured in src.evaluation.timeliness, not here."
        )
        return
    LOGGER.info(
        "Intelligence lead over the official record: median %.1f d, p90 %.1f d, n=%s clusters",
        float(lead.median()), float(lead.quantile(0.9)), len(lead),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-sample", action="store_true",
                        help="regenerate the synthetic corpus even if it exists")
    parser.add_argument("--strict", action="store_true",
                        help="abort if any source is unavailable instead of skipping it")
    parser.add_argument("--reuse-adapters", action="store_true",
                        help="skip adapters and normalisation, reusing cached interim tables "
                             "(development shortcut; re-runs linkage only)")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args()

    setup_logging(args.log_level)
    run(force_sample=args.force_sample, strict=args.strict, reuse_adapters=args.reuse_adapters)


if __name__ == "__main__":
    main()
