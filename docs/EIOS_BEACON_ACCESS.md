# BEACON, PADI-web & EIOS — how to get real data

## BEACON (public API — implemented)

Website: https://beaconbio.org  
Public API (no key): `https://api.beaconbio.org`

| Method | Path | Role |
|--------|------|------|
| GET | `/public/filter` | Disease / pathogen / location catalogues |
| GET | `/public/report?page=&limit=&diseases={uuid}` | Paginated curated reports |
| GET | `/public/report/{id}` | Full report |
| GET | `/public/event?page=&limit=` | Event clusters |

Animal Health Radar disease filters (catalogue UUIDs):

* African swine fever — `5fe4d6f3-94fd-4208-9111-c8fb203e82e4`
* Highly pathogenic avian influenza (HPAI) — `a50d3bd3-769b-4963-8d9b-0bd5ef853335`
* Avian influenza (bird flu) — `0c99bca8-0fc4-4d91-80ec-b345ec1dcf50`

```bash
# Fetch + cache under data/raw/beacon/
python scripts/fetch_beacon.py

# Or let ingest call the API (pilot mode, sources.beacon.refresh=true)
python scripts/ingest.py
```

Cache file: `data/raw/beacon/beacon_reports_panel.csv`  
Set `sources.beacon.refresh: false` in `config/config.yaml` to reuse the cache offline.

---

## PADI-web (public JSON API — implemented)

Website: https://padi-web.cirad.fr  
Public listing (no key): `GET https://padi-web.cirad.fr/en/articles/api/`

This is the same JSON endpoint the free SPA uses. Filters that work:

| Param | Role |
|-------|------|
| `source_category` | Disease feed (e.g. `Avian Influenza`, `African Swine Fever`) |
| `country` | ISO2 code (`FR`, `DE`, …) |
| `published_after` / `published_before` | Publication window |
| `general_labels_per_task[Relevance]=1` | Relevant articles only |
| `page` / `per_page` | Pagination (DRF-style `count` / `next` / `results`) |

Categories used for this pilot:

* HPAI — `Avian Influenza`, `Avian Influenza Press Releases`, `Official AI press releases`
* ASF — `African Swine Fever`

```bash
# Fetch + cache under data/raw/padiweb/
python scripts/fetch_padiweb.py

# Or let ingest call the API (pilot mode, sources.padiweb.refresh=true)
python scripts/ingest.py
```

Cache file: `data/raw/padiweb/padiweb_articles_panel.csv`  
Set `sources.padiweb.refresh: false` to reuse the cache offline.

**UI CSV/XLSX/JSON export** in the portal requires Sign in + export permissions (`export_articleweb`). For advanced / extended access contact **padi-web@cirad.fr**. Research corpora (not a live feed) are also on [CIRAD Dataverse](https://www.padi-web-one-health.org/dissemination/datasets).

---

## EIOS (public newsmap + optional portal export)

### Public WHO Pandemic Hub newsmap — implemented

Map UI: https://portal.who.int/pandemichub/newsmap/

This is **not** the restricted EIOS community portal. It is the public WHO/JRC news map that surfaces **recent** open-source articles already tagged with EIOS category IDs. Disclaimer on the page: content is taken from publicly available sites and is not WHO-verified.

Public JSON tunnel (same API the map uses; no login):

| Call | Role |
|------|------|
| `GET .../tunnel?sid=&info=true&version=9.5` | Category catalogue |
| `GET .../tunnel?sid=&category=Avianflu&langs=&rows=` | Recent items |
| `GET .../tunnel?sid=&guids=id1,id2` | Titles / links |

Pilot categories: `Avianflu`, `H5N1`, `H5N6`, `H5N8`, `InfluenzaHXNXAnimal`, `InfluenzaHumanAnimalInterface`, `SwineFever`, `PigDisease`.

```bash
python scripts/fetch_eios_newsmap.py
# cache: data/raw/eios/eios_newsmap_panel.csv
```

**Limits:** recent window only (days–weeks, not multi-year history); country often comes from EIOS tags (noisy); media-source country is a weak fallback.

### Full EIOS community portal (optional, richer)

1. Community page: https://www.who.int/initiatives/eios/eios-community-of-practice  
2. Request access via WHO / WOAH contact.  
3. Export Animal Health / HPAI / ASF Excel or CSV (§2.7).  
4. Drop under `data/raw/eios/` (any name except `eios_newsmap_panel.csv`) — portal exports take priority on ingest.

If neither newsmap cache nor portal export is available, the adapter falls back to the labelled **MOCK** corpus.

---

## Independence note

BEACON and EIOS are **aggregator** intelligence; PADI-web sits in the **media** cluster with GDELT / ProMED / HealthMap. They often rest on the same open news. The fusion layer discounts within-cluster dependence (`beacon_media_dependence`, evidence clusters in `config.yaml`) so overlapping stories are not counted as fully independent corroboration.
