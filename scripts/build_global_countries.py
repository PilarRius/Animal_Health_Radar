"""Build a global ``config/countries.yaml`` from WOAH membership + INFUR coverage.

The panel is no longer limited to the EuFMD 20-country pilot. Official WAHIS
INFUR already covers most of the world; intelligence caches (PADI/BEACON/EIOS)
may still be sparse until re-fetched.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import pycountry
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "TVI"))

from config.woah_regions import ISO3_TO_NAME, ISO3_TO_REGION  # type: ignore  # noqa: E402

# WAHIS INFUR export labels → ISO3 (names that pycountry / WOAH short names miss)
WAHIS_NAME_TO_ISO3: dict[str, str] = {
    "afghanistan": "AFG",
    "albania": "ALB",
    "algeria": "DZA",
    "andorra": "AND",
    "angola": "AGO",
    "argentina": "ARG",
    "armenia": "ARM",
    "australia": "AUS",
    "austria": "AUT",
    "azerbaijan": "AZE",
    "bangladesh": "BGD",
    "belize": "BLZ",
    "benin": "BEN",
    "bhutan": "BTN",
    "bolivia": "BOL",
    "bosnia and herzegovina": "BIH",
    "botswana": "BWA",
    "brazil": "BRA",
    "burkina faso": "BFA",
    "burundi": "BDI",
    "cabo verde": "CPV",
    "cambodia": "KHM",
    "cameroon": "CMR",
    "canada": "CAN",
    "cayman islands": "CYM",
    "chad": "TCD",
    "chile": "CHL",
    "china (people's rep. of)": "CHN",
    "chinese taipei": "TWN",
    "colombia": "COL",
    "comoros": "COM",
    "congo (dem. rep. of the)": "COD",
    "congo (rep. of the)": "COG",
    "costa rica": "CRI",
    "cote d'ivoire": "CIV",
    "croatia": "HRV",
    "cuba": "CUB",
    "cyprus": "CYP",
    "czech republic": "CZE",
    "czechia": "CZE",
    "denmark": "DNK",
    "djibouti": "DJI",
    "dominican (rep.)": "DOM",
    "dominican republic": "DOM",
    "ecuador": "ECU",
    "el salvador": "SLV",
    "eritrea": "ERI",
    "estonia": "EST",
    "eswatini": "SWZ",
    "finland": "FIN",
    "french polynesia": "PYF",
    "gabon": "GAB",
    "gambia": "GMB",
    "ghana": "GHA",
    "greece": "GRC",
    "greenland": "GRL",
    "guadeloupe": "GLP",
    "guatemala": "GTM",
    "guinea": "GIN",
    "guinea-bissau": "GNB",
    "haiti": "HTI",
    "honduras": "HND",
    "hong kong": "HKG",
    "iceland": "ISL",
    "india": "IND",
    "indonesia": "IDN",
    "iran": "IRN",
    "iran (islamic rep. of)": "IRN",
    "iraq": "IRQ",
    "ireland": "IRL",
    "jamaica": "JAM",
    "japan": "JPN",
    "jordan": "JOR",
    "kazakhstan": "KAZ",
    "kenya": "KEN",
    "korea (rep. of)": "KOR",
    "kuwait": "KWT",
    "kyrgyzstan": "KGZ",
    "laos": "LAO",
    "latvia": "LVA",
    "lebanon": "LBN",
    "lesotho": "LSO",
    "liberia": "LBR",
    "libya": "LBY",
    "liechtenstein": "LIE",
    "lithuania": "LTU",
    "luxembourg": "LUX",
    "madagascar": "MDG",
    "malawi": "MWI",
    "malaysia": "MYS",
    "mali": "MLI",
    "malta": "MLT",
    "martinique": "MTQ",
    "mauritania": "MRT",
    "mauritius": "MUS",
    "mayotte": "MYT",
    "mexico": "MEX",
    "mongolia": "MNG",
    "montenegro": "MNE",
    "mozambique": "MOZ",
    "myanmar": "MMR",
    "namibia": "NAM",
    "nepal": "NPL",
    "new caledonia": "NCL",
    "new zealand": "NZL",
    "nicaragua": "NIC",
    "niger": "NER",
    "nigeria": "NGA",
    "north macedonia": "MKD",
    "norway": "NOR",
    "oman": "OMN",
    "pakistan": "PAK",
    "palestine": "PSE",
    "panama": "PAN",
    "papua new guinea": "PNG",
    "paraguay": "PRY",
    "peru": "PER",
    "philippines": "PHL",
    "portugal": "PRT",
    "puerto rico": "PRI",
    "qatar": "QAT",
    "reunion": "REU",
    "rwanda": "RWA",
    "saudi arabia": "SAU",
    "senegal": "SEN",
    "sierra leone": "SLE",
    "singapore": "SGP",
    "slovakia": "SVK",
    "slovenia": "SVN",
    "south africa": "ZAF",
    "south sudan (rep. of)": "SSD",
    "sri lanka": "LKA",
    "st. lucia": "LCA",
    "sudan": "SDN",
    "sweden": "SWE",
    "switzerland": "CHE",
    "tajikistan": "TJK",
    "tanzania": "TZA",
    "thailand": "THA",
    "timor-leste": "TLS",
    "togo": "TGO",
    "trinidad and tobago": "TTO",
    "türkiye (rep. of)": "TUR",
    "turkiye (rep. of)": "TUR",
    "uganda": "UGA",
    "united kingdom": "GBR",
    "united states of america": "USA",
    "uruguay": "URY",
    "venezuela": "VEN",
    "vietnam": "VNM",
    "viet nam": "VNM",
    "zambia": "ZMB",
    "zimbabwe": "ZWE",
    # keep prior pilot aliases
    "russia": "RUS",
    "russian federation": "RUS",
    "turkey": "TUR",
    "turkiye": "TUR",
    "moldova (rep. of)": "MDA",
    "republic of moldova": "MDA",
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
    "georgia": "GEO",
    "israel": "ISR",
    "egypt": "EGY",
    "tunisia": "TUN",
    "morocco": "MAR",
}

# Territories we keep out of the analytical panel (non-sovereign / not useful)
EXCLUDE_ISO3 = {
    "ATA",  # Antarctica
    "HMD",  # Heard and McDonald
    "SGS",  # South Georgia
    "SHN",  # St Helena
    "CYM",  # Cayman
    "GLP",
    "MTQ",
    "MYT",
    "REU",
    "GRL",
    "PRI",
    "PYF",
    "NCL",
    "FRO",  # Faroe
    "FLK",
    "HKG",
}


def _resolve_wahis_name(name: str) -> str | None:
    key = str(name).strip().lower()
    if key in WAHIS_NAME_TO_ISO3:
        return WAHIS_NAME_TO_ISO3[key]
    # pycountry fuzzy
    try:
        hit = pycountry.countries.search_fuzzy(name)[0]
        return hit.alpha_3
    except LookupError:
        return None


def main() -> None:
    infur_path = ROOT / "data" / "raw" / "infur_outbreaks_20260722_080609.csv"
    df = pd.read_csv(
        infur_path,
        usecols=["country", "disease", "latitude", "longitude"],
        low_memory=False,
    )
    # centroids from INFUR
    coords: dict[str, list[tuple[float, float]]] = defaultdict(list)
    infur_iso: set[str] = set()
    unmapped: list[str] = []
    for name, lat, lon in df[["country", "latitude", "longitude"]].itertuples(index=False):
        iso = _resolve_wahis_name(str(name))
        if not iso or iso in EXCLUDE_ISO3:
            if iso is None:
                unmapped.append(str(name))
            continue
        infur_iso.add(iso)
        try:
            la, lo = float(lat), float(lon)
            if la == la and lo == lo and abs(la) <= 90 and abs(lo) <= 180:
                coords[iso].append((la, lo))
        except (TypeError, ValueError):
            pass

    # Panel = WOAH membership list ∪ INFUR-mapped countries (minus excludes)
    panel = sorted((set(ISO3_TO_NAME) | infur_iso) - EXCLUDE_ISO3)

    # Preserve richer livestock/neighbours from previous pilot where present
    old_path = ROOT / "config" / "countries.yaml"
    old_by_iso: dict[str, dict] = {}
    if old_path.exists():
        old = yaml.safe_load(old_path.read_text(encoding="utf-8")) or {}
        for entry in old.get("countries") or []:
            old_by_iso[str(entry["iso3"]).upper()] = entry

    countries: list[dict] = []
    for iso in panel:
        name = ISO3_TO_NAME.get(iso)
        if not name:
            try:
                name = pycountry.countries.get(alpha_3=iso).name
            except Exception:
                name = iso
        region = ISO3_TO_REGION.get(iso, "Unknown")
        old = old_by_iso.get(iso, {})
        if iso in coords:
            lats = [p[0] for p in coords[iso]]
            lons = [p[1] for p in coords[iso]]
            lat = sum(lats) / len(lats)
            lon = sum(lons) / len(lons)
        else:
            centroid = (old.get("centroid") or {})
            lat = float(centroid.get("lat", 0.0) or 0.0)
            lon = float(centroid.get("lon", 0.0) or 0.0)
        countries.append(
            {
                "iso3": iso,
                "name": name,
                "region": region,
                "centroid": {"lat": round(float(lat), 4), "lon": round(float(lon), 4)},
                "area_km2": float(old.get("area_km2", 0) or 0),
                "surveillance_capacity": str(old.get("surveillance_capacity", "medium")),
                "livestock": old.get("livestock") or {},
                "neighbours": old.get("neighbours") or [],
            }
        )

    payload = {
        "countries": countries,
        "enabled": [c["iso3"] for c in countries],
    }

    # Comment header written manually for readability
    header = (
        "# =============================================================================\n"
        "# Global country panel (WOAH members + INFUR-mapped territories)\n"
        "# =============================================================================\n"
        "# Generated by scripts/build_global_countries.py\n"
        "# Official observation (WAHIS INFUR) is global. Intelligence caches\n"
        "# (PADI / BEACON / EIOS) may still be sparse until re-fetched.\n"
        "# Livestock / neighbours are filled where the old pilot had them;\n"
        "# elsewhere they default to empty / medium surveillance capacity.\n"
        "# =============================================================================\n\n"
    )
    out = ROOT / "config" / "countries.yaml"
    out.write_text(
        header + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    uniq_unmapped = sorted(set(unmapped))
    print(f"Wrote {out} with {len(countries)} countries")
    print(f"INFUR-mapped ISO3: {len(infur_iso)}")
    print(f"Still-unmapped INFUR labels ({len(uniq_unmapped)}): {uniq_unmapped[:30]}")


if __name__ == "__main__":
    main()
