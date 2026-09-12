from app.config import AppSettings


def test_meta_ids_and_api_version_are_loaded_from_expected_environment_names(
    monkeypatch,
) -> None:
    monkeypatch.setenv("META_WABA_ID", "waba-context-id")
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "phone-number-id")
    monkeypatch.setenv("META_API_VERSION", "v99.0")
    monkeypatch.setenv("META_ACCESS_TOKEN", "environment-token")

    settings = AppSettings()

    assert settings.meta_waba_id == "waba-context-id"
    assert settings.meta_phone_number_id == "phone-number-id"
    assert settings.meta_api_version == "v99.0"
    assert settings.meta_access_token == "environment-token"
