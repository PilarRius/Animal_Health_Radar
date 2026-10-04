# PADI-web raw cache

Real articles pulled from the public PADI-web JSON listing:

`GET https://padi-web.cirad.fr/en/articles/api/`

```bash
python scripts/fetch_padiweb.py
```

Produces `padiweb_articles_panel.csv` (HPAI / ASF × panel countries).

Set `sources.padiweb.refresh: true` in `config/config.yaml` to re-download on ingest.
See `docs/EIOS_BEACON_ACCESS.md` (PADI-web section).
