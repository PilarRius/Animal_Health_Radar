"""Generation of the labelled SYNTHETIC sample corpus.

Why a simulator rather than a fixture
-------------------------------------
The whole thesis of the Radar is that the *observation process* is separate
from the *disease process*. A hand-written fixture cannot exercise that: it has
no hidden layer. This module therefore simulates the full causal chain and then
throws most of it away, exposing to the pipeline only what a real analyst would
actually see.

::

    (1) LATENT PROCESS      spatio-temporal Hawkes process on weekly outbreaks
              |                driven by seasonality, climate suitability,
              |                livestock exposure, self- and cross-excitation
              v
    (2) DETECTION           Binomial thinning with country-specific
              |                ascertainment (surveillance capacity tiers)
              v
    (3) REPORTING           log-normal onset -> suspicion -> confirmation ->
              |                notification -> publication delays
              v
    (4) OBSERVATION         the WAHIS CSV that the pipeline is allowed to read

Media / intelligence signals are generated from layer (1) with a *short* delay,
while official records arrive from layer (4) with a *long* delay. That is the
exploitable structure the early-warning model is supposed to find, and it is
the same structure that exists in reality.

The true latent series is written to ``data/sample/_ground_truth_latent_weekly.csv``
and is used **only** by :mod:`src.evaluation`. A leakage test asserts that no
feature ever reads it.

Everything produced here is stamped ``realism = synthetic`` (or ``mock`` for
EIOS, whose real API is access-restricted).
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.utils.config import AppConfig, CountrySpec, DiseaseSpec, get_config, load_countries, load_diseases
from src.utils.dates import week_starts_between
from src.utils.geo import build_adjacency, country_radius_km, decay_kernel, distance_matrix, jitter_point
from src.utils.io import write_csv, write_json
from src.utils.logging_utils import get_logger
from src.utils.paths import ensure_dir

LOGGER = get_logger(__name__)

__all__ = ["SampleCorpusGenerator", "generate_sample_corpus", "SAMPLE_FILES"]


#: Files the generator produces, keyed by the adapter that consumes them.
SAMPLE_FILES: dict[str, str] = {
    "wahis": "wahis_events_sample.csv",
    "empresi": "empresi_events_sample.csv",
    "gdelt": "gdelt_daily_sample.csv",
    "padiweb": "padiweb_articles_sample.csv",
    "promed": "promed_posts_sample.csv",
    "healthmap": "healthmap_alerts_sample.csv",
    "beacon": "beacon_signals_sample.csv",
    "eios": "eios_board_items_mock.csv",
    "era5": "era5_weekly_sample.csv",
    "era5_land": "era5land_weekly_sample.csv",
    "worldclim": "worldclim_climatology_sample.csv",
    "glw4": "glw4_livestock_density_sample.csv",
    "faostat": "faostat_livestock_annual_sample.csv",
    "truth": "_ground_truth_latent_weekly.csv",
    "manifest": "MANIFEST.json",
}

#: Surveillance-capacity tier -> (mean ascertainment, delay log-offset)
_CAPACITY: dict[str, tuple[float, float]] = {
    "high": (0.82, -0.28),
    "medium": (0.56, 0.00),
    "low": (0.29, 0.34),
}

#: Tier -> how much local media chatter escapes even when nothing is notified.
_CHATTER: dict[str, float] = {"high": 0.55, "medium": 0.75, "low": 0.95}


def _stable_hash(text: str) -> int:
    """Deterministic string hash.

    ``hash()`` is salted per interpreter process (PYTHONHASHSEED), so using it
    to derive RNG streams would make the "reproducible" corpus different on
    every run. CRC32 is stable across processes and platforms.
    """
    return zlib.crc32(text.encode("utf-8"))


@dataclass
class _SimulationResult:
    """Internal container for the latent + observed layers."""

    weeks: list[date]
    latent: dict[str, np.ndarray]        # disease -> (T, C) true outbreaks
    detected: dict[str, np.ndarray]      # disease -> (T, C) detected outbreaks
    suitability: dict[str, np.ndarray]   # disease -> (T, C) suitability index
    climate: dict[str, np.ndarray]       # variable -> (T, C)
    outbreak_records: list[dict[str, Any]]


class SampleCorpusGenerator:
    """Builds the entire offline synthetic corpus from configuration."""

    def __init__(self, config: AppConfig | None = None, seed: int | None = None) -> None:
        self.config = config or get_config()
        self.countries: dict[str, CountrySpec] = load_countries()
        self.diseases: dict[str, DiseaseSpec] = load_diseases()
        self.seed = int(seed if seed is not None else self.config.random_seed)
        self.rng = np.random.default_rng(self.seed)

        self.iso3: list[str] = list(self.countries.keys())
        self.n_countries = len(self.iso3)
        self.weeks: list[date] = week_starts_between(
            self.config.start_date, self.config.end_date
        )
        self.n_weeks = len(self.weeks)
        self.cutoff: date = self.config.data_cutoff
        self.out_dir = ensure_dir(self.config.path("data_sample"))

        distances = distance_matrix(self.countries)
        self.spatial_weights = decay_kernel(
            distances,
            bandwidth_km=float(self.config.get("features.spatial_kernel_km", 900.0)),
            shared_border=build_adjacency(self.countries),
        ).to_numpy()

    # ------------------------------------------------------------------ #
    # public entry point
    # ------------------------------------------------------------------ #
    def generate(self) -> dict[str, Any]:
        """Run the simulation and write every sample file. Returns a manifest."""
        LOGGER.info(
            "Simulating %s weeks x %s countries x %s diseases (seed=%s)",
            self.n_weeks, self.n_countries, len(self.diseases), self.seed,
        )
        sim = self._simulate()

        manifest: dict[str, Any] = {
            "generator": "src.ingestion.sample_generator.SampleCorpusGenerator",
            "realism": "synthetic",
            "warning": (
                "ALL FILES IN THIS DIRECTORY ARE SYNTHETIC. They are produced by an "
                "epidemiological simulator for offline development and must never be "
                "interpreted as observations of real animal disease events."
            ),
            "seed": self.seed,
            "generated_for_cutoff": self.cutoff.isoformat(),
            "period": {"start": self.weeks[0].isoformat(), "end": self.weeks[-1].isoformat()},
            "countries": self.iso3,
            "diseases": list(self.diseases.keys()),
            "files": {},
        }

        writers = [
            ("wahis", self._write_wahis, sim),
            ("empresi", self._write_empresi, sim),
            ("gdelt", self._write_gdelt, sim),
            ("padiweb", self._write_padiweb, sim),
            ("promed", self._write_promed, sim),
            ("healthmap", self._write_healthmap, sim),
            ("beacon", self._write_beacon, sim),
            ("eios", self._write_eios, sim),
            ("era5", self._write_era5, sim),
            ("era5_land", self._write_era5_land, sim),
            ("worldclim", self._write_worldclim, sim),
            ("glw4", self._write_glw4, sim),
            ("faostat", self._write_faostat, sim),
            ("truth", self._write_truth, sim),
        ]
        for key, writer, payload in writers:
            frame = writer(payload)
            path = write_csv(frame, self.out_dir / SAMPLE_FILES[key])
            manifest["files"][SAMPLE_FILES[key]] = {
                "adapter": key,
                "rows": int(len(frame)),
                "columns": list(frame.columns),
            }
            LOGGER.info("  %-38s %6d rows", SAMPLE_FILES[key], len(frame))

        write_json(manifest, self.out_dir / SAMPLE_FILES["manifest"])
        self._write_readme(manifest)
        return manifest

    # ------------------------------------------------------------------ #
    # layer 1-3: the simulation
    # ------------------------------------------------------------------ #
    def _simulate(self) -> _SimulationResult:
        climate = self._simulate_climate()
        latent: dict[str, np.ndarray] = {}
        detected: dict[str, np.ndarray] = {}
        suitability: dict[str, np.ndarray] = {}
        records: list[dict[str, Any]] = []

        for code, disease in self.diseases.items():
            suit = self._suitability(disease, climate)
            n_true = self._hawkes(disease, suit)
            n_det = self._detect(disease, n_true)
            latent[code] = n_true
            detected[code] = n_det
            suitability[code] = suit
            records.extend(self._materialise_outbreaks(disease, n_det))

        LOGGER.info("  latent outbreaks simulated: %s", {k: int(v.sum()) for k, v in latent.items()})
        LOGGER.info("  detected outbreaks:         %s", {k: int(v.sum()) for k, v in detected.items()})
        return _SimulationResult(
            weeks=self.weeks,
            latent=latent,
            detected=detected,
            suitability=suitability,
            climate=climate,
            outbreak_records=records,
        )

    # -- climate ------------------------------------------------------- #
    def _simulate_climate(self) -> dict[str, np.ndarray]:
        """Weekly country-mean temperature, precipitation and humidity.

        Latitude sets the seasonal amplitude and mean; an AR(1) anomaly gives
        year-to-year variability so that the environmental covariates carry
        information beyond a pure sine wave.
        """
        rng = np.random.default_rng(self.seed + 101)
        T, C = self.n_weeks, self.n_countries
        lats = np.array([self.countries[c].lat for c in self.iso3])
        week_index = np.arange(T)
        # week-of-year phase, 52.18 weeks per tropical year
        phase = 2.0 * np.pi * ((week_index % 52.18) - 3.0) / 52.18

        mean_temp = 29.0 - 0.42 * np.abs(lats)                # ~28C at equator, ~8C at 50N
        amplitude = 2.0 + 0.30 * np.abs(lats)                 # stronger seasonality poleward

        base = mean_temp[None, :] - amplitude[None, :] * np.cos(phase)[:, None]
        anomaly = self._ar1(rng, T, C, rho=0.72, sd=1.65)
        t2m = base + anomaly

        precip_base = 16.0 + 14.0 * np.exp(-((lats - 50.0) ** 2) / (2 * 18.0**2))[None, :]
        precip_season = 1.0 + 0.45 * np.sin(phase + 1.1)[:, None]
        precip = np.clip(
            precip_base * precip_season * np.exp(self._ar1(rng, T, C, 0.45, 0.32)), 0.0, None
        )

        humidity = np.clip(
            64.0 + 0.25 * (precip - precip.mean()) - 0.45 * (t2m - t2m.mean())
            + self._ar1(rng, T, C, 0.5, 3.0),
            20.0, 100.0,
        )
        # Long-term climatology (what WorldClim would say) = seasonal signal only
        return {
            "t2m_mean_c": t2m,
            "precip_mm_week": precip,
            "rel_humidity_pct": humidity,
            "t2m_climatology_c": base,
            "precip_climatology_mm": precip_base * precip_season,
        }

    @staticmethod
    def _ar1(rng: np.random.Generator, T: int, C: int, rho: float, sd: float) -> np.ndarray:
        out = np.zeros((T, C))
        innovation_sd = sd * np.sqrt(1.0 - rho**2)
        out[0] = rng.normal(0.0, sd, size=C)
        for t in range(1, T):
            out[t] = rho * out[t - 1] + rng.normal(0.0, innovation_sd, size=C)
        return out

    # -- suitability ----------------------------------------------------- #
    def _suitability(self, disease: DiseaseSpec, climate: dict[str, np.ndarray]) -> np.ndarray:
        """Disease-specific environmental suitability in roughly [0.2, 2.0].

        Gaussian thermal response x precipitation modifier x cold-anomaly push
        (relevant for HPAI: cold snaps displace migratory waterfowl).
        """
        t2m = climate["t2m_mean_c"]
        precip = climate["precip_mm_week"]
        clim_t = climate["t2m_climatology_c"]

        env = disease.environment
        opt = env.get("temp_optimum_c", 12.0)
        tol = max(env.get("temp_tolerance_c", 10.0), 1.0)
        thermal = np.exp(-0.5 * ((t2m - opt) / tol) ** 2)

        precip_z = (precip - precip.mean(axis=0, keepdims=True)) / (
            precip.std(axis=0, keepdims=True) + 1e-9
        )
        precip_term = 1.0 + env.get("precip_effect", 0.0) * precip_z

        cold_anomaly = np.clip(-(t2m - clim_t), 0.0, None) / 3.0
        cold_term = 1.0 + env.get("cold_anomaly_weight", 0.0) * cold_anomaly

        # Latitudinal host-reservoir proxy (flyways for HPAI, wild boar for ASF)
        lats = np.array([self.countries[c].lat for c in self.iso3])
        lat_opt = env.get("lat_optimum")
        if lat_opt is not None:
            lat_tol = max(env.get("lat_tolerance", 15.0), 1.0)
            lat_term = 0.25 + 0.75 * np.exp(-0.5 * ((lats - lat_opt) / lat_tol) ** 2)
        else:
            lat_term = np.ones_like(lats)

        suit = thermal * np.clip(precip_term, 0.4, 1.8) * np.clip(cold_term, 0.8, 2.2)
        suit = suit * lat_term[None, :]
        # Normalise so the average country-week has suitability 1.0
        return np.clip(suit / max(float(suit.mean()), 1e-9), 0.05, 4.0)

    # -- Hawkes latent process -------------------------------------------- #
    def _hawkes(self, disease: DiseaseSpec, suitability: np.ndarray) -> np.ndarray:
        """Self- and cross-exciting weekly count process with saturation.

        ``lambda_{c,t} = s_{c,t} * D_{c,t} * ( mu_c
                          + alpha * sum_k g_k N_{c,t-k}
                          + beta  * sum_k g_k (W N_{.,t-k})_c )``

        ``g_k`` is a normalised geometric memory kernel over four weeks,
        ``W`` the row-normalised distance-decay matrix and ``D`` a saturation
        term representing depletion of susceptible holdings plus the control
        measures that follow a large wave.
        """
        rng = np.random.default_rng(self.seed + _stable_hash(disease.code) % 9973)
        T, C = self.n_weeks, self.n_countries

        exposure = self._exposure_factor(disease)
        season = self._seasonal_multiplier(disease)
        mu = disease.baseline_hazard * exposure                      # (C,)
        alpha = disease.self_excitation
        beta = disease.spatial_excitation
        kernel = np.array([0.45, 0.28, 0.17, 0.10])                  # 4-week memory
        kernel = kernel / kernel.sum()
        carrying = 22.0 + 30.0 * exposure                            # (C,) saturation scale

        counts = np.zeros((T, C), dtype=float)
        for t in range(T):
            lags = min(t, kernel.size)
            if lags == 0:
                own = np.zeros(C)
                neighbour = np.zeros(C)
            else:
                recent = counts[t - lags:t][::-1]                    # (lags, C), newest first
                weights = kernel[:lags][:, None]
                own = float(1.0) * (recent * weights).sum(axis=0)
                neighbour = self.spatial_weights @ own
            # saturation from the past year of activity in the same country
            recent_year = counts[max(0, t - 52):t].sum(axis=0)
            damping = 1.0 / (1.0 + recent_year / carrying)

            lam = suitability[t] * season[t] * damping * (mu + alpha * own + beta * neighbour)
            lam = np.clip(lam, 0.0, 90.0)
            counts[t] = rng.poisson(lam)

        return counts

    def _exposure_factor(self, disease: DiseaseSpec) -> np.ndarray:
        """Relative host-population exposure per country, centred on 1.0.

        Host density enters sub-linearly (a country with ten times the density
        is not ten times the risk) and is multiplied by the configured
        reservoir/introduction-pressure scenario for the synthetic build.
        """
        layer = disease.exposure_layer
        key = {"chickens_density": "chickens", "pigs_density": "pigs"}.get(layer, "cattle")
        heads = np.array([max(self.countries[c].livestock.get(key, 1.0), 1.0) for c in self.iso3])
        density = heads / np.array([max(self.countries[c].area_km2, 1.0) for c in self.iso3])
        factor = np.clip((density / np.median(density)) ** 0.30, 0.35, 2.4)

        scenario = np.array(
            [disease.country_risk_multiplier.get(c, 1.0) for c in self.iso3], dtype=float
        )
        return np.clip(factor * scenario, 0.05, 5.0)

    def _seasonal_multiplier(self, disease: DiseaseSpec) -> np.ndarray:
        """von-Mises-shaped seasonality normalised to mean 1 over the year."""
        peak = disease.seasonality.get("peak_week", 1.0)
        kappa = disease.seasonality.get("kappa", 1.5)
        amplitude = disease.seasonality.get("amplitude", 1.2)
        week_of_year = np.array([w.isocalendar().week for w in self.weeks], dtype=float)
        theta = 2.0 * np.pi * (week_of_year - peak) / 52.18
        shape = np.exp(kappa * np.cos(theta))
        shape = shape / shape.mean()
        return 1.0 + (amplitude - 1.0) * (shape - 1.0) / max(shape.max() - 1.0, 1e-9) * 2.0

    # -- detection -------------------------------------------------------- #
    def _detect(self, disease: DiseaseSpec, latent: np.ndarray) -> np.ndarray:
        """Binomial thinning of the latent process by country ascertainment."""
        rng = np.random.default_rng(self.seed + 555 + _stable_hash(disease.code) % 7919)
        multiplier = float(
            self.config.get(f"ascertainment.disease_multiplier.{disease.code}", 1.0)
        )
        rho = np.array(
            [
                np.clip(_CAPACITY[self.countries[c].surveillance_capacity][0] * multiplier, 0.02, 0.98)
                for c in self.iso3
            ]
        )
        detected = np.zeros_like(latent)
        for t in range(latent.shape[0]):
            detected[t] = rng.binomial(latent[t].astype(int), rho)
        return detected

    # -- reporting -------------------------------------------------------- #
    def _materialise_outbreaks(
        self, disease: DiseaseSpec, detected: np.ndarray
    ) -> list[dict[str, Any]]:
        """Turn detected weekly counts into individual dated outbreak records."""
        rng = np.random.default_rng(self.seed + 7000 + _stable_hash(disease.code) % 6113)
        meanlog = disease.reporting_delay.get("meanlog", 2.6)
        sdlog = disease.reporting_delay.get("sdlog", 0.65)
        size = disease.outbreak_size
        cases_mean = size.get("cases_mean", 500.0)
        cases_disp = max(size.get("cases_dispersion", 0.5), 1e-3)
        cfr = np.clip(size.get("case_fatality", 0.5), 0.0, 1.0)

        records: list[dict[str, Any]] = []
        first_seen: dict[str, bool] = {}
        counter = 0

        for t, week in enumerate(self.weeks):
            for ci, iso in enumerate(self.iso3):
                n = int(detected[t, ci])
                if n <= 0:
                    continue
                spec = self.countries[iso]
                tier = spec.surveillance_capacity
                delay_offset = _CAPACITY[tier][1]
                radius = country_radius_km(spec.area_km2)

                # WAHIS groups foci into an event; simulate that grouping
                event_root = f"{disease.code}-{iso}-{week.isoformat()}"
                for focus in range(n):
                    counter += 1
                    onset = week + timedelta(days=int(rng.integers(0, 7)))

                    total_delay = float(rng.lognormal(meanlog + delay_offset, sdlog))
                    total_delay = float(np.clip(total_delay, 1.0, 240.0))
                    # Split the delay across the observation chain
                    f_susp = float(np.clip(rng.beta(2.4, 3.0), 0.05, 0.85))
                    f_conf = float(np.clip(f_susp + rng.beta(2.2, 2.6) * (1 - f_susp), f_susp, 0.97))
                    suspicion = onset + timedelta(days=int(round(total_delay * f_susp)))
                    confirmation = onset + timedelta(days=int(round(total_delay * f_conf)))
                    notification = onset + timedelta(days=int(round(total_delay)))
                    publication = notification + timedelta(days=int(1 + rng.poisson(1.8)))

                    cases = int(max(1, self._nb_draw(rng, cases_mean, cases_disp)))
                    deaths = int(rng.binomial(cases, cfr))
                    killed = int(min(cases + rng.poisson(cases * 0.35), 10_000_000))
                    susceptible = int(cases * float(rng.uniform(1.4, 9.0)))

                    lat, lon = jitter_point(spec.lat, spec.lon, radius_km=radius, rng=rng)
                    species = str(rng.choice(disease.species)) if disease.species else "unknown"
                    is_wild = "wild" in species.lower() or "boar" in species.lower()

                    key = f"{iso}|{disease.code}"
                    is_first = key not in first_seen
                    first_seen[key] = True

                    records.append(
                        {
                            "disease": disease.code,
                            "country_iso3": iso,
                            "week_start": week,
                            "focus_index": focus,
                            "event_id": f"WAHIS-{event_root}",
                            "outbreak_id": f"WAHIS-{event_root}-{focus:02d}",
                            "internal_ref": counter,
                            "onset_date": onset,
                            "suspicion_date": suspicion,
                            "confirmation_date": confirmation,
                            "notification_date": notification,
                            "publication_date": publication,
                            "cases": cases,
                            "deaths": deaths,
                            "killed_disposed": killed,
                            "susceptible": susceptible,
                            "latitude": round(lat, 4),
                            "longitude": round(lon, 4),
                            "species": species,
                            "host_category": "wild" if is_wild else "domestic",
                            "is_first_occurrence": is_first,
                        }
                    )
        return records

    @staticmethod
    def _nb_draw(rng: np.random.Generator, mean: float, dispersion: float) -> int:
        """Gamma-Poisson draw with mean-dispersion parameterisation."""
        shape = 1.0 / max(dispersion, 1e-6)
        lam = rng.gamma(shape=shape, scale=max(mean, 1e-6) / shape)
        return int(rng.poisson(lam))

    # ------------------------------------------------------------------ #
    # layer 4: the files a real analyst would see
    # ------------------------------------------------------------------ #
    def _write_wahis(self, sim: _SimulationResult) -> pd.DataFrame:
        """Official notifications, one row per outbreak/focus.

        Only rows whose *publication* date falls on or before the corpus cut-off
        exist: an outbreak notified after the cut-off simply has not happened as
        far as the pipeline is concerned.
        """
        rows: list[dict[str, Any]] = []
        for rec in sim.outbreak_records:
            if rec["publication_date"] > self.cutoff:
                continue
            disease = self.diseases[rec["disease"]]
            spec = self.countries[rec["country_iso3"]]
            report_number = 1 if rec["focus_index"] == 0 else 1 + rec["focus_index"] // 4
            rows.append(
                {
                    "event_id": rec["event_id"],
                    "outbreak_id": rec["outbreak_id"],
                    "report_type": "immediate_notification" if report_number == 1 else "follow_up_report",
                    "report_number": report_number,
                    "disease": disease.wahis_name,
                    "disease_code": disease.code,
                    "serotype": "H5N1" if disease.code == "HPAI" else "genotype II",
                    "country": spec.name,
                    "iso3": spec.iso3,
                    "admin1": f"{spec.iso3}-R{(rec['internal_ref'] % 9) + 1}",
                    "locality": f"{spec.name} locality {rec['internal_ref'] % 240}",
                    "latitude": rec["latitude"],
                    "longitude": rec["longitude"],
                    "location_precision": "point",
                    "start_date": rec["onset_date"].isoformat(),
                    "date_of_suspicion": rec["suspicion_date"].isoformat(),
                    "date_of_confirmation": rec["confirmation_date"].isoformat(),
                    "date_of_notification": rec["notification_date"].isoformat(),
                    "date_of_publication": rec["publication_date"].isoformat(),
                    "event_status": "resolved" if rec["publication_date"] < self.cutoff - timedelta(days=180) else "ongoing",
                    "diagnosis": "laboratory_confirmed",
                    "species": rec["species"],
                    "host_category": rec["host_category"],
                    "is_wild": rec["host_category"] == "wild",
                    "outbreaks": 1,
                    "susceptible": rec["susceptible"],
                    "cases": rec["cases"],
                    "deaths": rec["deaths"],
                    "killed_and_disposed": rec["killed_disposed"],
                    "is_first_occurrence": rec["is_first_occurrence"],
                    "control_measures": "stamping_out;movement_control;disinfection",
                    "data_realism": "synthetic",
                }
            )
        frame = pd.DataFrame(rows)
        return frame.sort_values(["date_of_publication", "event_id"]).reset_index(drop=True)

    def _write_empresi(self, sim: _SimulationResult) -> pd.DataFrame:
        """EMPRES-i view: a re-publication of a subset of WAHIS, 2-9 days later.

        Deliberately carries its own identifiers and a ``source_reference``
        column pointing back at WAHIS, so the linkage layer has something real
        to resolve and the independence logic something real to discount.
        """
        rng = np.random.default_rng(self.seed + 31)
        rows: list[dict[str, Any]] = []
        for rec in sim.outbreak_records:
            if rec["publication_date"] > self.cutoff:
                continue
            if rng.random() > 0.78:        # EMPRES-i does not mirror everything
                continue
            republished = rec["publication_date"] + timedelta(days=int(2 + rng.poisson(3.2)))
            if republished > self.cutoff:
                continue
            spec = self.countries[rec["country_iso3"]]
            rows.append(
                {
                    # The counter restarts per disease, so the disease code is
                    # part of the identifier: colliding ids across diseases
                    # would silently chain unrelated clusters in linkage.
                    "empresi_id": f"EMPRESI-{rec['disease']}-{rec['internal_ref']:07d}",
                    "source_reference": rec["outbreak_id"],
                    "upstream_source": "WAHIS",
                    "disease": self.diseases[rec["disease"]].name,
                    "disease_code": rec["disease"],
                    "country": spec.name,
                    "iso3": spec.iso3,
                    "latitude": rec["latitude"],
                    "longitude": rec["longitude"],
                    "observation_date": rec["onset_date"].isoformat(),
                    "report_date": rec["notification_date"].isoformat(),
                    "published_date": republished.isoformat(),
                    "species": rec["species"],
                    "cases": rec["cases"],
                    "deaths": rec["deaths"],
                    "status": "confirmed",
                    "data_realism": "synthetic",
                }
            )
        return pd.DataFrame(rows).sort_values("published_date").reset_index(drop=True)

    # -- intelligence sources ------------------------------------------- #
    def _media_intensity(self, sim: _SimulationResult, disease_code: str) -> np.ndarray:
        """Expected weekly media attention, driven by LATENT activity.

        Two components, which is what gives media its early-warning value:

        ``chatter``   local reporting of unusual mortality, proportional to the
                      *latent* burden and larger where official surveillance is
                      weak (the rumour fills the vacuum);
        ``echo``      coverage of officially published notifications, which by
                      construction arrives weeks later.
        """
        latent = sim.latent[disease_code]
        T, C = latent.shape
        chatter_weight = np.array(
            [_CHATTER[self.countries[c].surveillance_capacity] for c in self.iso3]
        )
        # official echo: weekly count of outbreaks PUBLISHED in each week
        echo = np.zeros((T, C))
        week_index = {w: i for i, w in enumerate(self.weeks)}
        col = {c: i for i, c in enumerate(self.iso3)}
        for rec in sim.outbreak_records:
            if rec["disease"] != disease_code or rec["publication_date"] > self.cutoff:
                continue
            pub_week = rec["publication_date"] - timedelta(days=rec["publication_date"].weekday())
            idx = week_index.get(pub_week)
            if idx is not None:
                echo[idx, col[rec["country_iso3"]]] += 1.0

        # smoothed latent signal with a one-week reporting lag on the chatter
        lagged = np.vstack([np.zeros((1, C)), latent[:-1]])
        smooth_latent = 0.65 * latent + 0.35 * lagged

        baseline = 2.4 + 2.2 * np.log1p(
            np.array([self.countries[c].livestock.get("chickens", 1000.0) for c in self.iso3]) / 50_000.0
        )
        return (
            baseline[None, :]
            + 1.55 * chatter_weight[None, :] * smooth_latent
            + 2.30 * echo
        )

    def _write_gdelt(self, sim: _SimulationResult) -> pd.DataFrame:
        """GDELT-style DAILY raw article volume.

        Raw counts only. Turning volume into an anomaly (abnormal volume,
        source diversity, acceleration) is the adapter's job -- a raw count is
        not a probability and must never be treated as one.
        """
        rng = np.random.default_rng(self.seed + 202)
        rows: list[dict[str, Any]] = []
        for code in self.diseases:
            intensity = self._media_intensity(sim, code)
            for t, week in enumerate(self.weeks):
                for ci, iso in enumerate(self.iso3):
                    weekly = max(intensity[t, ci], 0.05)
                    # distribute the week over days with weekday-heavy news cycle
                    day_weights = np.array([1.15, 1.2, 1.15, 1.1, 1.0, 0.7, 0.7])
                    day_weights = day_weights / day_weights.sum()
                    for d in range(7):
                        day = week + timedelta(days=d)
                        if day > self.cutoff:
                            continue
                        lam = weekly * day_weights[d]
                        n_articles = int(rng.poisson(lam))
                        if n_articles == 0 and rng.random() > 0.22:
                            continue
                        n_sources = int(min(n_articles, 1 + rng.binomial(max(n_articles, 1), 0.55)))
                        rows.append(
                            {
                                "date": day.isoformat(),
                                "iso3": iso,
                                "country": self.countries[iso].name,
                                "theme": f"ANIMAL_DISEASE_{code}",
                                "disease_code": code,
                                "n_articles": n_articles,
                                "n_distinct_sources": n_sources,
                                "n_languages": int(1 + rng.binomial(3, 0.35)),
                                "avg_tone": round(float(rng.normal(-3.2, 1.8)), 3),
                                "query": f"gdelt:doc:theme=ANIMAL_DISEASE_{code}&country={iso}",
                                "data_realism": "synthetic",
                            }
                        )
        return pd.DataFrame(rows)

    def _write_padiweb(self, sim: _SimulationResult) -> pd.DataFrame:
        """PADI-web style extracted news events with relevance scoring."""
        rng = np.random.default_rng(self.seed + 303)
        rows: list[dict[str, Any]] = []
        counter = 0
        for code in self.diseases:
            intensity = self._media_intensity(sim, code)
            for t, week in enumerate(self.weeks):
                for ci, iso in enumerate(self.iso3):
                    n = rng.poisson(max(intensity[t, ci], 0.05) * 0.30)
                    for _ in range(int(n)):
                        counter += 1
                        pub = week + timedelta(days=int(rng.integers(0, 7)))
                        if pub > self.cutoff:
                            continue
                        relevance = float(np.clip(rng.beta(4.0, 2.2), 0.0, 1.0))
                        rows.append(
                            {
                                "article_id": f"PADI-{counter:07d}",
                                "published_date": pub.isoformat(),
                                "extracted_date": (pub + timedelta(days=1)).isoformat(),
                                "iso3": iso,
                                "country": self.countries[iso].name,
                                "disease_code": code,
                                "disease_mention": self.diseases[code].name,
                                "relevance_score": round(relevance, 3),
                                "is_epidemiological_event": bool(relevance > 0.45),
                                "host_mention": str(rng.choice(self.diseases[code].species))
                                if self.diseases[code].species else "unknown",
                                "language": str(rng.choice(["en", "fr", "es", "ru"], p=[0.6, 0.18, 0.12, 0.10])),
                                "source_outlet": f"outlet_{int(rng.integers(1, 48)):02d}",
                                "title": f"[SYNTHETIC] Reports of {code} activity in {self.countries[iso].name}",
                                "data_realism": "synthetic",
                            }
                        )
        return pd.DataFrame(rows)

    def _write_promed(self, sim: _SimulationResult) -> pd.DataFrame:
        """ProMED-mail style curated posts (sparse, high specificity)."""
        rng = np.random.default_rng(self.seed + 404)
        rows: list[dict[str, Any]] = []
        counter = 0
        for code in self.diseases:
            latent = sim.latent[code]
            for t, week in enumerate(self.weeks):
                for ci, iso in enumerate(self.iso3):
                    p = 1.0 - np.exp(-0.16 * latent[t, ci])
                    if rng.random() > p:
                        continue
                    counter += 1
                    pub = week + timedelta(days=int(rng.integers(2, 12)))
                    if pub > self.cutoff:
                        continue
                    rows.append(
                        {
                            "post_id": f"PROMED-{counter:06d}",
                            "archive_number": f"2024{counter:06d}.{counter % 1000:04d}",
                            "published_date": pub.isoformat(),
                            "iso3": iso,
                            "country": self.countries[iso].name,
                            "disease_code": code,
                            "subject": f"[SYNTHETIC] {code}, animal - {self.countries[iso].name}",
                            "curator_comment_present": bool(rng.random() < 0.6),
                            "confidence": str(rng.choice(["confirmed", "suspected", "unverified"], p=[0.45, 0.35, 0.20])),
                            "data_realism": "synthetic",
                        }
                    )
        return pd.DataFrame(rows)

    def _write_healthmap(self, sim: _SimulationResult) -> pd.DataFrame:
        """HealthMap style geo-coded alerts aggregated from feeds."""
        rng = np.random.default_rng(self.seed + 505)
        rows: list[dict[str, Any]] = []
        counter = 0
        for code in self.diseases:
            intensity = self._media_intensity(sim, code)
            for t, week in enumerate(self.weeks):
                for ci, iso in enumerate(self.iso3):
                    n = rng.poisson(max(intensity[t, ci], 0.05) * 0.16)
                    for _ in range(int(n)):
                        counter += 1
                        pub = week + timedelta(days=int(rng.integers(0, 7)))
                        if pub > self.cutoff:
                            continue
                        spec = self.countries[iso]
                        lat, lon = jitter_point(
                            spec.lat, spec.lon, radius_km=country_radius_km(spec.area_km2), rng=rng
                        )
                        rows.append(
                            {
                                "alert_id": f"HM-{counter:07d}",
                                "published_date": pub.isoformat(),
                                "iso3": iso,
                                "country": spec.name,
                                "disease_code": code,
                                "latitude": round(lat, 3),
                                "longitude": round(lon, 3),
                                "feed": str(rng.choice(["news", "official", "social"], p=[0.7, 0.2, 0.1])),
                                "duplicate_of_feed_item": bool(rng.random() < 0.34),
                                "headline": f"[SYNTHETIC] {code} signal near {spec.name}",
                                "data_realism": "synthetic",
                            }
                        )
        return pd.DataFrame(rows)

    def _write_beacon(self, sim: _SimulationResult) -> pd.DataFrame:
        """BEACON style screened epidemic-intelligence signals.

        Signals carry a verification state; unverified ones are more numerous
        and noisier, which is exactly the trade-off the fusion model must learn
        to weight rather than take at face value.
        """
        rng = np.random.default_rng(self.seed + 606)
        rows: list[dict[str, Any]] = []
        counter = 0
        for code in self.diseases:
            latent = sim.latent[code]
            intensity = self._media_intensity(sim, code)
            for t, week in enumerate(self.weeks):
                for ci, iso in enumerate(self.iso3):
                    lam = 0.08 + 0.22 * np.log1p(intensity[t, ci]) + 0.20 * latent[t, ci]
                    n = rng.poisson(lam)
                    for _ in range(int(n)):
                        counter += 1
                        detected = week + timedelta(days=int(rng.integers(0, 6)))
                        if detected > self.cutoff:
                            continue
                        verified = bool(rng.random() < 0.38)
                        rows.append(
                            {
                                "signal_id": f"BEACON-{counter:07d}",
                                "detected_date": detected.isoformat(),
                                "screened_date": (detected + timedelta(days=int(rng.integers(0, 3)))).isoformat(),
                                "iso3": iso,
                                "country": self.countries[iso].name,
                                "disease_code": code,
                                "signal_strength": round(float(np.clip(rng.beta(2.0, 3.0) + 0.05 * latent[t, ci], 0, 1)), 3),
                                "verification_status": "verified" if verified else "unverified",
                                "signal_type": str(rng.choice(
                                    ["unusual_mortality", "media_cluster", "trade_alert", "syndromic"],
                                    p=[0.35, 0.40, 0.10, 0.15])),
                                "underlying_sources": str(rng.choice(["media", "media;official", "official", "field"], p=[0.5, 0.25, 0.15, 0.10])),
                                "data_realism": "synthetic",
                            }
                        )
        return pd.DataFrame(rows)

    def _write_eios(self, sim: _SimulationResult) -> pd.DataFrame:
        """EIOS board items - MOCK.

        The real EIOS API is access-restricted. This file exists so that the
        adapter interface is exercised end to end; every row is labelled
        ``mock`` and the app displays it as such.
        """
        rng = np.random.default_rng(self.seed + 707)
        rows: list[dict[str, Any]] = []
        counter = 0
        for code in self.diseases:
            intensity = self._media_intensity(sim, code)
            for t, week in enumerate(self.weeks):
                for ci, iso in enumerate(self.iso3):
                    if rng.random() > 0.11 + 0.02 * np.log1p(intensity[t, ci]):
                        continue
                    counter += 1
                    seen = week + timedelta(days=int(rng.integers(0, 7)))
                    if seen > self.cutoff:
                        continue
                    rows.append(
                        {
                            "item_id": f"EIOS-MOCK-{counter:06d}",
                            "board": "Animal Health",
                            "first_seen_date": seen.isoformat(),
                            "iso3": iso,
                            "country": self.countries[iso].name,
                            "disease_code": code,
                            "n_articles_in_cluster": int(1 + rng.poisson(2.5)),
                            "relevance": round(float(rng.beta(2.5, 2.5)), 3),
                            "triage_state": str(rng.choice(["new", "under_review", "dismissed"], p=[0.5, 0.3, 0.2])),
                            "data_realism": "mock",
                        }
                    )
        return pd.DataFrame(rows)

    # -- environmental / exposure --------------------------------------- #
    def _write_era5(self, sim: _SimulationResult) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for t, week in enumerate(self.weeks):
            for ci, iso in enumerate(self.iso3):
                rows.append(
                    {
                        "week_start": week.isoformat(),
                        "iso3": iso,
                        "t2m_mean_c": round(float(sim.climate["t2m_mean_c"][t, ci]), 3),
                        "t2m_min_c": round(float(sim.climate["t2m_mean_c"][t, ci] - 4.6), 3),
                        "t2m_max_c": round(float(sim.climate["t2m_mean_c"][t, ci] + 5.1), 3),
                        "total_precipitation_mm": round(float(sim.climate["precip_mm_week"][t, ci]), 3),
                        "relative_humidity_pct": round(float(sim.climate["rel_humidity_pct"][t, ci]), 2),
                        "wind_speed_10m_ms": round(float(3.0 + 0.02 * sim.climate["precip_mm_week"][t, ci]), 3),
                        "aggregation": "country_area_weighted_mean",
                        "release_lag_days": int(self.config.get("features.availability_lag_days.environmental", 6)),
                        "data_realism": "synthetic",
                    }
                )
        return pd.DataFrame(rows)

    def _write_era5_land(self, sim: _SimulationResult) -> pd.DataFrame:
        """ERA5-Land subset: soil and surface variables at higher resolution."""
        rng = np.random.default_rng(self.seed + 808)
        rows: list[dict[str, Any]] = []
        for t, week in enumerate(self.weeks):
            for ci, iso in enumerate(self.iso3):
                t2m = sim.climate["t2m_mean_c"][t, ci]
                precip = sim.climate["precip_mm_week"][t, ci]
                rows.append(
                    {
                        "week_start": week.isoformat(),
                        "iso3": iso,
                        "skin_temperature_c": round(float(t2m + rng.normal(0.8, 0.4)), 3),
                        "soil_temperature_l1_c": round(float(t2m * 0.85 + rng.normal(1.2, 0.5)), 3),
                        "volumetric_soil_water_l1": round(float(np.clip(0.18 + 0.004 * precip + rng.normal(0, 0.015), 0.02, 0.6)), 4),
                        "snow_depth_m": round(float(max(0.0, (2.0 - t2m) * 0.012 + rng.normal(0, 0.004))), 4),
                        "aggregation": "country_area_weighted_mean",
                        "release_lag_days": int(self.config.get("features.availability_lag_days.environmental", 6)),
                        "data_realism": "synthetic",
                    }
                )
        return pd.DataFrame(rows)

    def _write_worldclim(self, sim: _SimulationResult) -> pd.DataFrame:
        """Static 1970-2000 style monthly climatology per country."""
        clim_t = sim.climate["t2m_climatology_c"]
        clim_p = sim.climate["precip_climatology_mm"]
        month_of_week = np.array([w.month for w in self.weeks])
        rows: list[dict[str, Any]] = []
        for ci, iso in enumerate(self.iso3):
            for month in range(1, 13):
                mask = month_of_week == month
                if not mask.any():
                    continue
                rows.append(
                    {
                        "iso3": iso,
                        "month": month,
                        "tavg_c": round(float(clim_t[mask, ci].mean()), 3),
                        "tmin_c": round(float(clim_t[mask, ci].mean() - 5.2), 3),
                        "tmax_c": round(float(clim_t[mask, ci].mean() + 5.6), 3),
                        "prec_mm": round(float(clim_p[mask, ci].mean() * 4.33), 2),
                        "reference_period": "1970-2000 (synthetic analogue)",
                        "data_realism": "synthetic",
                    }
                )
        return pd.DataFrame(rows)

    def _write_glw4(self, sim: _SimulationResult) -> pd.DataFrame:
        """Gridded Livestock of the World densities aggregated to country.

        Two *vintages* are emitted (a 2010 reference released in 2014 and a 2020
        reference released in 2022) so the point-in-time store has to choose the
        version that actually existed at each as-of date, exactly as it would
        with the real GLW releases.
        """
        rows: list[dict[str, Any]] = []
        vintages = [
            (2010, date(2014, 3, 1), 0.88, "GLW3"),
            (2020, date(2022, 6, 1), 1.00, "GLW4"),
        ]
        for iso in self.iso3:
            spec = self.countries[iso]
            area = max(spec.area_km2, 1.0)
            for ref_year, release, scale, version in vintages:
                for species, heads_thousand in spec.livestock.items():
                    heads = heads_thousand * 1000.0 * scale
                    rows.append(
                        {
                            "iso3": iso,
                            "country": spec.name,
                            "species": species,
                            "reference_year": ref_year,
                            "dataset_version": version,
                            "release_date": release.isoformat(),
                            "total_head": int(heads),
                            "density_head_per_km2": round(heads / area, 4),
                            "area_km2": area,
                            "layer": f"{species}_density",
                            "aggregation": "country_sum_of_grid_cells",
                            "data_realism": "synthetic",
                        }
                    )
        return pd.DataFrame(rows)

    def _write_faostat(self, sim: _SimulationResult) -> pd.DataFrame:
        """FAOSTAT style annual livestock stocks with a realistic release lag."""
        rng = np.random.default_rng(self.seed + 909)
        rows: list[dict[str, Any]] = []
        years = sorted({w.year for w in self.weeks})
        for iso in self.iso3:
            spec = self.countries[iso]
            for year in years:
                drift = float(np.exp(rng.normal(0.0, 0.035) + 0.012 * (year - years[0])))
                for species, heads_thousand in spec.livestock.items():
                    rows.append(
                        {
                            "iso3": iso,
                            "country": spec.name,
                            "year": year,
                            "item": species,
                            "element": "Stocks",
                            "unit": "1000 head",
                            "value": round(heads_thousand * drift, 1),
                            # FAOSTAT publishes year Y around mid Y+1
                            "release_date": date(year + 1, 7, 15).isoformat(),
                            "data_realism": "synthetic",
                        }
                    )
        return pd.DataFrame(rows)

    # -- ground truth (evaluation only) ---------------------------------- #
    def _write_truth(self, sim: _SimulationResult) -> pd.DataFrame:
        """Hidden latent state. NOT an input to any feature - evaluation only."""
        notified_week: dict[tuple[str, str, date], int] = {}
        for rec in sim.outbreak_records:
            key = (rec["disease"], rec["country_iso3"], rec["week_start"])
            notified_week[key] = notified_week.get(key, 0) + 1

        rows: list[dict[str, Any]] = []
        for code in self.diseases:
            multiplier = float(self.config.get(f"ascertainment.disease_multiplier.{code}", 1.0))
            for t, week in enumerate(self.weeks):
                for ci, iso in enumerate(self.iso3):
                    tier = self.countries[iso].surveillance_capacity
                    rows.append(
                        {
                            "week_start": week.isoformat(),
                            "iso3": iso,
                            "disease_code": code,
                            "entity_key": f"{iso}|{code}",
                            "true_latent_outbreaks": int(sim.latent[code][t, ci]),
                            "detected_outbreaks": int(sim.detected[code][t, ci]),
                            "eventually_notified_outbreaks": int(
                                notified_week.get((code, iso, week), 0)
                            ),
                            "true_ascertainment": round(
                                float(np.clip(_CAPACITY[tier][0] * multiplier, 0.02, 0.98)), 4
                            ),
                            "true_suitability": round(float(sim.suitability[code][t, ci]), 4),
                            "usage": "EVALUATION_ONLY__NEVER_A_FEATURE",
                            "data_realism": "synthetic",
                        }
                    )
        return pd.DataFrame(rows)

    # -- documentation ---------------------------------------------------- #
    def _write_readme(self, manifest: dict[str, Any]) -> None:
        lines = [
            "# SYNTHETIC SAMPLE CORPUS - NOT REAL DATA",
            "",
            "Every file in this directory is generated by",
            "`src/ingestion/sample_generator.py`. None of it describes real animal",
            "disease events, real countries' epidemiological situations, or real",
            "media coverage. It exists so the pipeline and dashboard can be run and",
            "validated completely offline.",
            "",
            f"- Seed: `{manifest['seed']}`",
            f"- Period: {manifest['period']['start']} to {manifest['period']['end']}",
            f"- Corpus cut-off (pipeline 'today'): {manifest['generated_for_cutoff']}",
            f"- Countries: {len(manifest['countries'])}",
            f"- Diseases: {', '.join(manifest['diseases'])}",
            "",
            "## How the corpus is built",
            "",
            "1. **Latent process** - a spatio-temporal Hawkes process generates the",
            "   true weekly outbreak counts from seasonality, climate suitability,",
            "   livestock exposure, within-country self-excitation and",
            "   distance-weighted cross-country spillover, with saturation.",
            "2. **Detection** - binomial thinning by a country-specific ascertainment",
            "   probability derived from the surveillance-capacity tier.",
            "3. **Reporting** - log-normal onset-to-notification delays split across",
            "   suspicion, confirmation and notification, then a publication lag.",
            "4. **Observation** - only outbreaks published on or before the cut-off",
            "   appear in `wahis_events_sample.csv`.",
            "",
            "Media and intelligence files are generated from the **latent** layer with",
            "a short lag, so they genuinely lead the official record. That lead is the",
            "signal the early-warning model is meant to exploit.",
            "",
            "## Ground truth",
            "",
            "`_ground_truth_latent_weekly.csv` contains the hidden latent state. It is",
            "consumed **only** by `src/evaluation`; `tests/leakage` asserts that no",
            "feature builder ever reads it.",
            "",
            "## Files",
            "",
        ]
        for filename, meta in manifest["files"].items():
            lines.append(f"- `{filename}` - adapter `{meta['adapter']}`, {meta['rows']:,} rows")
        lines.append("")
        (self.out_dir / "README_SAMPLE.md").write_text("\n".join(lines), encoding="utf-8")


def generate_sample_corpus(
    config: AppConfig | None = None, seed: int | None = None, force: bool = False
) -> dict[str, Any]:
    """Generate the sample corpus unless it already exists.

    Parameters
    ----------
    force:
        Regenerate even if ``data/sample/MANIFEST.json`` is present.
    """
    config = config or get_config()
    out_dir = ensure_dir(config.path("data_sample"))
    manifest_path = out_dir / SAMPLE_FILES["manifest"]
    if manifest_path.is_file() and not force:
        LOGGER.info("Sample corpus already present at %s (use --force to regenerate)", out_dir)
        import json

        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return SampleCorpusGenerator(config=config, seed=seed).generate()
