from app.schemas.score import ScoreResponse


def test_score_response_supports_region_and_context_codes() -> None:
    payload = ScoreResponse(
        score=72,
        verdict="high",
        label_code="score.label.high",
        context_code="score.context.high.stable_window",
        context_params={"cloud_base_gap_m": 250},
        cloud_base=1200,
        peak_slug="moucherotte",
        prediction_id="pred-uuid-1",
        optimal_window_start="06:30",
        optimal_window_end="08:00",
        sunrise="06:42",
        stability_hours=36,
        conditions={
            "cloud_base_score": 1.0,
            "humidity_score": 0.9,
            "wind_score": 0.8,
            "inversion_score": 0.7,
            "pressure_score": 0.6,
            "cloud_base_m": 1200,
            "humidity_pct": 94.0,
            "wind_speed_kmh": 8.0,
            "inversion_delta_c": 4.0,
            "inversion_detected": True,
            "pressure_hpa": 1025.0,
            "cloud_cover_low_pct": 80.0,
        },
        cloud_layer_viz={
            "summit_altitude": 1901,
            "cloud_base": 1200,
            "pressure_levels": [],
        },
        peak_name="Moucherotte",
        peak_altitude=1901,
        peak_region="Massif du Vercors",
    )

    assert payload.peak_region == "Massif du Vercors"
    assert payload.context_code == "score.context.high.stable_window"
