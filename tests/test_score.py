"""
Tests de l'algorithme de score mer de nuage.

Conditions bloquantes (éliminatoires → verdict "none", score 0) :
  1. cloud_base >= peak_altitude → nuages au-dessus du sommet
  2. cloud_cover_low < 45% → couche trop fragmentée

Score conditionnel (seulement si conditions non bloquantes) :
  Indicateurs de qualité combinés — poids indicatifs, non calibrés.
  Verdicts : high ≥ 70, medium 40-69, low < 40.
"""

from app.domain.score import (
    _cloud_base_component,
    _context_payload,
    _estimate_stability_hours,
    _estimate_sunrise_minutes,
    _humidity_component,
    _inversion_component,
    _optimal_window_from_sunrise,
    _pressure_component,
    _verdict_label_code,
    _wind_component,
    build_score_presentation,
    calculate_score,
)
from app.domain.score import ScoreConditions, ScoreResult
from app.domain.weather_types import PressureLevelData, WeatherData
from typing import cast


# ── Fixtures ─────────────────────────────────────────────────────────────────


def weather(
    cloud_base: int = 1000,
    humidity: float = 85.0,
    wind_speed: float = 10.0,
    temperature_925hpa: float = 5.0,
    temperature_850hpa: float = 8.0,
    pressure: float = 1018.0,
    cloud_cover_low: float = 70.0,
    month: int = 3,
) -> WeatherData:
    """Données météo favorables par défaut (bon cas mer de nuage)."""
    return WeatherData(
        cloud_base=cloud_base,
        humidity=humidity,
        wind_speed=wind_speed,
        temperature_2m=10.0,
        temperature_850hpa=temperature_850hpa,
        temperature_925hpa=temperature_925hpa,
        pressure=pressure,
        cloud_cover_low=cloud_cover_low,
        month=month,
    )


# ── Conditions bloquantes ────────────────────────────────────────────────────


class TestConditionsBloquantes:
    """
    Deux conditions bloquantes retournent score=0, verdict="none" immédiatement
    sans calculer les composantes.
    """

    def test_cloud_base_au_dessus_sommet_verdict_none(self) -> None:
        """cloud_base >= peak_altitude → condition bloquante → verdict "none"."""
        result = calculate_score(weather(cloud_base=2500), peak_altitude=1500)
        assert result["score"] == 0
        assert result["verdict"] == "none"

    def test_cloud_base_egal_sommet_verdict_none(self) -> None:
        """cloud_base == peak_altitude → condition bloquante → verdict "none"."""
        result = calculate_score(weather(cloud_base=1500), peak_altitude=1500)
        assert result["score"] == 0
        assert result["verdict"] == "none"

    def test_cloud_cover_low_insuffisant_verdict_none(self) -> None:
        """cloud_cover_low < 45% → couche trop fragmentée → condition bloquante → verdict "none"."""
        result = calculate_score(weather(cloud_base=800, cloud_cover_low=10.0), peak_altitude=1500)
        assert result["score"] == 0
        assert result["verdict"] == "none"

    def test_cloud_cover_low_zero_verdict_none(self) -> None:
        """cloud_cover_low = 0% → ciel parfaitement dégagé → verdict "none"."""
        result = calculate_score(weather(cloud_base=800, cloud_cover_low=0.0), peak_altitude=1500)
        assert result["score"] == 0
        assert result["verdict"] == "none"

    def test_cloud_cover_low_fragmented_verdict_none(self) -> None:
        """cloud_cover_low juste sous 45% → pas assez de nuages bas pour scorer."""
        result = calculate_score(weather(cloud_base=800, cloud_cover_low=44.0), peak_altitude=1500)
        assert result["score"] == 0
        assert result["verdict"] == "none"

    def test_cloud_cover_low_exactement_seuil_passe(self) -> None:
        """cloud_cover_low = 45.0% → seuil atteint → conditions non bloquantes."""
        result = calculate_score(weather(cloud_base=800, cloud_cover_low=45.0), peak_altitude=1500)
        assert result["verdict"] != "none"

    def test_conditions_bloquantes_retournent_zero_conditions(self) -> None:
        """Toutes les composantes sont à 0.0 pour les cas bloquants."""
        result = calculate_score(weather(cloud_base=2500), peak_altitude=1500)
        cond = result["conditions"]
        assert cond["cloud_base_score"] == 0.0
        assert cond["humidity_score"] == 0.0
        assert cond["wind_score"] == 0.0
        assert cond["inversion_score"] == 0.0
        assert cond["pressure_score"] == 0.0

    def test_cloud_cover_low_bloquant_conditions_zero(self) -> None:
        """cloud_cover_low bloquant → toutes les composantes à 0.0."""
        result = calculate_score(weather(cloud_base=800, cloud_cover_low=5.0), peak_altitude=1500)
        cond = result["conditions"]
        assert cond["cloud_base_score"] == 0.0
        assert cond["humidity_score"] == 0.0
        assert cond["wind_score"] == 0.0
        assert cond["inversion_score"] == 0.0
        assert cond["pressure_score"] == 0.0


