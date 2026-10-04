"""Public WHO Pandemic Hub newsmap client (EIOS-tagged open news).

Portal: ``https://portal.who.int/pandemichub/newsmap/``

This is **not** the restricted EIOS community portal. It is the public
WHO/JRC news map that surfaces recent open-source articles already tagged
with EIOS category IDs. Useful as a real recent intelligence feed; it does
**not** replace a full historical EIOS board export.

Endpoints
---------
* ``GET .../tunnel?sid=&info=true&version=9.5`` — category catalogue
* ``GET .../tunnel?sid=&category=&langs=&rows=`` — recent items for a category
* ``GET .../tunnel?sid=&guids=a,b,c`` — article titles / links for guids
"""

from __future__ import annotations

import time
from typing import Any, Iterable

import pandas as pd
import requests

from src.ingestion.wahis_mapping import map_country_iso3
from src.utils.config import load_countries
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = [
    "EIOS_NEWSMAP_BASE",
    "EIOS_NEWSMAP_CATEGORIES",
    "fetch_newsmap_items",
    "items_to_frame",
]

EIOS_NEWSMAP_BASE = "https://portal.who.int/pandemichub/newsmap"

# Public newsmap category IDs relevant to the HPAI / ASF pilot panel.
EIOS_NEWSMAP_CATEGORIES: dict[str, list[str]] = {
    "HPAI": [
        "Avianflu",
        "H5N1",
        "H5N6",
        "H5N8",
        "InfluenzaHXNXAnimal",
        "InfluenzaHumanAnimalInterface",
    ],
    "ASF": [
        "SwineFever",
        "PigDisease",
    ],
}

_PANEL_NAME_HINTS: dict[str, str] = {
    "france": "FRA",
    "germany": "DEU",
    "netherlands": "NLD",
    "belgium": "BEL",
    "italy": "ITA",
    "spain": "ESP",
    "poland": "POL",
    "hungary": "HUN",
    "romania": "ROU",
    "bulgaria": "BGR",
    "serbia": "SRB",
    "ukraine": "UKR",
    "moldova": "MDA",
    "russia": "RUS",
    "russianfederation": "RUS",
    "turkey": "TUR",
    "turkiye": "TUR",
    "georgia": "GEO",
    "israel": "ISR",
    "egypt": "EGY",
    "tunisia": "TUN",
    "morocco": "MAR",
    "unitedkingdom": "GBR",  # not in panel; kept for mapping completeness
}


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "AnimalHealthRadar/0.1 (WOAH Datathon; offline research pipeline)",
            "Accept": "application/json",
            "Referer": f"{EIOS_NEWSMAP_BASE}/",
        }
    )
    return session


def _iso3_from_category_ids(category_ids: Iterable[str]) -> str | None:
    for raw in category_ids:
        text = str(raw or "").strip()
        if not text or text.startswith("EIOS.") or text.startswith("PAHO"):
            continue
        # Compact forms used by the newsmap (UnitedKingdom, RussianFederation)
        compact = text.replace(" ", "").replace("_", "").lower()
        if compact in _PANEL_NAME_HINTS:
            return _PANEL_NAME_HINTS[compact]
        mapped = map_country_iso3(text)
        if mapped:
            return mapped
        # Split CamelCase: UnitedKingdom -> United Kingdom
        spaced = "".join(f" {ch}" if ch.isupper() else ch for ch in text).strip()
        mapped = map_country_iso3(spaced)
        if mapped:
            return mapped
    return None


def _disease_from_categories(disease_code: str | None, category_ids: Iterable[str]) -> str | None:
    if disease_code in {"HPAI", "ASF"}:
        return disease_code
    joined = " ".join(str(c) for c in category_ids).lower()
    if "swinefever" in joined or "pigdisease" in joined or "africanswine" in joined:
        return "ASF"
    if any(
        tok in joined
        for tok in (
            "avianflu",
            "h5n1",
            "h5n6",
            "h5n8",
            "h7n",
            "influenzahxnxanimal",
            "influenzaHumanAnimalInterface".lower(),
            "lowpathogenicavian",
            "birdflu",
        )
    ):
        return "HPAI"
    return None


