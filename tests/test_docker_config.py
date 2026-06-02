from __future__ import annotations

from pathlib import Path


def test_dockerfile_can_embed_linux_orca_build() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "ARG ORCA_LINUXDIR_URL=" in dockerfile
    assert "/opt/orca" in dockerfile
    assert "/usr/local/bin/orca-slicer" in dockerfile
    assert "curl -fsSL" in dockerfile
    assert "LD_LIBRARY_PATH=/opt/orca/bin" in dockerfile


def test_compose_dev_documents_optional_orca_build_arg() -> None:
    compose_dev = Path("compose.dev.yaml").read_text(encoding="utf-8")

    assert "ORCA_LINUXDIR_URL" in compose_dev


def test_dockerfile_installs_orca_linux_runtime_libraries() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    for package in (
        "libegl1",
        "libgstreamer1.0-0",
        "libgstreamer-plugins-base1.0-0",
        "libwebkit2gtk-4.1-0",
        "libgtk-3-0t64",
        "libwebpdecoder3",
        "libwebpdemux2",
        "libopengl0",
    ):
        assert package in dockerfile
