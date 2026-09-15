"""Country name and code resolution.

Sources disagree about country naming in entirely predictable ways ("Turkey" /
"Türkiye" / "Turkiye", "Russia" / "Russian Federation", "Moldova" / "Republic
of Moldova"). Left unresolved these become silent data loss: the records exist
but attach to no entity and quietly vanish from every count.

The resolver is deliberately conservative. It matches on an explicit alias
table and a normalised string form, and it *reports* what it could not resolve
rather than guessing with fuzzy string distance.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache

from src.utils.config import load_countries
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["normalise_country", "resolve_iso3", "unresolved_report"]

#: Aliases beyond the canonical names in ``config/countries.yaml``.
_ALIASES: dict[str, str] = {
    "turkey": "TUR",
    "turkiye": "TUR",
    "republic of turkiye": "TUR",
    "russia": "RUS",
    "russian federation": "RUS",
    "republic of moldova": "MDA",
    "moldova republic of": "MDA",
    "the netherlands": "NLD",
    "holland": "NLD",
    "kingdom of the netherlands": "NLD",
    "republic of serbia": "SRB",
    "state of israel": "ISR",
    "arab republic of egypt": "EGY",
    "kingdom of morocco": "MAR",
    "republic of tunisia": "TUN",
    "czechia": "CZE",
    "united kingdom": "GBR",
    "great britain": "GBR",
    "deutschland": "DEU",
    "espana": "ESP",
    "france metropolitaine": "FRA",
    "italia": "ITA",
    "polska": "POL",
    "magyarorszag": "HUN",
    "romania": "ROU",
    "bulgaria": "BGR",
    "ukraine": "UKR",
    "georgia": "GEO",
    "belgique": "BEL",
    "belgie": "BEL",
}

_UNRESOLVED: dict[str, int] = {}


def normalise_country(text: str) -> str:
    """Casefold, strip accents and collapse punctuation for matching."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in ascii_text)
    return " ".join(cleaned.lower().split())


@lru_cache(maxsize=4096)
def _lookup_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for iso3, spec in load_countries().items():
        table[normalise_country(iso3)] = iso3
        table[normalise_country(spec.name)] = iso3
    table.update(_ALIASES)
    return table


def resolve_iso3(value: str | None, *, strict: bool = False) -> str | None:
    """Map a country name or code onto a panel ISO3 code.

    Returns ``None`` for anything outside the configured panel, recording the
    miss so that :func:`unresolved_report` can surface it at the end of a run.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    candidate = raw.upper()
    countries = load_countries()
    if candidate in countries:
        return candidate

    resolved = _lookup_table().get(normalise_country(raw))
    if resolved in countries:
        return resolved

    _UNRESOLVED[raw] = _UNRESOLVED.get(raw, 0) + 1
    if strict:
        raise KeyError(f"Country {raw!r} is not in the configured panel.")
    return None


def unresolved_report() -> dict[str, int]:
    """Names seen during this process that could not be mapped, with counts."""
    return dict(sorted(_UNRESOLVED.items(), key=lambda item: -item[1]))
