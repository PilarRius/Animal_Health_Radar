"""Animal Health Radar - source package.

The package is organised along the causal chain that the system models::

    TRUE / LATENT DISEASE STATE
        -> SURVEILLANCE + DETECTION
            -> REPORTING / CONFIRMATION
                -> OFFICIAL OBSERVATION (WAHIS)

Sub-packages
------------
ingestion      Source adapters (official, intelligence, environmental, exposure).
schemas        Pydantic contracts for every object that crosses a boundary.
normalization  Mapping heterogeneous records onto the canonical event schema.
linkage        Entity resolution, de-duplication and evidence-independence.
features       Point-in-time-correct feature store and feature builders.
models         Delay, nowcast, early-warning and forecast models.
forecasting    Horizon orchestration and probabilistic ensembling.
evaluation     Timeliness, nowcast, forecast and leakage evaluation.
alerts         Alert construction, explanation and counterfactual ablation.
provenance     Source provenance ledger.
visualization  Figure builders shared by the app and the reports.
utils          Configuration, paths, dates, as-of filtering, statistics.
"""

__version__ = "0.1.0"
