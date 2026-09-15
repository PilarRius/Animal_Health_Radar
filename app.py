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
from dashboard.layouts.shell import app_ui
from dashboard.modules import forecast as forecast_mod
from dashboard.modules import investigate as investigate_mod
from dashboard.modules import radar as radar_mod

DATA = AppData.load(ROOT)


def server(input, output, session):  # noqa: ANN001
    @reactive.calc
    def filtered_predictions():
        return DATA.predictions_as_of(input.as_of(), input.disease())

    radar_mod.register(input, output, session, DATA, filtered_predictions)
    investigate_mod.register(input, output, session, DATA, filtered_predictions)
    forecast_mod.register(input, output, session, DATA, filtered_predictions)

    @render.text
    def banner():
        mode = DATA.data_mode.upper()
        return (
            f"DATA MODE: {mode} — all figures are MODEL ESTIMATES. "
            "Not confirmed outbreaks. Synthetic corpus until live WAHIS is configured."
        )


app = App(app_ui(DATA), server)
