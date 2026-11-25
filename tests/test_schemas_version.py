from pytest import mark, raises
from pydantic import ValidationError

from app.schemas.version import VersionResponse

LOCAL_VERSION = {
    "service": "backend",
    "sha": "unknown",
    "built_at": None,
    "version": "1.0.0",
    "tag": None,
}


@mark.parametrize("field", LOCAL_VERSION)
def test_requires_each_version_field(field: str) -> None:
    payload = LOCAL_VERSION.copy()
    del payload[field]

    with raises(ValidationError) as error:
        VersionResponse.model_validate(payload)

    assert error.value.errors()[0]["loc"] == (field,)
    assert error.value.errors()[0]["type"] == "missing"


def test_accepts_null_timestamp_and_tag() -> None:
    assert VersionResponse.model_validate(LOCAL_VERSION).model_dump() == LOCAL_VERSION


def test_rejects_other_service_names() -> None:
    with raises(ValidationError) as error:
        VersionResponse.model_validate({**LOCAL_VERSION, "service": "ops"})

    assert error.value.errors()[0]["loc"] == ("service",)
    assert error.value.errors()[0]["type"] == "literal_error"
