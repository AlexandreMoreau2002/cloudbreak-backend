from app.services import analytics


PEAK_ID = "550e8400-e29b-41d4-a716-446655440000"
PREDICTION_ID = "01890f8e-65d7-4ee6-8df7-6e43c391ee62"


class FakePosthog:
    def __init__(self, api_key: str, host: str, disable_geoip: bool, **options: object) -> None:
        self.api_key = api_key
        self.host = host
        self.disable_geoip = disable_geoip
        self.options = options
        self.captures: list[dict[str, object]] = []
        self.shutdown_called = False

    def capture(self, event: str, distinct_id: str, properties: dict[str, object]) -> None:
        self.captures.append({"event": event, "distinct_id": distinct_id, "properties": properties})

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_empty_configuration_keeps_analytics_disabled(monkeypatch) -> None:
    monkeypatch.setattr(analytics, "_client", None)

    analytics.initialize_analytics("", "")
    analytics.track("score_calculated", "user-1", {"score": 88})

    assert analytics._client is None


def test_track_captures_only_whitelisted_properties(monkeypatch) -> None:
    clients: list[FakePosthog] = []

    def build_client(*args, **kwargs) -> FakePosthog:
        client = FakePosthog(*args, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(analytics, "Posthog", build_client)
    monkeypatch.setattr(analytics, "_client", None)

    analytics.initialize_analytics("project-token", "https://eu.i.posthog.com")
    analytics.track(
        "score_calculated",
        "user-1",
        {
            "peak_id": PEAK_ID,
            "score": 88,
            "plan": "free",
            "verdict": "high",
            "note": "never send this",
        },
    )

    assert clients[0].disable_geoip is True
    assert clients[0].options == {
        "capture_trace_context": False,
        "enable_exception_autocapture": False,
        "enable_local_evaluation": False,
        "privacy_mode": True,
    }
    assert clients[0].captures == [
        {
            "event": "score_calculated",
            "distinct_id": "user-1",
            "properties": {"peak_id": PEAK_ID, "score": 88, "plan": "free", "verdict": "high"},
        }
    ]


def test_track_ignores_unknown_events_and_unsafe_properties(monkeypatch) -> None:
    client = FakePosthog("project-token", "https://eu.i.posthog.com", disable_geoip=True)
    monkeypatch.setattr(analytics, "_client", client)

    analytics.track("auth_submitted", "user-1", {"error_code": "email@example.invalid"})
    analytics.track("score_calculated", "user-1", {"score": "eighty-eight"})

    assert client.captures == []


def test_track_rejects_free_text_and_out_of_range_known_properties(monkeypatch) -> None:
    client = FakePosthog("project-token", "https://eu.i.posthog.com", disable_geoip=True)
    monkeypatch.setattr(analytics, "_client", client)

    analytics.track(
        "score_calculated",
        "user-1",
        {"peak_id": "alex@example.invalid", "score": 88, "plan": "free", "verdict": "high"},
    )
    analytics.track(
        "score_calculated",
        "user-1",
        {"peak_id": PEAK_ID, "score": 101, "plan": "contact me", "verdict": "high"},
    )
    analytics.track(
        "terrain_validated",
        "user-1",
        {"prediction_id": "message libre", "result": True},
    )
    analytics.track(
        "score_week_calculated",
        "user-1",
        {"peak_id": PEAK_ID, "cell_count": 64, "plan": "free"},
    )

    assert client.captures == []


def test_track_captures_valid_uuid_enums_and_bounded_values(monkeypatch) -> None:
    client = FakePosthog("project-token", "https://eu.i.posthog.com", disable_geoip=True)
    monkeypatch.setattr(analytics, "_client", client)

    analytics.track(
        "score_calculated",
        "user-1",
        {"peak_id": PEAK_ID, "score": 100, "plan": "premium", "verdict": "high"},
    )
    analytics.track(
        "score_week_calculated",
        "user-1",
        {"peak_id": PEAK_ID, "cell_count": 63, "plan": "pro"},
    )
    analytics.track(
        "terrain_validated",
        "user-1",
        {"prediction_id": PREDICTION_ID, "result": False},
    )

    assert client.captures == [
        {
            "event": "score_calculated",
            "distinct_id": "user-1",
            "properties": {"peak_id": PEAK_ID, "score": 100, "plan": "premium", "verdict": "high"},
        },
        {
            "event": "score_week_calculated",
            "distinct_id": "user-1",
            "properties": {"peak_id": PEAK_ID, "cell_count": 63, "plan": "pro"},
        },
        {
            "event": "terrain_validated",
            "distinct_id": "user-1",
            "properties": {"prediction_id": PREDICTION_ID, "result": False},
        },
    ]


def test_shutdown_only_runs_for_an_initialized_client(monkeypatch) -> None:
    monkeypatch.setattr(analytics, "_client", None)
    analytics.shutdown_analytics()

    client = FakePosthog("project-token", "https://eu.i.posthog.com", disable_geoip=True)
    monkeypatch.setattr(analytics, "_client", client)
    analytics.shutdown_analytics()

    assert client.shutdown_called is True
    assert analytics._client is None
