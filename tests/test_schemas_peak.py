from app.schemas.peak import PeakResponse, PeakSearchResult


def test_peak_search_result_accepts_region() -> None:
    peak = PeakSearchResult(
        id="peak-1",
        name="Moucherotte",
        slug="moucherotte",
        altitude=1901,
        region="Massif du Vercors",
    )

    assert peak.region == "Massif du Vercors"


def test_peak_response_contains_coordinates() -> None:
    peak = PeakResponse(
        id="peak-1",
        name="Moucherotte",
        slug="moucherotte",
        lat=45.16,
        lng=5.64,
        altitude=1901,
    )

    assert peak.lat == 45.16
    assert peak.region is None
