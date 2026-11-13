from datetime import UTC, datetime

from app.schemas.favorite import FavoriteCreate, FavoriteResponse


def test_favorite_create_accepts_peak_id() -> None:
    payload = FavoriteCreate(peak_id="peak-1")

    assert payload.peak_id == "peak-1"


def test_favorite_response_nests_peak_payload() -> None:
    favorite = FavoriteResponse(
        id="fav-1",
        peak_id="peak-1",
        peak={
            "id": "peak-1",
            "name": "Moucherotte",
            "slug": "moucherotte",
            "altitude": 1901,
            "region": "Massif du Vercors",
        },
        created_at=datetime(2026, 3, 29, tzinfo=UTC),
    )

    assert favorite.peak.name == "Moucherotte"
    assert favorite.peak.region == "Massif du Vercors"