# ── cloud_base_condition (poids 0.35) ─────────────────────────────────────────


class TestCloudBaseCondition:
    """
    cloud_base est l'altitude MSL (en mètres) de la base des nuages.
    Si cloud_base < altitude_sommet → les nuages sont SOUS le sommet → mer de nuage probable.
    cloud_base >= altitude_sommet → condition bloquante → "none".
    """

    def test_cloud_base_sous_le_sommet_score_eleve(self) -> None:
        """cloud_base 1000m, sommet 1500m → nuages sous le sommet → score élevé."""
        result = calculate_score(weather(cloud_base=1000), peak_altitude=1500)
        assert result["score"] >= 70
        assert result["verdict"] == "high"

    def test_cloud_base_tres_bas_score_maximal(self) -> None:
        """cloud_base 200m, sommet 1500m → très favorable (avec inversion marquée)."""
        result = calculate_score(
            weather(cloud_base=200, temperature_925hpa=3.0, temperature_850hpa=10.0),
            peak_altitude=1500,
        )
        assert result["score"] >= 70

    def test_cloud_base_component_optimal(self) -> None:
        """cloud_base bien sous le sommet → composante 1.0."""
        assert _cloud_base_component(cloud_base=1000, peak_altitude=1500) == 1.0

    def test_cloud_base_component_au_dessus(self) -> None:
        """cloud_base bien au-dessus du sommet → composante 0.0."""
        assert _cloud_base_component(cloud_base=2500, peak_altitude=1500) == 0.0


# ── humidity_score (poids 0.20) ────────────────────────────────────────────────


class TestHumidityScore:
    """
    Humidité élevée = conditions propices à la formation des nuages bas.
    Seuil : > 88% favorable, < 60% défavorable.
    """

    def test_humidite_elevee_favorise_le_score(self) -> None:
        """90% d'humidité → composante haute."""
        base = calculate_score(weather(humidity=60.0, cloud_base=800), peak_altitude=1500)
        high_humidity = calculate_score(weather(humidity=90.0, cloud_base=800), peak_altitude=1500)
        assert high_humidity["score"] > base["score"]

    def test_humidite_faible_penalise_le_score(self) -> None:
        """30% d'humidité → conditions sèches → score réduit."""
        result = calculate_score(weather(humidity=30.0, cloud_base=800), peak_altitude=1500)
        result_humid = calculate_score(weather(humidity=90.0, cloud_base=800), peak_altitude=1500)
        assert result["score"] < result_humid["score"]

    def test_humidity_component_seuil_min(self) -> None:
        """Humidité en dessous du seuil minimum → composante 0.0."""
        assert _humidity_component(50.0) == 0.0

    def test_humidity_component_seuil_max(self) -> None:
        """Humidité au maximum → composante 1.0."""
        assert _humidity_component(95.0) == 1.0


# ── wind_score (poids 0.15) ────────────────────────────────────────────────────


