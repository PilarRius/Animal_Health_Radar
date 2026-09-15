"""Source adapters.

Sources are grouped by the role they play in the causal chain, not by their
technology:

* **Official observation** -- :class:`~src.ingestion.wahis.WAHISAdapter` (primary),
  :class:`~src.ingestion.empresi.EMPRESiAdapter` (downstream of WAHIS).
* **Epidemic intelligence** -- BEACON, PADI-web, GDELT, EIOS (mock), ProMED,
  HealthMap. These see the world earlier and more noisily than the official
  process, which is exactly why they are useful and exactly why they must be
  de-duplicated against each other.
* **Environmental** -- ERA5, ERA5-Land, WorldClim. Independent of the reporting
  process.
* **Exposure and context** -- GLW4, FAOSTAT. Denominators, not observations.
"""

from src.ingestion.base import AdapterOutput, LiveSourceUnavailable, SourceAdapter
from src.ingestion.beacon import BEACONAdapter
from src.ingestion.eios import EIOSAdapter
from src.ingestion.empresi import EMPRESiAdapter
from src.ingestion.era5 import ERA5Adapter, ERA5LandAdapter
from src.ingestion.faostat import FAOSTATAdapter
from src.ingestion.gdelt import GDELTAdapter
from src.ingestion.glw4 import GLW4Adapter
from src.ingestion.healthmap import HealthMapAdapter
from src.ingestion.padiweb import PADIWebAdapter
from src.ingestion.promed import ProMEDAdapter
from src.ingestion.registry import (
    ADAPTER_REGISTRY,
    IngestionResult,
    build_adapters,
    run_ingestion,
    source_catalogue,
)
from src.ingestion.sample_generator import generate_sample_corpus
from src.ingestion.wahis import WAHISAdapter
from src.ingestion.worldclim import WorldClimAdapter

__all__ = [
    "ADAPTER_REGISTRY",
    "AdapterOutput",
    "BEACONAdapter",
    "EIOSAdapter",
    "EMPRESiAdapter",
    "ERA5Adapter",
    "ERA5LandAdapter",
    "FAOSTATAdapter",
    "GDELTAdapter",
    "GLW4Adapter",
    "HealthMapAdapter",
    "IngestionResult",
    "LiveSourceUnavailable",
    "PADIWebAdapter",
    "ProMEDAdapter",
    "SourceAdapter",
    "WAHISAdapter",
    "WorldClimAdapter",
    "build_adapters",
    "generate_sample_corpus",
    "run_ingestion",
    "source_catalogue",
]
