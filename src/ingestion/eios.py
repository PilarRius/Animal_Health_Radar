"""EIOS adapter — WHO Epidemic Intelligence from Open Sources.

Priority in pilot / offline / live modes
----------------------------------------
1. Offline portal export under ``data/raw/eios/*.csv|xlsx`` (full community export)
2. Public WHO Pandemic Hub newsmap feed (recent EIOS-tagged open news)
3. Labelled MOCK corpus (sample mode / last resort)

The newsmap is **not** the restricted EIOS portal — it is the public map at
``https://portal.who.int/pandemichub/newsmap/`` (WHO/JRC), which exposes a
``tunnel`` JSON API for recent articles. See ``docs/EIOS_BEACON_ACCESS.md``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingestion.base import AdapterOutput, LiveSourceUnavailable, SourceAdapter
from src.ingestion.eios_newsmap_client import (
    EIOS_NEWSMAP_BASE,
    EIOS_NEWSMAP_CATEGORIES,
    fetch_newsmap_items,
    items_to_frame,
)
from src.ingestion.signal_derivation import derive_anomaly_block, emit_weekly_signals, to_weekly
from src.ingestion.wahis_mapping import map_country_iso3, map_disease_code
from src.schemas.enums import DataRealism, EvidenceCluster, SignalFamily, SourceTier, SourceType
from src.utils.config import load_countries, load_diseases
from src.utils.io import read_csv, write_csv
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["EIOSAdapter"]


class EIOSAdapter(SourceAdapter):
    """Board-item / article signals from EIOS (export, newsmap, or mock)."""

    source_name = "EIOS"
    source_type = SourceType.AGGREGATOR
    source_tier = SourceTier.INTELLIGENCE
    evidence_cluster = EvidenceCluster.AGGREGATOR
    reliability = 0.55
    sample_filename = "eios_board_items_mock.csv"
    sample_realism = DataRealism.MOCK
    ingestion_lag_days = 1
    licence = "Public newsmap content via WHO/JRC EIOS tagging; full portal exports remain restricted"
    homepage = "https://portal.who.int/pandemichub/newsmap/"
    live_env_var = "EIOS_EXPORT_DIR"  # optional override of data/raw/eios

    def load_raw(self) -> pd.DataFrame:
        mode = self.config.data_mode
        if mode in {"pilot", "offline", "live"}:
            path = self._resolve_offline_path()
            if path is not None:
                LOGGER.info("%s: loading offline portal export %s", self.source_name, path.name)
                if path.suffix.lower() in {".xlsx", ".xls"}:
                    frame = pd.read_excel(path)
                else:
                    frame = read_csv(path)
                return self._normalise_export(frame)

            cache = self._cache_path()
            refresh = str(self.config.get("sources.eios.refresh", "false")).lower() in {
                "1",
                "true",
                "yes",
            }
            if cache.is_file() and not refresh:
                LOGGER.info("%s: loading newsmap cache %s", self.source_name, cache.name)
                return read_csv(cache)

            try:
                frame = self.fetch_live()
            except Exception as exc:  # noqa: BLE001
                if cache.is_file():
                    LOGGER.warning(
                        "%s: newsmap fetch failed (%s); falling back to cache %s",
                        self.source_name,
                        exc,
                        cache.name,
                    )
                    return read_csv(cache)
                LOGGER.warning(
                    "%s: newsmap unavailable (%s) and no portal export — using MOCK corpus. "
                    "See docs/EIOS_BEACON_ACCESS.md.",
                    self.source_name,
                    exc,
                )
                return super().load_raw()

            cache.parent.mkdir(parents=True, exist_ok=True)
            write_csv(frame, cache)
            LOGGER.info("%s: wrote newsmap cache %s (%s rows)", self.source_name, cache, len(frame))
            return frame
        return super().load_raw()

    def fetch_live(self) -> pd.DataFrame:
        import os

        # Prefer an explicit portal export if present.
        path = self._resolve_offline_path()
        if path is not None:
            if path.suffix.lower() in {".xlsx", ".xls"}:
                return self._normalise_export(pd.read_excel(path))
            return self._normalise_export(read_csv(path))

        api_base = (
            os.environ.get("EIOS_NEWSMAP_BASE", "")
            or str(self.config.get("sources.eios.newsmap_base", EIOS_NEWSMAP_BASE))
            or EIOS_NEWSMAP_BASE
        )
        rows = int(self.config.get("sources.eios.newsmap_rows", 100))
        LOGGER.info(
            "%s: fetching public WHO newsmap %s/tunnel (recent EIOS-tagged news)",
            self.source_name,
            api_base.rstrip("/"),
        )
        articles = fetch_newsmap_items(
            disease_categories=EIOS_NEWSMAP_CATEGORIES,
            rows_per_category=rows,
            api_base=api_base,
        )
        frame = items_to_frame(articles)
        if frame.empty:
            raise LiveSourceUnavailable(
                f"{self.source_name}: newsmap returned no panel-mapped HPAI/ASF items."
            )
        return frame

    def _cache_path(self) -> Path:
        return self.config.path("data_raw") / "eios" / "eios_newsmap_panel.csv"

    def _resolve_offline_path(self) -> Path | None:
        import os

        env_dir = os.environ.get(self.live_env_var or "")
        candidates: list[Path] = []
        if env_dir:
            candidates.append(Path(env_dir))
        raw = self.config.path("data_raw")
        eios_dir = raw / "eios"
        if eios_dir.is_dir():
            # Prefer explicit portal exports over the newsmap cache file.
            for pattern in ("*.csv", "*.xlsx"):
                for path in sorted(eios_dir.glob(pattern)):
                    if path.name.lower() == "eios_newsmap_panel.csv":
                        continue
                    if path.name.lower() == "readme.md":
                        continue
                    candidates.append(path)
        candidates.extend(sorted(raw.glob("eios*.csv")))
        candidates.extend(sorted(raw.glob("eios*.xlsx")))
        files = [
            p
            for p in candidates
            if p.is_file() and p.name.lower() not in {"eios_newsmap_panel.csv", "readme.md"}
        ]
        return files[0] if files else None

    def _normalise_export(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Map common EIOS export column names onto the adapter schema."""
        if raw.empty:
            return raw
        # Already-normalised newsmap / prior cache
        if {"item_id", "iso3", "disease_code", "first_seen_date"}.issubset(raw.columns):
            frame = raw.copy()
            if "data_realism" not in frame.columns:
                frame["data_realism"] = "real"
            return frame

        colmap = {c.lower().strip(): c for c in raw.columns}

        def pick(*names: str) -> str | None:
            for name in names:
                if name.lower() in colmap:
                    return colmap[name.lower()]
            return None

        country_col = pick("country", "country_name", "location", "geo", "countries")
        disease_col = pick("disease", "disease_name", "category", "threat", "diseases")
        date_col = pick(
            "first_seen_date",
            "publication_date",
            "published",
            "date",
            "article_date",
            "information_date",
            "created",
        )
        id_col = pick("item_id", "article_id", "id", "uid", "document_id")
        rel_col = pick("relevance", "score", "relevance_score")
        triage_col = pick("triage_state", "status", "triage", "state")
        cluster_col = pick("n_articles_in_cluster", "cluster_size", "articles", "n_articles")

        rows: list[dict] = []
        for i, row in enumerate(raw.to_dict(orient="records")):
            country_raw = row.get(country_col) if country_col else None
            disease_raw = row.get(disease_col) if disease_col else None
            if country_raw is not None and ";" in str(country_raw):
                country_raw = str(country_raw).split(";")[0].strip()
            if country_raw is not None and "," in str(country_raw):
                country_raw = str(country_raw).split(",")[0].strip()
            iso3 = map_country_iso3(str(country_raw) if country_raw is not None else None)
            disease = map_disease_code(str(disease_raw) if disease_raw is not None else None)
            if disease is None and disease_raw is not None:
                text = str(disease_raw).lower()
                if "african swine" in text or text.strip() == "asf":
                    disease = "ASF"
                elif "avian influenza" in text or "hpai" in text or "bird flu" in text:
                    disease = "HPAI"
            if iso3 is None or disease is None:
                continue
            date_val = row.get(date_col) if date_col else None
            item_id = row.get(id_col) if id_col else f"EIOS-{i}"
            relevance = row.get(rel_col) if rel_col else 0.5
            triage = row.get(triage_col) if triage_col else "retained"
            n_cluster = row.get(cluster_col) if cluster_col else 1
            rows.append(
                {
                    "item_id": str(item_id),
                    "first_seen_date": date_val,
                    "iso3": iso3,
                    "disease_code": disease,
                    "relevance": relevance,
                    "triage_state": triage,
                    "n_articles_in_cluster": n_cluster,
                    "data_realism": "real",
                }
            )
        frame = pd.DataFrame(rows)
        LOGGER.info("%s: normalised %s rows from export (%s raw)", self.source_name, len(frame), len(raw))
        return frame

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries, diseases = load_countries(), load_diseases()
        output = AdapterOutput(source_name=self.source_name)

        is_real = (
            "data_realism" in raw.columns
            and raw["data_realism"].astype(str).str.lower().eq("real").any()
        )
        if is_real:
            output.notes.append(
                "EIOS records are REAL (portal export and/or public WHO newsmap). "
                "Newsmap items are recent open-source articles with EIOS tags — "
                "not a full historical community-portal extract."
            )
        else:
            output.notes.append(
                "EIOS records in this build are MOCK. Prefer the public newsmap "
                "(`python scripts/fetch_eios_newsmap.py`) or a portal export under "
                "data/raw/eios/ (see docs/EIOS_BEACON_ACCESS.md)."
            )

        frame = raw.copy()
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame["disease_code"] = frame["disease_code"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries) & frame["disease_code"].isin(diseases)]
        if frame.empty:
            output.notes.append("No EIOS rows matched the configured panel.")
            return output

        frame["relevance"] = pd.to_numeric(frame["relevance"], errors="coerce").fillna(0.0)
        frame["n_articles_in_cluster"] = pd.to_numeric(
            frame["n_articles_in_cluster"], errors="coerce"
        ).fillna(0.0)
        frame["not_dismissed"] = ~frame["triage_state"].astype(str).str.lower().eq("dismissed")
        frame["effective_cluster"] = frame["n_articles_in_cluster"] * frame["not_dismissed"].astype(float)

        weekly = to_weekly(
            frame,
            date_col="first_seen_date",
            group_cols=["iso3", "disease_code"],
            agg={
                "item_id": "count",
                "effective_cluster": "sum",
                "relevance": "mean",
                "not_dismissed": "sum",
            },
        ).rename(columns={"item_id": "n_items", "not_dismissed": "n_retained"})

        weekly = derive_anomaly_block(
            weekly,
            group_cols=["iso3", "disease_code"],
            value_col="effective_cluster",
            prefix="eios",
            alpha=float(self.config.get("features.ewma_alpha", 0.30)),
        )
        weekly["eios_retained_items"] = weekly["n_retained"].astype(float)
        weekly["eios_mean_relevance"] = weekly["relevance"]

        note = (
            "Real EIOS-tagged news (portal export and/or WHO newsmap)."
            if is_real
            else "MOCK DATA - interface demonstration only, not a WHO EIOS extract."
        )
        signals, provenance = emit_weekly_signals(
            self,
            weekly,
            signal_columns=[
                ("eios_abnormal_volume", "z-score"),
                ("eios_retained_items", "count"),
                ("eios_mean_relevance", "score"),
            ],
            family=SignalFamily.INTELLIGENCE,
            denominator_col="n_items",
            query_template="eios:newsmap/tunnel?country={iso3}&disease={disease}",
            note=note,
        )
        if is_real:
            for prov in provenance:
                prov.realism = DataRealism.REAL
        output.signals.extend(signals)
        output.provenance.extend(provenance)
        return output
