from app.settings import mask_secret, merge_settings_payload, redact_settings


def test_masks_secret_values():
    assert mask_secret("abcdef1234567890") == "abcdef********7890"
    assert mask_secret("short") == "configured"
    assert mask_secret("") is None


def test_merges_allowed_settings_only():
    current = {"makerworks": {"base_url": "http://old"}}
    result = merge_settings_payload(current, {"makerworks": {"base_url": "http://new"}})
    assert result["makerworks"]["base_url"] == "http://new"


def test_rejects_unknown_settings_section():
    try:
        merge_settings_payload({}, {"unknown": {"x": "y"}})
    except ValueError as exc:
        assert "Unknown settings section" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_redacted_settings_hide_youtube_refresh_token():
    redacted = redact_settings({"youtube": {"refresh_token": "refresh-token-123456"}})
    assert redacted["youtube"]["refresh_token"]["configured"] is True
    assert "refresh-token-123456" not in str(redacted)