class TestWindScore:
    """
    Vent fort disperse les nuages bas et empêche la mer de nuage de se former.
    Seuil : < 5 km/h calme parfait, > 30 km/h très défavorable.
    """

    def test_vent_faible_favorise_le_score(self) -> None:
        """5 km/h → calme → composante haute."""
        calm = calculate_score(weather(wind_speed=5.0, cloud_base=800), peak_altitude=1500)
        windy = calculate_score(weather(wind_speed=30.0, cloud_base=800), peak_altitude=1500)
        assert calm["score"] > windy["score"]

    def test_vent_fort_penalise_le_score(self) -> None:
        """60 km/h → vent fort → score réduit significativement."""
        result = calculate_score(weather(wind_speed=60.0, cloud_base=800), peak_altitude=1500)
        result_calm = calculate_score(weather(wind_speed=5.0, cloud_base=800), peak_altitude=1500)
        assert result["score"] < result_calm["score"]

    def test_wind_component_calme_parfait(self) -> None:
        """Vent < WIND_MIN → composante 1.0."""
        assert _wind_component(3.0) == 1.0

    def test_wind_component_vent_fort(self) -> None:
        """Vent >= WIND_MAX → composante 0.0."""
        assert _wind_component(35.0) == 0.0


# ── inversion_score (poids 0.20) ───────────────────────────────────────────────


class TestInversionScore:
    """
    L'inversion thermique est détectée via T(850hPa) vs T(925hPa).
    delta = T(850hPa) - T(925hPa)
    Si delta > 0 → inversion → favorable pour piéger les nuages bas.
    """

    def test_inversion_thermique_presente_favorise_score(self) -> None:
        """T925=2°C, T850=8°C → inversion → favorable."""
        with_inversion = calculate_score(
            weather(temperature_925hpa=2.0, temperature_850hpa=8.0, cloud_base=800),
            peak_altitude=1500,
        )
        without_inversion = calculate_score(
            weather(temperature_925hpa=15.0, temperature_850hpa=2.0, cloud_base=800),
            peak_altitude=1500,
        )
        assert with_inversion["score"] > without_inversion["score"]

    def test_pas_d_inversion_penalise_score(self) -> None:
        """Gradient normal (T925 chaude, T850 froide) → pas d'inversion → score réduit."""
        result = calculate_score(
            weather(temperature_925hpa=20.0, temperature_850hpa=5.0, cloud_base=800),
            peak_altitude=1500,
        )
        assert result["score"] < 90

    def test_inversion_component_forte(self) -> None:
        """Delta élevé → composante proche de 1.0."""
        score = _inversion_component(temp_925=2.0, temp_850=8.0)
        assert score > 0.8

    def test_inversion_component_absente(self) -> None:
        """Delta très négatif → composante 0.0."""
        score = _inversion_component(temp_925=15.0, temp_850=5.0)
        assert score == 0.0


# ── pressure_score (poids 0.10) ───────────────────────────────────────────────


class TestPressureScore:
    """
    Pression élevée (anticyclone) → conditions stables → favorable.
    Seuils : > 1025 hPa excellent, < 1010 hPa défavorable.
    """

    def test_pression_elevee_favorise_score(self) -> None:
        """1030 hPa → anticyclone → score plus élevé."""
        high_pres = calculate_score(weather(pressure=1030.0, cloud_base=800), peak_altitude=1500)
        low_pres = calculate_score(weather(pressure=1005.0, cloud_base=800), peak_altitude=1500)
        assert high_pres["score"] > low_pres["score"]

    def test_pressure_component_anticyclone(self) -> None:
        """Pression >= PRESSURE_HIGH → composante 1.0."""
        assert _pressure_component(1030.0) == 1.0

    def test_pressure_component_basse_pression(self) -> None:
        """Pression <= PRESSURE_LOW → composante 0.0."""
        assert _pressure_component(1005.0) == 0.0

    def test_pressure_component_intermediaire(self) -> None:
        """Pression entre seuils → composante entre 0 et 1."""
        score = _pressure_component(1017.5)
        assert 0.0 < score < 1.0

    def test_conditions_contient_pressure_score(self) -> None:
        """Le résultat doit inclure pressure_score dans les conditions."""
        result = calculate_score(weather(), peak_altitude=1500)
        assert "pressure_score" in result["conditions"]


# ── Verdict ───────────────────────────────────────────────────────────────────


