"""Disease name resolution.

WAHIS disease labels are long, versioned and punctuated
("Influenza A viruses of high pathogenicity (Inf. with) (non-poultry including
wild birds)"), media sources use colloquial terms ("bird flu", "swine fever"),
and aggregators use their own taxonomies. All of them must land on the same
code or the entity key is wrong and every count downstream is wrong with it.

Matching is by explicit alias first, then by keyword patterns that must *all*
be present. Ambiguous strings resolve to ``None`` and are reported, never
guessed: mis-assigning ASF to HPAI would be far worse than dropping a record.
"""

from __future__ import annotations

import re
from functools import lru_cache

from src.normalization.country_codes import normalise_country
from src.utils.config import load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["resolve_disease", "unresolved_disease_report"]

#: Keyword sets: a string matches a code when EVERY pattern in one of its
#: alternative groups is present.
_PATTERNS: dict[str, list[list[str]]] = {
    "HPAI": [
        [r"\bhpai\b"],
        [r"high pathogenicity", r"influenza"],
        [r"highly pathogenic", r"avian influenza"],
        [r"\bavian influenza\b"],
        [r"\bbird flu\b"],
        [r"\bh5n1\b"],
        [r"\bh5n8\b"],
        [r"\bh5nx\b"],
    ],
    "ASF": [
        [r"\basf\b"],
        [r"african swine fever"],
        [r"peste porcine africaine"],
        [r"peste porcina africana"],
    ],
}

#: Strings that look like a match but are a different disease entirely.
_NEGATIVE: dict[str, list[str]] = {
    "HPAI": [r"low pathogenicity", r"\blpai\b"],
    "ASF": [r"classical swine fever", r"\bcsf\b", r"hog cholera"],
}

_UNRESOLVED: dict[str, int] = {}


@lru_cache(maxsize=2048)
def _direct_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for code, spec in load_diseases().items():
        table[normalise_country(code)] = code
        table[normalise_country(spec.name)] = code
        table[normalise_country(spec.wahis_name)] = code
    return table


def resolve_disease(value: str | None, *, strict: bool = False) -> str | None:
    """Map a disease label onto a configured disease code, or ``None``."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    diseases = load_diseases()
    if raw.upper() in diseases:
        return raw.upper()

    normalised = normalise_country(raw)
    direct = _direct_table().get(normalised)
    if direct:
        return direct

    matches: set[str] = set()
    for code, groups in _PATTERNS.items():
        if code not in diseases:
            continue
        if any(re.search(pattern, normalised) for pattern in _NEGATIVE.get(code, [])):
            continue
        if any(all(re.search(pattern, normalised) for pattern in group) for group in groups):
            matches.add(code)

    if len(matches) == 1:
        return matches.pop()

    _UNRESOLVED[raw] = _UNRESOLVED.get(raw, 0) + 1
    if strict:
        reason = "ambiguous" if matches else "unrecognised"
        raise KeyError(f"Disease {raw!r} is {reason} (candidates: {sorted(matches)}).")
    if matches:
        LOGGER.warning("Ambiguous disease label %r matched %s; dropping.", raw, sorted(matches))
    return None


def unresolved_disease_report() -> dict[str, int]:
    """Labels seen during this process that could not be mapped, with counts."""
    return dict(sorted(_UNRESOLVED.items(), key=lambda item: -item[1]))
