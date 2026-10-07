"""Offline WAHIS INFUR / SMR field mappings (no API).

Maps WAHIS export disease names and country labels onto the AHR panel codes.
"""

from __future__ import annotations

import re
import unicodedata
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

# Country-name aliases beyond countries.yaml `name` fields (WAHIS export labels).
_COUNTRY_ALIASES: dict[str, str] = {
    "russia": "RUS",
    "russian federation": "RUS",
    "turkiye": "TUR",
    "türkiye": "TUR",
    "turkey": "TUR",
    "türkiye (rep. of)": "TUR",
    "turkiye (rep. of)": "TUR",
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
    "iran": "IRN",
    "iran (islamic rep. of)": "IRN",
    "syria": "SYR",
    "syrian arab republic": "SYR",
    "china (people's rep. of)": "CHN",
    "chinese taipei": "TWN",
    "congo (dem. rep. of the)": "COD",
    "congo (rep. of the)": "COG",
    "cote d'ivoire": "CIV",
    "dominican (rep.)": "DOM",
    "dominican republic": "DOM",
    "south sudan (rep. of)": "SSD",
    "cabo verde": "CPV",
    "laos": "LAO",
    "tanzania": "TZA",
    "palestine": "PSE",
    "eswatini": "SWZ",
    "swaziland": "SWZ",
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in ascii_text)
    return " ".join(cleaned.lower().split())


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
    mapping: dict[str, str] = {}
    for key, iso in _COUNTRY_ALIASES.items():
        mapping[_fold(key)] = iso
    for iso, spec in load_countries().items():
        mapping[_fold(iso)] = iso
        mapping[_fold(spec.name)] = iso
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
    key = _fold(country_name)
    if not key:
        return None
    iso = _name_to_iso().get(key)
    if iso and iso in known:
        return iso
    return None
