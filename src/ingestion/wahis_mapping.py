"""Offline WAHIS INFUR / SMR field mappings (no API).

Maps pilot export disease names and country labels onto the AHR panel codes.
"""

from __future__ import annotations

import re
from functools import lru_cache

from src.utils.config import load_countries, load_diseases

__all__ = [
    "map_disease_code",
    "map_country_iso3",
    "is_hpai_name",
    "is_asf_name",
]

# Explicit aliases for WAHIS export disease strings → AHR codes.
_DISEASE_CONTAINS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"african\s+swine\s+fever", re.I), "ASF"),
    (re.compile(r"high\s+pathogenicity\s+avian\s+influenza", re.I), "HPAI"),
    (re.compile(r"influenza\s+a\s+viruses\s+of\s+high\s+pathogenicity", re.I), "HPAI"),
    (re.compile(r"avian\s+influenza\s+a\s+viruses\s+of\s+high\s+pathogenicity", re.I), "HPAI"),
]

# Country-name aliases beyond countries.yaml `name` fields.
_COUNTRY_ALIASES: dict[str, str] = {
    "russia": "RUS",
    "russian federation": "RUS",
    "turkiye": "TUR",
    "türkiye": "TUR",
    "turkey": "TUR",
    "moldova (rep. of)": "MDA",
    "republic of moldova": "MDA",
    "korea (rep. of)": "KOR",
    "united states of america": "USA",
    "united kingdom": "GBR",
    "bosnia and herzegovina": "BIH",
    "czech republic": "CZE",
    "czechia": "CZE",
    "north macedonia": "MKD",
    "viet nam": "VNM",
    "vietnam": "VNM",
    "iran (islamic rep. of)": "IRN",
    "syria": "SYR",
    "syrian arab republic": "SYR",
}


def is_hpai_name(name: str) -> bool:
    return map_disease_code(name) == "HPAI"


def is_asf_name(name: str) -> bool:
    return map_disease_code(name) == "ASF"


def map_disease_code(raw_name: str | None) -> str | None:
    """Return AHR disease code if the WAHIS disease string is in scope."""
    if raw_name is None:
        return None
    text = str(raw_name).strip()
    if not text:
        return None
    diseases = load_diseases()
    # Exact wahis_name match first
    for code, spec in diseases.items():
        if text.lower() == spec.wahis_name.lower():
            return code
        if text.lower().startswith(spec.wahis_name.lower()):
            return code
    for pattern, code in _DISEASE_CONTAINS:
        if pattern.search(text) and code in diseases:
            return code
    return None


@lru_cache(maxsize=1)
def _name_to_iso() -> dict[str, str]:
    mapping: dict[str, str] = dict(_COUNTRY_ALIASES)
    for iso, spec in load_countries().items():
        mapping[spec.name.lower()] = iso
        mapping[iso.lower()] = iso
    return mapping


def map_country_iso3(country_name: str | None, iso_hint: str | None = None) -> str | None:
    """Map a WAHIS country name (and optional ISO hint) to a panel ISO3."""
    known = set(load_countries())
    if iso_hint:
        hint = str(iso_hint).strip().upper()
        if hint in known:
            return hint
    if country_name is None:
        return None
    key = str(country_name).strip().lower()
    if not key:
        return None
    iso = _name_to_iso().get(key)
    if iso and iso in known:
        return iso
    return None
