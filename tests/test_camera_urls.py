from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services import PrinterService


def _service(host: str = "192.168.1.20", access_code: str = "SECRET") -> PrinterService:
    return PrinterService(
        {
            "name": "Printer 1",
            "host": host,
            "serial": f"SERIAL-{uuid4().hex}",
            "access_code": access_code,
        },
        "printer-1",
        "Printer 1",
    )


def test_rtsp_urls_include_configured_host_and_auth_variants() -> None:
    service = _service()
    service.client = SimpleNamespace(
        _access_code="SECRET",
        get_device=lambda: SimpleNamespace(
            camera=SimpleNamespace(rtsp_url="rtsps://10.0.0.99:322/streaming/live/1")
        ),
    )

    assert service._rtsp_urls_to_try() == [
        "rtsps://10.0.0.99:322/streaming/live/1",
        "rtsps://bblp:SECRET@10.0.0.99:322/streaming/live/1",
        "rtsps://192.168.1.20:322/streaming/live/1",
        "rtsps://bblp:SECRET@192.168.1.20:322/streaming/live/1",
    ]


def test_rtsp_urls_preserve_existing_auth_when_rewriting_host() -> None:
    service = _service(host="192.168.1.21", access_code="SECRET")
    service.client = SimpleNamespace(
        _access_code="SECRET",
        get_device=lambda: SimpleNamespace(
            camera=SimpleNamespace(rtsp_url="rtsps://bblp:SECRET@10.0.0.99:322/streaming/live/1")
        ),
    )

    assert service._rtsp_urls_to_try() == [
        "rtsps://bblp:SECRET@10.0.0.99:322/streaming/live/1",
        "rtsps://bblp:SECRET@192.168.1.21:322/streaming/live/1",
    ]
