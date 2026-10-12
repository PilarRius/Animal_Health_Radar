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
- Absence of **INFUR** after a model alert also does **not** prove absence of disease (see reporting behaviour below).

Full information model: `EUFMD/NSA/empresi-data-integraton/docs/WAHIS_INFUR_SMR_information_model.md`

## Reporting behaviour nuances (INFUR silence ≠ no disease)

These operational realities matter for early-warning validation in the app:

### 1. “Stable” / endemic situations leave INFUR

When a country treats the disease situation as **stable** (operationally: the event-driven emergency phase is over and the disease is handled as **endemic** / established), Members typically **stop submitting new Immediate Notifications / Follow-Ups** for routine occurrence. Subsequent official visibility often appears only on the **Six-Month Report** (semester status, and sometimes semester outbreak totals).

Implication for AHR:

- Model WATCH/ALERT with **no later INFUR** may still be followed by an SMR that lists disease **present** / new or total outbreaks for that semester.
- That is **secondary official validation** (coarse grain), not day-level INFUR lead time.
- Do **not** merge those SMR rows into the INFUR weekly outbreak curve.

### 2. Not all diseases are notifiable via INFUR

Some diseases (or presentations) are **not notifiable** through the Immediate Notification pathway. For those, official status may **only** appear on SMR (or not in WAHIS event streams at all).

Implication: INFUR-based “finally reported” and INFUR lead-time metrics will be empty by design; SMR (or other sources) is the only official check.

### 3. Notifiable but endemic — INFUR under-used

Even when a disease **is** notifiable, countries with **endemic** circulation often do **not** keep using INFUR for every occurrence (fatigue, stable/endemic framing, national practice). Official confirmation of continued presence then skews to **SMR**.

Implication: intelligence + model alerts in endemic settings need SMR-aware evaluation; otherwise the demo falsely looks like “false alarms” whenever INFUR goes quiet.

### 4. How the Forecast & Replay storyline uses this

| Step | Source | Role |
|------|--------|------|
| INFUR before / after as-of | Final-vintage INFUR weeks | Primary timed official observation |
| Lead time model → INFUR | Same | Best early-warning proof when a later INFUR week exists |
| SMR semester check | `smr_disease_present` / `smr_new_outbreaks` / `smr_total_outbreaks` | Secondary validation when INFUR is silent; semester end + `available_from` (report knowability) |

SMR covariates are still **never** treated as INFUR outbreak events.

## How we map INFUR into AHR

When files appear under `data/raw/infur/`:

1. Prefer event/outbreak grain with **event time** (`startDate` / onset) separate from **observation time** (`submissionDate` / `reportedOn` / publication).
2. Set `available_from` from the earliest public knowability timestamp (submission/publication) — never substitute publication for onset.
3. Aggregate to `country × disease × week` for the modelling panel; keep outbreak-level rows in interim for maps/provenance.
4. Keep `data_realism = real` and full provenance (§61).

SMR: semester status covariates (`smr_*` in `data/interim/covariates.parquet`) — reporting-intensity / presence context and secondary replay validation; **not** outbreak counts mixed into the INFUR burden series.

## File naming (suggested)

```
data/raw/infur/wahis_infur_*.xlsx   # or .csv
data/raw/smr/wahis_smr_*.xlsx
```

After dropping files, tell the agent to run field inspection + adapter mapping before re-training.
