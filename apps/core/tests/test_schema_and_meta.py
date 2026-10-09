import pytest


@pytest.mark.django_db
def test_openapi_schema_and_swagger_are_served(anon_api) -> None:
    schema = anon_api.get("/api/schema/")
    docs = anon_api.get("/api/docs/")

    assert schema.status_code == 200
    body = schema.content.decode()
    for path in ("/api/v1/items", "/api/v1/reminder-rules/{item_type}", "/api/v1/telegram/webhook"):
        assert path in body
    assert docs.status_code == 200


@pytest.mark.django_db
def test_meta_app_is_public(anon_api, settings) -> None:
    settings.APP_MIN_SUPPORTED_VERSION = "1.2.0"
    settings.APP_DEVELOPER_NAME = "Dev Name"

    response = anon_api.get("/api/v1/meta/app")

    assert response.status_code == 200
    assert response.json()["min_supported_version"] == "1.2.0"
    assert response.json()["developer_name"] == "Dev Name"
    assert set(response.json()) == {
        "min_supported_version",
        "latest_version",
        "privacy_url",
        "support_telegram",
        "developer_name",
    }


def test_throttle_rate_parsing() -> None:
    from apps.core.api.throttling import LmsSyncThrottle

    assert LmsSyncThrottle().parse_rate("1/5m") == (1, 300)
    assert LmsSyncThrottle().parse_rate("10/day") == (10, 86400)
