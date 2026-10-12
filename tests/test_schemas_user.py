import pytest
from pydantic import ValidationError

from app.schemas.user import PushTokenUpdate


@pytest.mark.parametrize("token", ["ExponentPushToken[abc123]", "ExpoPushToken[a_B-9]"])
def test_push_token_accepts_expo_format(token: str) -> None:
    assert PushTokenUpdate(push_token=token).push_token == token


@pytest.mark.parametrize(
    "token",
    [
        "",
        "abc",
        "ExponentPushToken[]",
        "ExpoPushToken[]",
        "ExponentPushToken[",
        "ExponentPushToken[a b]",
        "ExponentPushToken[ab]\n",
        "ExponentPushToken[a\nb]",
        " ExponentPushToken[ab]",
        "ExponentPushToken[a[b]]",
        "ExponentPushToken[a]]",
        "ExponentPushToken[é]",
        "ExponentPushToken[日本]",
        "ExponentPushToken[a.b]",
        "xExponentPushToken[ab]",
        "ExponentPushToken[" + "a" * 300 + "]",
    ],
)
def test_push_token_rejects_invalid_format(token: str) -> None:
    with pytest.raises(ValidationError):
        PushTokenUpdate(push_token=token)


def test_push_token_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PushTokenUpdate(push_token="ExponentPushToken[a]", other=1)  # type: ignore[call-arg]


def test_push_token_locale_accepts_supported_values() -> None:
    assert PushTokenUpdate(push_token="ExponentPushToken[a]", locale="en").locale == "en"
    assert PushTokenUpdate(push_token="ExponentPushToken[a]", locale="fr").locale == "fr"


def test_push_token_locale_is_optional() -> None:
    assert PushTokenUpdate(push_token="ExponentPushToken[a]").locale is None


@pytest.mark.parametrize("locale", ["de", "EN", "", "fr-FR"])
def test_push_token_locale_rejects_unsupported_values(locale: str) -> None:
    with pytest.raises(ValidationError):
        PushTokenUpdate(push_token="ExponentPushToken[a]", locale=locale)  # type: ignore[arg-type]
