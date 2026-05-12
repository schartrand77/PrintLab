from __future__ import annotations

from pathlib import Path


def test_all_bambu_printer_models_have_static_thumbnails() -> None:
    asset_dir = Path("app/static/printers")
    expected = {
        "a1",
        "a1mini",
        "h2c",
        "h2d",
        "h2dpro",
        "h2s",
        "p1p",
        "p1s",
        "p2s",
        "x1",
        "x1c",
        "x1e",
    }

    missing = [slug for slug in sorted(expected) if not (asset_dir / f"{slug}.svg").exists()]

    assert missing == []


def test_gallery_uses_model_specific_printer_thumbnail_fallbacks() -> None:
    source = Path("app/views.py").read_text(encoding="utf-8")

    assert "printerThumbnailUrl(item.device_type)" in source
    assert "const previewFallback = printerThumbnailUrl(item.device_type)" in source
    assert "item.job?.thumbnail_url || previewFallback" in source
    assert "this.src='${escapeHtml(previewFallback)}'" in source
    assert "this.src=printerThumbnailUrl(item.device_type)" not in source


def test_add_printer_form_exposes_bambu_device_types() -> None:
    source = Path("app/views.py").read_text(encoding="utf-8")

    assert 'id="printerDeviceType"' in source
    for device_type in ("A1", "A1MINI", "P1P", "P1S", "P2S", "H2C", "H2D", "H2DPRO", "H2S", "X1", "X1C", "X1E"):
        assert f'value="{device_type}"' in source
    assert "device_type: document.getElementById('printerDeviceType').value" in source
    assert "document.getElementById('printerDeviceType').value = settings.device_type || 'X1C'" in source
