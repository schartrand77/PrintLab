from __future__ import annotations

import importlib
import json
from pathlib import Path


def test_get_env_reads_from_config_json_section(monkeypatch) -> None:
    tmp_dir = Path("tests/.tmp/config-json")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    config_path = tmp_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "youtube": {
                    "upload_enabled": True,
                    "privacy_status": "unlisted",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("YOUTUBE_UPLOAD_ENABLED", raising=False)
    monkeypatch.delenv("YOUTUBE_PRIVACY_STATUS", raising=False)
    monkeypatch.setenv("PRINTLAB_CONFIG_PATH", str(config_path))

    import app.config as config_module

    importlib.reload(config_module)

    assert config_module.get_env("YOUTUBE_UPLOAD_ENABLED") == "true"
    assert config_module.get_env("YOUTUBE_PRIVACY_STATUS") == "unlisted"
