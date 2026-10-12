"""Animal Health Radar — Shiny for Python entry point.

Loads precomputed predictions only. No model fitting inside reactives.

::

    shiny run app.py
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shiny import App, reactive, render

from dashboard.data_loader import AppData
from dashboard.filter_state import (
    configure_defaults,
    register_filter_sync,
    selected_as_of,
    selected_disease,
)
from dashboard.layouts.shell import app_ui
from dashboard.modules import forecast as forecast_mod
from dashboard.modules import investigate as investigate_mod
from dashboard.modules import radar as radar_mod

DATA = AppData.load(ROOT)
DEFAULT_AS_OF = DATA.as_of_dates[-1] if DATA.as_of_dates else None
DEFAULT_DISEASE = "ASF" if "ASF" in DATA.diseases else (next(iter(DATA.diseases), None))
configure_defaults(as_of=DEFAULT_AS_OF, disease=DEFAULT_DISEASE)


def server(input, output, session):  # noqa: ANN001
    register_filter_sync(input, session)

    @reactive.calc
    def filtered_predictions():
        as_of = selected_as_of(input) or DEFAULT_AS_OF
        disease = selected_disease(input) or DEFAULT_DISEASE or "ASF"
        return DATA.predictions_as_of(as_of, disease)

    radar_mod.register(input, output, session, DATA, filtered_predictions)
    investigate_mod.register(input, output, session, DATA, filtered_predictions)
    forecast_mod.register(input, output, session, DATA, filtered_predictions)

    @render.text
    def banner():
        mode = DATA.data_mode.upper()
        return (
            f"DATA MODE: {mode} · All map values are MODEL ESTIMATES (not confirmed outbreaks). "
            "Start with Investigation priority · use as-of to move backwards in time · "
            "see Intro for the full story."
        )


app = App(app_ui(DATA), server)
