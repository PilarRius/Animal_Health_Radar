"""Resolve as-of / disease / country from the active analysis tab."""

from __future__ import annotations

from shiny import reactive, ui


def selected_as_of(input) -> str:  # noqa: ANN001
    tab = str(input.main_nav() or "")
    if tab == "Investigate":
        return str(input.as_of_inv())
    if tab == "Forecast & Replay":
        return str(input.as_of_fc())
    return str(input.as_of_radar())


def selected_disease(input) -> str:  # noqa: ANN001
    tab = str(input.main_nav() or "")
    if tab == "Investigate":
        return str(input.disease_inv() or "HPAI")
    if tab == "Forecast & Replay":
        return str(input.disease_fc() or "HPAI")
    return str(input.disease_radar() or "HPAI")


def selected_country(input) -> str:  # noqa: ANN001
    tab = str(input.main_nav() or "")
    if tab == "Forecast & Replay":
        return str(input.country_fc())
    return str(input.country_inv())


def case_disease(input) -> str:  # noqa: ANN001
    disease = selected_disease(input)
    return "HPAI" if disease == "ALL" else disease


def register_filter_sync(input, session) -> None:  # noqa: ANN001
    """Keep shared filters aligned across analysis tabs (skip no-op updates)."""

    @reactive.effect
    @reactive.event(input.as_of_radar, input.disease_radar)
    def _from_radar():
        as_of = input.as_of_radar()
        disease = input.disease_radar()
        if input.as_of_inv() != as_of:
            ui.update_select("as_of_inv", selected=as_of, session=session)
        if input.as_of_fc() != as_of:
            ui.update_select("as_of_fc", selected=as_of, session=session)
        if disease and disease != "ALL":
            if input.disease_inv() != disease:
                ui.update_select("disease_inv", selected=disease, session=session)
            if input.disease_fc() != disease:
                ui.update_select("disease_fc", selected=disease, session=session)

    @reactive.effect
    @reactive.event(input.as_of_inv, input.disease_inv, input.country_inv)
    def _from_inv():
        as_of = input.as_of_inv()
        disease = input.disease_inv()
        country = input.country_inv()
        if input.as_of_radar() != as_of:
            ui.update_select("as_of_radar", selected=as_of, session=session)
        if input.as_of_fc() != as_of:
            ui.update_select("as_of_fc", selected=as_of, session=session)
        if input.disease_radar() != disease:
            ui.update_select("disease_radar", selected=disease, session=session)
        if input.disease_fc() != disease:
            ui.update_select("disease_fc", selected=disease, session=session)
        if input.country_fc() != country:
            ui.update_select("country_fc", selected=country, session=session)

    @reactive.effect
    @reactive.event(input.as_of_fc, input.disease_fc, input.country_fc)
    def _from_fc():
        as_of = input.as_of_fc()
        disease = input.disease_fc()
        country = input.country_fc()
        if input.as_of_radar() != as_of:
            ui.update_select("as_of_radar", selected=as_of, session=session)
        if input.as_of_inv() != as_of:
            ui.update_select("as_of_inv", selected=as_of, session=session)
        if input.disease_radar() != disease:
            ui.update_select("disease_radar", selected=disease, session=session)
        if input.disease_inv() != disease:
            ui.update_select("disease_inv", selected=disease, session=session)
        if input.country_inv() != country:
            ui.update_select("country_inv", selected=country, session=session)
