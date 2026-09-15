# Dropping real WAHIS INFUR / SMR data

Place pilot Excel/CSV extracts here (gitignored under `data/raw/`):

```
data/raw/
  infur/          # Immediate Notification / Follow-Up Reports (event-driven)
  smr/            # Six-Month Reports (semester country disease status)
```

## What INFUR vs SMR mean

From the EuFMD EMPRES-i WAHIS integration notes
(`EUFMD/NSA/empresi-data-integraton`):

| | **INFUR** | **SMR** |
|---|-----------|---------|
| Full name | Immediate Notification / Follow-Up Report | Six-Month Report |
| Rhythm | Real-time (IN + FUR) | Every semester (SEM01 / SEM02) |
| Question | What happened in this **event/outbreak**? | What is the **official semester status** for listed diseases in this country? |
| Space | Outbreak points (lat/lon) + admin labels | Mostly **country-level**; `adminDivision` only when quantities exist |
| IDs | `eventId`, `reportId`, `outbreakId` | `reportId`, `reportInfoId` — **different ID space** from INFUR |
| Link | No API foreign key — soft link on country + disease + admin + time only |

**Critical for Animal Health Radar**

- **INFUR** is the primary **official observation process** for early warning / nowcasting / lead-time evaluation (event onset → notification → publication).
- **SMR** is a **semester portfolio / status** layer. Do **not** treat SMR rows as outbreak events, and do **not** assume INFUR and SMR quantities match (they usually do not).
- `reportId` in INFUR ≠ `reportId` in SMR.
- Absence of SMR quantities does **not** mean absence of disease (status can be PRESENT with no counts).

Full information model: `EUFMD/NSA/empresi-data-integraton/docs/WAHIS_INFUR_SMR_information_model.md`

## How we will map INFUR into AHR

When files appear under `data/raw/infur/`:

1. Prefer event/outbreak grain with **event time** (`startDate` / onset) separate from **observation time** (`submissionDate` / `reportedOn` / publication).
2. Set `available_from` from the earliest public knowability timestamp (submission/publication) — never substitute publication for onset.
3. Aggregate to `country × disease × week` for the modelling panel; keep outbreak-level rows in interim for maps/provenance.
4. Keep `data_realism = real` and full provenance (§61).

SMR (optional later): contextual reporting-intensity / disease-status covariates — not outbreak counts mixed into the INFUR burden series.

## File naming (suggested)

```
data/raw/infur/wahis_infur_*.xlsx   # or .csv
data/raw/smr/wahis_smr_*.xlsx
```

After dropping files, tell the agent to run field inspection + adapter mapping before re-training.