def fetch_newsmap_items(
    *,
    disease_categories: dict[str, list[str]] | None = None,
    rows_per_category: int = 100,
    langs: str = "en,fr,es,de,it,nl,ar,ru,zh",
    api_base: str = EIOS_NEWSMAP_BASE,
    sleep_s: float = 0.1,
    enrich_details: bool = True,
) -> list[dict[str, Any]]:
    """Download recent newsmap items for the configured disease categories."""
    categories = disease_categories or EIOS_NEWSMAP_CATEGORIES
    session = _session()
    base = api_base.rstrip("/")
    sid = f"ahr-{int(time.time() * 1000)}"
    by_guid: dict[str, dict[str, Any]] = {}

    # Warm the session / confirm catalogue is reachable.
    info = session.get(
        f"{base}/tunnel",
        params={"sid": sid, "info": "true", "version": "9.5"},
        timeout=60,
    )
    info.raise_for_status()
    LOGGER.info(
        "EIOS newsmap catalogue ok (cacheVersion=%s)",
        (info.json() or {}).get("cacheVersion"),
    )

    for disease_code, cats in categories.items():
        for category in cats:
            response = session.get(
                f"{base}/tunnel",
                params={
                    "sid": sid,
                    "category": category,
                    "langs": langs,
                    "rows": rows_per_category,
                },
                timeout=90,
            )
            if response.status_code == 404:
                LOGGER.warning("EIOS newsmap category missing: %s", category)
                continue
            response.raise_for_status()
            payload = response.json() or {}
            items = payload.get("items") or []
            LOGGER.info(
                "EIOS newsmap %s/%s — %s items (totalCount=%s)",
                disease_code,
                category,
                len(items),
                payload.get("totalCount"),
            )
            for item in items:
                guid = str(item.get("guid") or "")
                if not guid:
                    continue
                row = dict(item)
                row["_ahr_disease_code"] = disease_code
                row["_ahr_category"] = category
                # Prefer keeping first disease assignment when categories overlap.
                by_guid.setdefault(guid, row)
            if sleep_s:
                time.sleep(sleep_s)

    articles = list(by_guid.values())
    if enrich_details and articles:
        # Batch guid lookups for titles / links.
        guids = [str(a["guid"]) for a in articles]
        details: dict[str, dict[str, Any]] = {}
        batch_size = 25
        for i in range(0, len(guids), batch_size):
            batch = guids[i : i + batch_size]
            response = session.get(
                f"{base}/tunnel",
                params={"sid": sid, "guids": ",".join(batch)},
                timeout=90,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                for detail in payload:
                    if isinstance(detail, dict) and detail.get("guid"):
                        details[str(detail["guid"])] = detail
            elif isinstance(payload, dict):
                for key, detail in payload.items():
                    if isinstance(detail, dict):
                        details[str(detail.get("guid") or key)] = detail
            if sleep_s:
                time.sleep(sleep_s)
        for article in articles:
            detail = details.get(str(article.get("guid")))
            if detail:
                article["_detail"] = detail

    LOGGER.info("EIOS newsmap fetch complete: %s unique items", len(articles))
    return articles


def items_to_frame(articles: list[dict[str, Any]]) -> pd.DataFrame:
    """Flatten newsmap items into the EIOS adapter tabular schema."""
    panel = set(load_countries().keys())
    rows: list[dict[str, Any]] = []
    skipped = 0
    for article in articles:
        category_ids = [str(c) for c in (article.get("categoryIds") or [])]
        detail = article.get("_detail") or {}
        if detail.get("categories"):
            category_ids.extend(str(c.get("id") or c.get("name") or "") for c in detail["categories"])
        disease = _disease_from_categories(article.get("_ahr_disease_code"), category_ids)
        iso3 = _iso3_from_category_ids(category_ids)
        if iso3 is None:
            # Fall back to media-source country only when no event country tag exists.
            src = article.get("source") or detail.get("source") or {}
            iso3 = map_country_iso3(src.get("country")) if isinstance(src, dict) else None
        if disease is None or iso3 is None or iso3 not in panel:
            skipped += 1
            continue
        title = detail.get("enTitle") or detail.get("title") or ""
        relevance = 0.55
        # Category scores when present
        for cat in detail.get("categories") or []:
            try:
                score = float(cat.get("score") or 0.0)
                if score > 0:
                    relevance = max(relevance, min(score / 500.0, 1.0))
            except (TypeError, ValueError):
                continue
        rows.append(
            {
                "item_id": f"EIOS-NM-{article.get('guid')}",
                "board": "WHO Pandemic Hub newsmap",
                "first_seen_date": pd.to_datetime(article.get("pubDate"), utc=True, errors="coerce"),
                "iso3": iso3,
                "country": iso3,
                "disease_code": disease,
                "n_articles_in_cluster": 1,
                "relevance": relevance,
                "triage_state": "retained",
                "title": str(title)[:500],
                "url": str(detail.get("link") or "")[:500],
                "language": str(article.get("language") or detail.get("language") or "")[:8],
                "source_category": article.get("_ahr_category") or "",
                "data_realism": "real",
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["first_seen_date"] = frame["first_seen_date"].dt.tz_localize(None)
    LOGGER.info(
        "EIOS newsmap normalised %s panel items (%s skipped: missing disease/country)",
        len(frame),
        skipped,
    )
    return frame
