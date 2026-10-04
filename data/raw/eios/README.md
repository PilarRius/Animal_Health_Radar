# EIOS raw data

## Preferred: public WHO newsmap (implemented)

```bash
python scripts/fetch_eios_newsmap.py
```

Writes `eios_newsmap_panel.csv` from the public Pandemic Hub newsmap
(`https://portal.who.int/pandemichub/newsmap/`). Recent EIOS-tagged open news only.

## Optional: full community portal export

Drop WHO EIOS portal Excel/CSV exports here (any name except `eios_newsmap_panel.csv`).
Portal exports take priority over the newsmap cache on ingest.

See `docs/EIOS_BEACON_ACCESS.md`.
