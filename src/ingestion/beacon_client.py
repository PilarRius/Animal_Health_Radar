"""Public BEACON API client (no key required).

Base: ``https://api.beaconbio.org``

Endpoints used
--------------
* ``GET /public/filter`` — disease / pathogen / location catalogues
* ``GET /public/report?page=&limit=&diseases=`` — paginated curated reports
* ``GET /public/report/{id}`` — full report (optional detail)

This is the same public API the website at https://beaconbio.org calls.
"""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
import requests

from src.ingestion.wahis_mapping import map_country_iso3, map_disease_code
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = [
    "BEACON_API_BASE",
    "BEACON_DISEASE_IDS",
    "fetch_beacon_reports",
    "reports_to_signal_frame",
]

BEACON_API_BASE = "https://api.beaconbio.org"

# Stable catalogue IDs from GET /public/filter (as of 2026-10).
BEACON_DISEASE_IDS: dict[str, str] = {
    "ASF": "5fe4d6f3-94fd-4208-9111-c8fb203e82e4",  # African swine fever
    "HPAI": "a50d3bd3-769b-4963-8d9b-0bd5ef853335",  # Highly pathogenic avian influenza
    "AI": "0c99bca8-0fc4-4d91-80ec-b345ec1dcf50",  # Avian influenza (bird flu)
}

_ISO2_TO_ISO3: dict[str, str] = {
    "FR": "FRA",
    "DE": "DEU",
    "NL": "NLD",
    "BE": "BEL",
    "IT": "ITA",
    "ES": "ESP",
    "PL": "POL",
    "HU": "HUN",
    "RO": "ROU",
    "BG": "BGR",
    "RS": "SRB",
    "UA": "UKR",
    "MD": "MDA",
    "RU": "RUS",
    "TR": "TUR",
    "GE": "GEO",
    "IL": "ISR",
    "EG": "EGY",
    "TN": "TUN",
    "MA": "MAR",
}


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "AnimalHealthRadar/0.1 (WOAH Datathon; offline research pipeline)",
            "Accept": "application/json",
            "Origin": "https://beaconbio.org",
            "Referer": "https://beaconbio.org/",
        }
    )
    return session


def fetch_beacon_reports(
    *,
    disease_ids: Iterable[str] | None = None,
    page_size: int = 100,
    max_pages: int | None = None,
    api_base: str = BEACON_API_BASE,
) -> list[dict[str, Any]]:
    """Download curated BEACON reports for the given disease catalogue IDs."""
    ids = list(disease_ids or BEACON_DISEASE_IDS.values())
    session = _session()
    rows: list[dict[str, Any]] = []
    page = 0
    while True:
        if max_pages is not None and page >= max_pages:
            break
        params: list[tuple[str, str | int]] = [("page", page), ("limit", page_size)]
        for disease_id in ids:
            params.append(("diseases", disease_id))
        response = session.get(f"{api_base.rstrip('/')}/public/report", params=params, timeout=90)
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("data") or []
        total_pages = int(payload.get("totalPages") or 0)
        total_items = int(payload.get("totalItems") or 0)
        LOGGER.info(
            "BEACON /public/report page %s/%s — got %s (totalItems=%s)",
            page,
            max(total_pages - 1, 0),
            len(batch),
            total_items,
        )
        if not batch:
            break
        rows.extend(batch)
        page += 1
        if page >= total_pages:
            break
    # Deduplicate by report id (multi-disease queries can overlap AI/HPAI).
    by_id = {str(row["id"]): row for row in rows if row.get("id")}
    LOGGER.info("BEACON fetch complete: %s unique reports", len(by_id))
    return list(by_id.values())


