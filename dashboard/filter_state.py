"""Resolve as-of / disease / country from the active analysis tab."""

from __future__ import annotations

from shiny import reactive, ui

# Set at app startup from AppData so empty selects still resolve.
_DEFAULT_AS_OF: str | None = None
_DEFAULT_DISEASE: str = "ASF"


def configure_defaults(*, as_of: str | None, disease: str | None = "ASF") -> None:
    global _DEFAULT_AS_OF, _DEFAULT_DISEASE
    _DEFAULT_AS_OF = as_of
    if disease:
        _DEFAULT_DISEASE = disease


def _or_default_as_of(value) -> str:  # noqa: ANN001
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return str(_DEFAULT_AS_OF or "")
    return text


def _or_default_disease(value) -> str:  # noqa: ANN001
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return _DEFAULT_DISEASE
    return text


def selected_as_of(input) -> str:  # noqa: ANN001
    tab = str(input.main_nav() or "")
    if tab == "Investigate":
        return _or_default_as_of(input.as_of_inv())
    if tab == "Forecast & Replay":
        return _or_default_as_of(input.as_of_fc())
    return _or_default_as_of(input.as_of_radar())


def selected_disease(input) -> str:  # noqa: ANN001
    tab = str(input.main_nav() or "")
    if tab == "Investigate":
        return _or_default_disease(input.disease_inv())
    if tab == "Forecast & Replay":
        return _or_default_disease(input.disease_fc())
    return _or_default_disease(input.disease_radar())


def selected_country(input) -> str:  # noqa: ANN001
    tab = str(input.main_nav() or "")
    if tab == "Forecast & Replay":
        return str(input.country_fc())
    return str(input.country_inv())


def case_disease(input) -> str:  # noqa: ANN001
    disease = selected_disease(input)
    # Radar "All diseases" falls back to the case-view default (ASF).
    return _DEFAULT_DISEASE if disease == "ALL" else disease


def _safe_update(session, input_id: str, selected, current) -> None:  # noqa: ANN001
    if selected is None or selected == "":
        return
    if current is not None and str(current) == str(selected):
        return
    ui.update_select(input_id, selected=str(selected), session=session)


def register_filter_sync(input, session) -> None:  # noqa: ANN001
    """Keep shared filters aligned across analysis tabs.

    Radar sidebars are always the source of truth for as-of / disease when
    entering Investigate or Forecast (those inputs are often created only on
    first visit, so change-events alone are not enough).
    """

    @reactive.effect
    def _ensure_radar_defaults():
        """Force latest as-of / default disease if the select has no value yet."""
        if not _DEFAULT_AS_OF:
            return
        as_of = input.as_of_radar()
        if as_of is None or str(as_of).strip() in ("", "None"):
            ui.update_select("as_of_radar", selected=_DEFAULT_AS_OF, session=session)
        disease = input.disease_radar()
        if disease is None or str(disease).strip() in ("", "None"):
            ui.update_select("disease_radar", selected=_DEFAULT_DISEASE, session=session)

    @reactive.effect
    @reactive.event(input.as_of_radar, input.disease_radar)
    def _from_radar():
        as_of = _or_default_as_of(input.as_of_radar())
        disease = _or_default_disease(input.disease_radar())
        _safe_update(session, "as_of_inv", as_of, input.as_of_inv())
        _safe_update(session, "as_of_fc", as_of, input.as_of_fc())
        if disease and disease != "ALL":
            _safe_update(session, "disease_inv", disease, input.disease_inv())
            _safe_update(session, "disease_fc", disease, input.disease_fc())

    @reactive.effect
    @reactive.event(input.as_of_inv, input.disease_inv, input.country_inv)
    def _from_inv():
        as_of = _or_default_as_of(input.as_of_inv())
        disease = _or_default_disease(input.disease_inv())
        country = input.country_inv()
        _safe_update(session, "as_of_radar", as_of, input.as_of_radar())
        _safe_update(session, "as_of_fc", as_of, input.as_of_fc())
        _safe_update(session, "disease_radar", disease, input.disease_radar())
        _safe_update(session, "disease_fc", disease, input.disease_fc())
        _safe_update(session, "country_fc", country, input.country_fc())

    @reactive.effect
    @reactive.event(input.as_of_fc, input.disease_fc, input.country_fc)
    def _from_fc():
        as_of = _or_default_as_of(input.as_of_fc())
        disease = _or_default_disease(input.disease_fc())
        country = input.country_fc()
        _safe_update(session, "as_of_radar", as_of, input.as_of_radar())
        _safe_update(session, "as_of_inv", as_of, input.as_of_inv())
        _safe_update(session, "disease_radar", disease, input.disease_radar())
        _safe_update(session, "disease_inv", disease, input.disease_inv())
        _safe_update(session, "country_inv", country, input.country_inv())

    @reactive.effect
    @reactive.event(input.main_nav)
    def _push_on_tab_enter():
        """Re-apply Radar filters when opening Investigate / Forecast.

        Do not read the destination inputs here — they may not exist until the
        tab has rendered once (first visit), which previously dropped the sync.
        """
        tab = str(input.main_nav() or "")
        if tab not in ("Investigate", "Forecast & Replay"):
            return
        as_of = _or_default_as_of(input.as_of_radar())
        disease = _or_default_disease(input.disease_radar())
        if as_of:
            target = "as_of_inv" if tab == "Investigate" else "as_of_fc"
            ui.update_select(target, selected=str(as_of), session=session)
        if disease and disease != "ALL":
            target = "disease_inv" if tab == "Investigate" else "disease_fc"
            ui.update_select(target, selected=str(disease), session=session)
