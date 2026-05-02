from pathlib import Path


def test_makerworks_library_cards_use_proxied_thumbnails() -> None:
    html = Path("app/dashboard.html").read_text(encoding="utf-8")
    makerworks_section = html.split("async function loadMakerworksModels()", 1)[1].split("async function", 1)[0]

    assert "item.thumbnail_proxy_url || item.thumbnail_url || placeholderThumb" in makerworks_section