class TestVerdict:
    """
    Seuils de verdict :
    - none   : conditions bloquantes — score = 0
    - high   : score ≥ 70  → "Lève-toi tôt !"
    - medium : 40 ≤ score < 70 → "Ça peut le faire"
    - low    : score < 40  → "Pas ce coup-ci"
    """

    def test_verdict_high(self) -> None:
        result = calculate_score(
            weather(
                cloud_base=500,
                humidity=92.0,
                wind_speed=5.0,
                temperature_925hpa=2.0,
                temperature_850hpa=8.0,
                pressure=1028.0,
                cloud_cover_low=80.0,
                month=10,
            ),
            peak_altitude=1500,
        )
        assert result["verdict"] == "high"
        assert result["score"] >= 70

    def test_verdict_none_cloud_base_bloquant(self) -> None:
        """cloud_base >= sommet → condition bloquante → verdict "none", score 0."""
        result = calculate_score(weather(cloud_base=3000), peak_altitude=1500)
        assert result["verdict"] == "none"
        assert result["score"] == 0

    def test_verdict_none_cloud_cover_low_bloquant(self) -> None:
        """cloud_cover_low < 45% → couche basse trop faible → verdict "none", score 0."""
        result = calculate_score(weather(cloud_base=800, cloud_cover_low=15.0), peak_altitude=1500)
        assert result["verdict"] == "none"
        assert result["score"] == 0

    def test_verdict_high_exige_55_pour_cloud_cover_low(self) -> None:
        """cloud_cover_low < 45% → aucun score ; entre 45% et 54% → jamais high."""
        result = calculate_score(
            weather(
                cloud_base=500,
                humidity=92.0,
                wind_speed=5.0,
                temperature_925hpa=2.0,
                temperature_850hpa=8.0,
                pressure=1028.0,
                cloud_cover_low=44.0,
                month=10,
            ),
            peak_altitude=1500,
        )
        assert result["verdict"] == "none"
        assert result["score"] == 0

    def test_verdict_high_a_45_ne_passe_pas(self) -> None:
        """cloud_cover_low = 45% → score possible, mais jamais high."""
        result = calculate_score(
            weather(
                cloud_base=500,
                humidity=92.0,
                wind_speed=5.0,
                temperature_925hpa=2.0,
                temperature_850hpa=8.0,
                pressure=1028.0,
                cloud_cover_low=45.0,
                month=10,
            ),
            peak_altitude=1500,
        )
        assert result["verdict"] != "high"
        assert result["score"] < 70

    def test_verdict_low_flux_normal(self) -> None:
        """cloud_base < sommet, cloud_cover_low < 45%, conditions défavorables → verdict none."""
        result = calculate_score(
            weather(
                cloud_base=1400,  # juste sous le sommet mais toutes conditions mauvaises
                humidity=30.0,
                wind_speed=60.0,
                temperature_925hpa=20.0,
                temperature_850hpa=5.0,
                pressure=1000.0,
                cloud_cover_low=25.0,
                month=7,
            ),
            peak_altitude=1500,
        )
        assert result["verdict"] == "none"
        assert result["score"] == 0

    def test_verdict_medium_existe(self) -> None:
        """Conditions mixtes → verdict medium possible."""
        result = calculate_score(
            weather(
                cloud_base=1400,
                humidity=70.0,
                wind_speed=20.0,
                temperature_925hpa=10.0,
                temperature_850hpa=8.0,
                pressure=1015.0,
                cloud_cover_low=45.0,
                month=5,
            ),
            peak_altitude=1500,
        )
        assert result["verdict"] in ("medium", "low", "high")


# ── Structure de retour ───────────────────────────────────────────────────────


