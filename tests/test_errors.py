from app.core.errors import ErrorCode


def test_error_codes_are_stable_strings() -> None:
    assert ErrorCode.QUOTA_EXCEEDED == "QUOTA_EXCEEDED"
    assert ErrorCode.PEAK_NOT_FOUND == "PEAK_NOT_FOUND"
    assert ErrorCode.WEATHER_UNAVAILABLE == "WEATHER_UNAVAILABLE"
    assert ErrorCode.INVALID_TOKEN == "INVALID_TOKEN"


def test_error_codes_do_not_duplicate_values() -> None:
    values = [
        ErrorCode.QUOTA_EXCEEDED,
        ErrorCode.PEAK_NOT_FOUND,
        ErrorCode.WEATHER_UNAVAILABLE,
        ErrorCode.SUBSCRIPTION_REQUIRED,
        ErrorCode.INVALID_TOKEN,
        ErrorCode.TOKEN_EXPIRED,
        ErrorCode.NOT_FOUND,
        ErrorCode.INTERNAL_ERROR,
        ErrorCode.ALREADY_EXISTS,
    ]

    assert len(values) == len(set(values))