def _disease_from_report(latest: dict[str, Any]) -> str | None:
    disease_list = latest.get("diseaseList") or {}
    processed = disease_list.get("processed") or []
    for name in processed:
        code = map_disease_code(str(name))
        if code:
            return code
        low = str(name).lower()
        if "african swine" in low:
            return "ASF"
        if "highly pathogenic" in low or "avian influenza" in low or "bird flu" in low:
            return "HPAI"
    pathogen_list = latest.get("pathogenList") or {}
    for name in pathogen_list.get("processed") or []:
        code = map_disease_code(str(name))
        if code:
            return code
        low = str(name).lower()
        if "african swine" in low:
            return "ASF"
        if "influenza" in low and "avian" in low:
            return "HPAI"
    title = str(latest.get("title") or "")
    return map_disease_code(title) or (
        "ASF"
        if "african swine" in title.lower()
        else ("HPAI" if "avian influenza" in title.lower() or "hpai" in title.lower() else None)
    )


def _iso3_from_report(report: dict[str, Any], latest: dict[str, Any]) -> str | None:
    # Prefer ISO2 border codes from the map payload.
    border_codes = ((latest.get("map") or {}).get("borders") or [])
    for border in border_codes:
        iso2 = str(border.get("shortCode") or "").upper()
        if iso2 in _ISO2_TO_ISO3:
            return _ISO2_TO_ISO3[iso2]
        mapped = map_country_iso3(border.get("label"))
        if mapped:
            return mapped
    for loc in latest.get("location") or []:
        mapped = map_country_iso3(loc.get("name") if isinstance(loc, dict) else loc)
        if mapped:
            return mapped
    for loc in report.get("locations") or []:
        mapped = map_country_iso3(loc.get("name") if isinstance(loc, dict) else loc)
        if mapped:
            return mapped
    # Title pattern: "..., Spain"
    title = str(latest.get("title") or "")
    if "," in title:
        mapped = map_country_iso3(title.rsplit(",", 1)[-1].strip())
        if mapped:
            return mapped
    return None


def _strength(latest: dict[str, Any]) -> float:
    raw = latest.get("severityScore")
    try:
        if raw is not None and str(raw).strip() != "":
            value = float(raw)
            if value > 1.0:
                value = value / 10.0
            return float(max(0.05, min(value, 1.0)))
    except (TypeError, ValueError):
        pass
    # Curated BEACON reports are already triaged — default mid-high strength.
    return 0.65


def _verified(latest: dict[str, Any]) -> str:
    pins = ((latest.get("map") or {}).get("pins") or [])
    if any(bool(pin.get("isVerified")) for pin in pins if isinstance(pin, dict)):
        return "verified"
    reliability = str(latest.get("mediaReliability") or "").lower()
    if reliability in {"high", "verified", "confirmed"}:
        return "verified"
    return "unverified"


def reports_to_signal_frame(reports: list[dict[str, Any]]) -> pd.DataFrame:
    """Flatten BEACON JSON reports into the adapter's tabular signal schema."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    for report in reports:
        latest = report.get("latestVersion") or {}
        disease = _disease_from_report(latest)
        iso3 = _iso3_from_report(report, latest)
        if disease is None or iso3 is None:
            skipped += 1
            continue
        published = report.get("publishedAt") or latest.get("createdAt") or latest.get("eventDate")
        event_date = latest.get("eventDate") or published
        sources = latest.get("sources") or []
        underlying = "media"
        if sources:
            joined = " ".join(str(s) for s in sources).lower()
            if "woah" in joined or "wahis" in joined or "ministry" in joined or "gov" in joined:
                underlying = "media;official"
        rows.append(
            {
                "signal_id": f"BEACON-{report.get('id')}",
                "report_id": str(report.get("id")),
                "detected_date": pd.to_datetime(event_date, utc=True, errors="coerce"),
                "screened_date": pd.to_datetime(published, utc=True, errors="coerce"),
                "iso3": iso3,
                "disease_code": disease,
                "signal_strength": _strength(latest),
                "verification_status": _verified(latest),
                "signal_type": "beacon_report",
                "underlying_sources": underlying,
                "title": latest.get("title") or "",
                "data_realism": "real",
                "url": f"https://beaconbio.org/en/report/?reportid={report.get('id')}",
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["detected_date"] = frame["detected_date"].dt.tz_localize(None)
        frame["screened_date"] = frame["screened_date"].dt.tz_localize(None)
    LOGGER.info(
        "BEACON normalised %s panel signals (%s reports skipped: outside disease/country panel)",
        len(frame),
        skipped,
    )
    return frame