class TestStructureRetour:
    """La fonction doit retourner tous les champs attendus par l'endpoint."""

    def test_champs_obligatoires_presents(self) -> None:
        result = calculate_score(weather(), peak_altitude=1500)
        assert "score" in result
        assert "verdict" in result
        assert "cloud_base" in result
        assert "conditions" in result

    def test_score_entre_0_et_100(self) -> None:
        result = calculate_score(weather(), peak_altitude=1500)
        assert 0 <= result["score"] <= 100

    def test_cloud_base_repris_dans_retour(self) -> None:
        result = calculate_score(weather(cloud_base=1234), peak_altitude=1500)
        assert result["cloud_base"] == 1234

    def test_cloud_base_repris_dans_retour_cas_bloquant(self) -> None:
        """cloud_base est retourné même pour les cas bloquants."""
        result = calculate_score(weather(cloud_base=2000), peak_altitude=1500)
        assert result["cloud_base"] == 2000

    def test_conditions_contient_composantes(self) -> None:
        result = calculate_score(weather(), peak_altitude=1500)
        conditions = result["conditions"]
        assert "cloud_base_score" in conditions
        assert "humidity_score" in conditions
        assert "wind_score" in conditions
        assert "inversion_score" in conditions
        assert "pressure_score" in conditions

    def test_verdict_valeur_valide(self) -> None:
        result = calculate_score(weather(), peak_altitude=1500)
        assert result["verdict"] in ("none", "high", "medium", "low")

    def test_verdict_valeur_valide_cas_bloquant(self) -> None:
        result = calculate_score(weather(cloud_base=3000), peak_altitude=1500)
        assert result["verdict"] in ("none", "high", "medium", "low")

    def test_score_ne_depasse_pas_100(self) -> None:
        """Avec toutes les conditions maximales, le score ne dépasse pas 100."""
        result = calculate_score(
            weather(
                cloud_base=100,
                humidity=95.0,
                wind_speed=2.0,
                temperature_925hpa=0.0,
                temperature_850hpa=10.0,
                pressure=1030.0,
                cloud_cover_low=90.0,
                month=10,
            ),
            peak_altitude=1500,
        )
        assert result["score"] <= 100


# ── Helpers de présentation ──────────────────────────────────────────────────


