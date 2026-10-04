"""Public PADI-web articles API client (no key for the free limited tier).

Base: ``https://padi-web.cirad.fr``

Endpoint used
-------------
* ``GET /en/articles/api/?page=&per_page=&source_category=&country=&published_after=&general_labels_per_task[Relevance]=1&is_archived=0&ordering=-published_at``

This is the same JSON API the public SPA at https://padi-web.cirad.fr calls.
CSV/XLSX bulk export in the UI requires a signed-in account with export
permissions; the paginated JSON listing does not.
"""

from __future__ import annotations

import time
from typing import Any, Iterable
from urllib.parse import urlencode

import pandas as pd
import requests

from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = [
    "PADIWEB_API_BASE",
    "PADIWEB_SOURCE_CATEGORIES",
    "ISO3_TO_ISO2",
    "fetch_padiweb_articles",
    "articles_to_frame",
]

PADIWEB_API_BASE = "https://padi-web.cirad.fr"

# RSS source_category values from GET /en/articles/list-source-categories/
PADIWEB_SOURCE_CATEGORIES: dict[str, list[str]] = {
    "HPAI": [
        "Avian Influenza",
        "Avian Influenza Press Releases",
        "Official AI press releases",
    ],
    "ASF": [
        "African Swine Fever",
    ],
}

# Panel ISO3 → ISO2 used by PADI-web's ``country`` filter.
ISO3_TO_ISO2: dict[str, str] = {
    "FRA": "FR",
    "DEU": "DE",
    "NLD": "NL",
    "BEL": "BE",
    "ITA": "IT",
    "ESP": "ES",
    "POL": "PL",
    "HUN": "HU",
    "ROU": "RO",
    "BGR": "BG",
    "SRB": "RS",
    "UKR": "UA",
    "MDA": "MD",
    "RUS": "RU",
    "TUR": "TR",
    "GEO": "GE",
    "ISR": "IL",
    "EGY": "EG",
    "TUN": "TN",
    "MAR": "MA",
}

_ISO2_TO_ISO3 = {v: k for k, v in ISO3_TO_ISO2.items()}

_OUTBREAK_LABELS = {
    "outbreak declaration",
    "consequences",
    "alert, prepardness",
    "alert, preparedness",
}


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "AnimalHealthRadar/0.1 (WOAH Datathon; offline research pipeline)",
            "Accept": "application/json",
            "Referer": "https://padi-web.cirad.fr/en/articles/",
        }
    )
    return session


def _category_to_disease(category: str | None) -> str | None:
    text = str(category or "").strip().lower()
    if not text:
        return None
    if "african swine" in text:
        return "ASF"
    if "avian influenza" in text or text in {"official ai press releases", "ai"}:
        return "HPAI"
    return None


def _relevance_score(labels: list[dict[str, Any]] | None) -> float:
    names = {str(lab.get("name") or "").strip().lower() for lab in (labels or [])}
    if "relevant" in names:
        return 0.85
    if "irrelevant" in names:
        return 0.15
    return 0.50


def _is_epidemiological_event(labels: list[dict[str, Any]] | None) -> bool:
    names = {str(lab.get("name") or "").strip().lower() for lab in (labels or [])}
    if names & _OUTBREAK_LABELS:
        return True
    return "relevant" in names


