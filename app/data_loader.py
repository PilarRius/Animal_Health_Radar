"""Load precomputed parquet artefacts for the Shiny app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from src.utils.config import get_config, load_countries, load_diseases
from src.utils.io import read_json, read_parquet


@dataclass
class AppData:
    predictions: pd.DataFrame
    alerts: pd.DataFrame
    explanations: dict
    nowcast_latest: pd.DataFrame | None
    countries: dict
    diseases: dict
    data_mode: str
    as_of_dates: list[str]
    project_root: Path

    @classmethod
    def load(cls, project_root: Path) -> AppData:
        config = get_config()
        processed = config.path("data_processed")
        predictions = read_parquet(processed / "predictions.parquet")
        alerts = read_parquet(processed / "alerts.parquet")
        explanations = {}
        exp_path = processed / "explanations.json"
        if exp_path.exists():
            explanations = read_json(exp_path)
        nowcast = None
        nc_path = processed / "nowcast_latest.parquet"
        if nc_path.exists():
            nowcast = read_parquet(nc_path)

        as_of_dates = sorted(predictions["as_of_date"].astype(str).unique().tolist())
        return cls(
            predictions=predictions,
            alerts=alerts,
            explanations=explanations,
            nowcast_latest=nowcast,
            countries=load_countries(),
            diseases=load_diseases(),
            data_mode=config.data_mode,
            as_of_dates=as_of_dates,
            project_root=project_root,
        )

    def predictions_as_of(self, as_of: str, disease: str) -> pd.DataFrame:
        frame = self.predictions.loc[self.predictions["as_of_date"].astype(str) == str(as_of)].copy()
        if disease and disease != "ALL":
            frame = frame.loc[frame["disease"] == disease]
        return frame

    def entity_series(self, entity_key: str) -> pd.DataFrame:
        return (
            self.predictions.loc[self.predictions["entity_key"] == entity_key]
            .sort_values("as_of_date")
            .copy()
        )

    def explanation_for(self, alert_id: str) -> dict | None:
        for item in self.explanations.get("explanations", []):
            if item.get("alert_id") == alert_id:
                return item.get("explanation")
        return None