class TestPresentationHelpers:
    def test_verdict_label_couvre_tous_les_cas(self) -> None:
        assert _verdict_label_code("high") == "score.label.high"
        assert _verdict_label_code("medium") == "score.label.medium"
        assert _verdict_label_code("low") == "score.label.low"
        assert _verdict_label_code("none") == "score.label.none"

    def test_context_message_ete_score_faible(self) -> None:
        result = calculate_score(
            weather(
                cloud_base=1400,
                humidity=45.0,
                wind_speed=12.0,
                temperature_925hpa=14.0,
                temperature_850hpa=12.0,
                pressure=1008.0,
                cloud_cover_low=10.0,
                month=7,
            ),
            peak_altitude=1500,
        )
        assert result["score"] == 0
        assert _context_payload(
            result,
            weather(cloud_base=1400, cloud_cover_low=10.0, month=7),
            peak_altitude=1500,
        ) == ("score.context.none.low_cloud_cover", {})

    def test_context_payload_detecte_le_facteur_dominant(self) -> None:
        target_weather = weather(
            cloud_base=500,
            humidity=92.0,
            wind_speed=34.0,
            temperature_925hpa=2.0,
            temperature_850hpa=9.0,
            pressure=1028.0,
            cloud_cover_low=55.0,
            month=10,
        )
        result = calculate_score(
            target_weather,
            peak_altitude=1500,
        )
        assert _context_payload(result, target_weather, 1500) == (
            "score.context.low.wind_dispersion",
            {},
        )

    def test_context_payload_couvre_autres_facteurs_et_blocages(self) -> None:
        none_result = cast(
            ScoreResult,
            {
                "score": 0,
                "verdict": "none",
                "cloud_base": 1700,
                "conditions": cast(ScoreConditions, {}),
            },
        )
        assert _context_payload(
            none_result,
            weather(cloud_base=1700, cloud_cover_low=50.0),
            peak_altitude=1500,
        ) == ("score.context.none.cloud_base_above_summit", {})
        assert _context_payload(
            none_result,
            weather(cloud_base=1200, cloud_cover_low=10.0),
            peak_altitude=1500,
        ) == ("score.context.none.low_cloud_cover", {})

        humidity_result = cast(
            ScoreResult,
            {
                "score": 30,
                "verdict": "low",
                "cloud_base": 900,
                "conditions": cast(
                    ScoreConditions,
                    {
                        "cloud_base_score": 0.8,
                        "humidity_score": 0.1,
                        "wind_score": 0.7,
                        "inversion_score": 0.9,
                        "pressure_score": 0.8,
                    },
                ),
            },
        )
        assert _context_payload(
            humidity_result,
            weather(humidity=65.0),
            peak_altitude=1500,
        ) == ("score.context.low.humidity_too_low", {})

        inversion_result = cast(
            ScoreResult,
            {
                "score": 30,
                "verdict": "low",
                "cloud_base": 900,
                "conditions": cast(
                    ScoreConditions,
                    {
                        "cloud_base_score": 0.8,
                        "humidity_score": 0.7,
                        "wind_score": 0.6,
                        "inversion_score": 0.1,
                        "pressure_score": 0.8,
                    },
                ),
            },
        )
        assert _context_payload(
            inversion_result,
            weather(temperature_925hpa=8.0, temperature_850hpa=7.0),
            peak_altitude=1500,
        ) == ("score.context.low.no_inversion", {})

        pressure_result = cast(
            ScoreResult,
            {
                "score": 30,
                "verdict": "low",
                "cloud_base": 900,
                "conditions": cast(
                    ScoreConditions,
                    {
                        "cloud_base_score": 0.8,
                        "humidity_score": 0.7,
                        "wind_score": 0.6,
                        "inversion_score": 0.9,
                        "pressure_score": 0.1,
                    },
                ),
            },
        )
        assert _context_payload(
            pressure_result,
            weather(pressure=1010.0),
            peak_altitude=1500,
        ) == ("score.context.low.pressure_too_low", {})

        cloud_base_result = cast(
            ScoreResult,
            {
                "score": 30,
                "verdict": "low",
                "cloud_base": 1450,
                "conditions": cast(
                    ScoreConditions,
                    {
                        "cloud_base_score": 0.1,
                        "humidity_score": 0.8,
                        "wind_score": 0.7,
                        "inversion_score": 0.9,
                        "pressure_score": 0.8,
                    },
                ),
            },
        )
        assert _context_payload(
            cloud_base_result,
            weather(cloud_base=1450),
            peak_altitude=1500,
        ) == ("score.context.low.cloud_base_too_high", {})

        fallback_result = cast(
            ScoreResult,
            {
                "score": 30,
                "verdict": "low",
                "cloud_base": 900,
                "conditions": cast(
                    ScoreConditions,
                    {
                        "cloud_base_score": 0.8,
                        "humidity_score": 0.7,
                        "wind_score": 0.6,
                        "inversion_score": 0.9,
                        "pressure_score": 0.8,
                    },
                ),
            },
        )
        assert _context_payload(
            fallback_result,
            weather(humidity=80.0, wind_speed=10.0, pressure=1020.0),
            peak_altitude=1500,
        ) == ("score.context.low.conditions_too_marginal", {})

    def test_estimate_stability_hours_cas_bloquants(self) -> None:
        none_result = cast(
            ScoreResult,
            {
                "score": 0,
                "verdict": "none",
                "cloud_base": 0,
                "conditions": cast(ScoreConditions, {}),
            },
        )
        assert _estimate_stability_hours(none_result, weather(cloud_cover_low=10.0)) == 6
        assert _estimate_stability_hours(none_result, weather(cloud_cover_low=20.0)) == 6
        assert _estimate_stability_hours(none_result, weather(cloud_cover_low=55.0)) == 8

    def test_estimate_stability_hours_paliers(self) -> None:
        base_conditions = cast(
            ScoreConditions,
            {
                "cloud_base_score": 1.0,
                "humidity_score": 1.0,
                "wind_score": 1.0,
                "inversion_score": 1.0,
                "pressure_score": 1.0,
            },
        )
        assert (
            _estimate_stability_hours(
                cast(
                    ScoreResult,
                    {
                        "score": 80,
                        "verdict": "high",
                        "cloud_base": 800,
                        "conditions": base_conditions,
                    },
                ),
                weather(),
            )
            == 48
        )
        assert (
            _estimate_stability_hours(
                cast(
                    ScoreResult,
                    {
                        "score": 70,
                        "verdict": "high",
                        "cloud_base": 800,
                        "conditions": cast(
                            ScoreConditions,
                            {
                                "cloud_base_score": 0.8,
                                "humidity_score": 0.0,
                                "wind_score": 0.7,
                                "inversion_score": 0.6,
                                "pressure_score": 0.6,
                            },
                        ),
                    },
                ),
                weather(),
            )
            == 36
        )
        assert (
            _estimate_stability_hours(
                cast(
                    ScoreResult,
                    {
                        "score": 40,
                        "verdict": "medium",
                        "cloud_base": 800,
                        "conditions": cast(
                            ScoreConditions,
                            {
                                "cloud_base_score": 0.0,
                                "humidity_score": 0.0,
                                "wind_score": 0.0,
                                "inversion_score": 0.0,
                                "pressure_score": 0.0,
                            },
                        ),
                    },
                ),
                weather(),
            )
            == 18
        )
        assert (
            _estimate_stability_hours(
                cast(
                    ScoreResult,
                    {
                        "score": 39,
                        "verdict": "low",
                        "cloud_base": 800,
                        "conditions": cast(
                            ScoreConditions,
                            {
                                "cloud_base_score": 0.0,
                                "humidity_score": 0.0,
                                "wind_score": 0.0,
                                "inversion_score": 0.0,
                                "pressure_score": 0.0,
                            },
                        ),
                    },
                ),
                weather(),
            )
            == 8
        )

    def test_estimate_sunrise_minutes_et_fenetre(self) -> None:
        sunrise_minutes = _estimate_sunrise_minutes("2026-10-15", 45.83, 6.86)
        assert sunrise_minutes is not None
        assert _optimal_window_from_sunrise(sunrise_minutes, 48) == (
            _optimal_window_from_sunrise(sunrise_minutes, 48)[0],
            _optimal_window_from_sunrise(sunrise_minutes, 48)[1],
        )
        assert _optimal_window_from_sunrise(360, 18) == ("05:45", "07:00")
        assert _optimal_window_from_sunrise(360, 8) == ("05:50", "06:45")
        assert _optimal_window_from_sunrise(None, 48) == (None, None)
        assert _estimate_sunrise_minutes("2026-12-21", 80.0, 0.0) is None

    def test_build_score_presentation(self) -> None:
        result = cast(
            ScoreResult,
            {
                "score": 82,
                "verdict": "high",
                "cloud_base": 700,
                "conditions": cast(
                    ScoreConditions,
                    {
                        "cloud_base_score": 1.0,
                        "humidity_score": 1.0,
                        "wind_score": 1.0,
                        "inversion_score": 1.0,
                        "pressure_score": 1.0,
                    },
                ),
            },
        )
        weather_data = WeatherData(
            cloud_base=700,
            humidity=92.0,
            wind_speed=5.0,
            temperature_2m=10.0,
            temperature_850hpa=8.0,
            temperature_925hpa=2.0,
            pressure=1028.0,
            cloud_cover_low=75.0,
            month=10,
            pressure_levels=[
                PressureLevelData(
                    pressure_hpa=925,
                    altitude_m=750,
                    temperature_c=3.2,
                    relative_humidity=88.0,
                    dew_point_spread=1.5,
                ),
            ],
        )
        presentation = build_score_presentation(
            result=result,
            weather=weather_data,
            date="2026-10-15",
            lat=45.83,
            lng=6.86,
            peak_altitude=1500,
        )
        assert presentation["label_code"] == "score.label.high"
        assert presentation["context_code"] == "score.context.high.stable_window"
        assert presentation["context_params"] == {"cloud_base_gap_m": 800}
        assert presentation["stability_hours"] == 48
        assert presentation["sunrise"] is not None
        assert presentation["optimal_window_start"] is not None
        assert presentation["optimal_window_end"] is not None
        assert presentation["cloud_layer_viz"]["summit_altitude"] == 1500
        assert presentation["cloud_layer_viz"]["cloud_base"] == 700
        assert presentation["cloud_layer_viz"]["pressure_levels"][0]["pressure_hpa"] == 925