def fetch_padiweb_articles(
    *,
    disease_categories: dict[str, list[str]] | None = None,
    iso3_countries: Iterable[str] | None = None,
    published_after: str = "2021-01-01",
    published_before: str | None = None,
    relevant_only: bool = True,
    page_size: int = 200,
    max_pages_per_query: int | None = None,
    api_base: str = PADIWEB_API_BASE,
    sleep_s: float = 0.15,
) -> list[dict[str, Any]]:
    """Download PADI-web articles for panel diseases × countries.

    Queries are scoped by ``source_category`` + ISO2 ``country`` so we do not
    pull the global corpus. Results are deduplicated by article id.
    """
    categories = disease_categories or PADIWEB_SOURCE_CATEGORIES
    iso3_list = [str(c).upper() for c in (iso3_countries or ISO3_TO_ISO2.keys())]
    session = _session()
    base = api_base.rstrip("/")
    by_id: dict[str, dict[str, Any]] = {}

    queries: list[tuple[str, str, str]] = []  # disease_code, category, iso2
    for disease_code, cats in categories.items():
        for category in cats:
            for iso3 in iso3_list:
                iso2 = ISO3_TO_ISO2.get(iso3)
                if not iso2:
                    continue
                queries.append((disease_code, category, iso2))

    LOGGER.info(
        "PADI-web fetch: %s category×country queries (published_after=%s)",
        len(queries),
        published_after,
    )

    for qi, (disease_code, category, iso2) in enumerate(queries, start=1):
        page = 1
        while True:
            if max_pages_per_query is not None and page > max_pages_per_query:
                break
            params: dict[str, Any] = {
                "page": page,
                "per_page": page_size,
                "source_category": category,
                "country": iso2,
                "published_after": published_after,
                "is_archived": 0,
                "ordering": "-published_at",
            }
            if published_before:
                params["published_before"] = published_before
            if relevant_only:
                params["general_labels_per_task[Relevance]"] = 1
            url = f"{base}/en/articles/api/?{urlencode(params)}"
            response = session.get(url, timeout=90)
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("results") or []
            count = int(payload.get("count") or 0)
            LOGGER.info(
                "PADI-web [%s/%s] %s / %s page %s — got %s (count=%s)",
                qi,
                len(queries),
                disease_code,
                iso2,
                page,
                len(batch),
                count,
            )
            if not batch:
                break
            for article in batch:
                aid = str(article.get("id") or "")
                if not aid:
                    continue
                # Prefer explicit disease from the query category over rssfeed noise.
                article = dict(article)
                article["_ahr_disease_code"] = disease_code
                article["_ahr_source_category"] = category
                by_id[aid] = article
            if not payload.get("next"):
                break
            page += 1
            if sleep_s:
                time.sleep(sleep_s)
        if sleep_s:
            time.sleep(sleep_s)

    LOGGER.info("PADI-web fetch complete: %s unique articles", len(by_id))
    return list(by_id.values())


def articles_to_frame(articles: list[dict[str, Any]]) -> pd.DataFrame:
    """Flatten PADI-web JSON articles into the adapter's tabular schema."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    for article in articles:
        labels = article.get("machine_classification_labels") or []
        disease = article.get("_ahr_disease_code") or _category_to_disease(
            (article.get("rssfeed") or {}).get("source_category")
            or article.get("_ahr_source_category")
        )
        iso2 = str(article.get("country") or "").upper()
        iso3 = _ISO2_TO_ISO3.get(iso2)
        if disease is None or iso3 is None:
            skipped += 1
            continue
        published = article.get("published_at") or article.get("created_at")
        extracted = article.get("created_at") or published
        category = (
            article.get("_ahr_source_category")
            or (article.get("rssfeed") or {}).get("source_category")
            or disease
        )
        rows.append(
            {
                "article_id": f"PADI-{article.get('id')}",
                "published_date": pd.to_datetime(published, utc=True, errors="coerce"),
                "extracted_date": pd.to_datetime(extracted, utc=True, errors="coerce"),
                "iso3": iso3,
                "country": iso3,
                "disease_code": disease,
                "disease_mention": category,
                "relevance_score": _relevance_score(labels),
                "is_epidemiological_event": _is_epidemiological_event(labels),
                "host_mention": "",
                "language": str(article.get("lang") or article.get("source_lang") or "en").lower()[:8],
                "source_outlet": str(article.get("source") or "")[:120],
                "title": str(article.get("title") or "")[:500],
                "url": str(article.get("url") or ""),
                "data_realism": "real",
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["published_date"] = frame["published_date"].dt.tz_localize(None)
        frame["extracted_date"] = frame["extracted_date"].dt.tz_localize(None)
    LOGGER.info(
        "PADI-web normalised %s panel articles (%s skipped: missing disease/country)",
        len(frame),
        skipped,
    )
    return frame
