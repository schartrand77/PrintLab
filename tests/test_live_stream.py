from __future__ import annotations

from app.routers import api


def test_stable_rtsp_command_prefers_buffering_over_low_latency() -> None:
    command = api._build_stable_rtsp_ffmpeg_command("rtsps://printer.local/streaming/live/1")

    assert "-rtsp_transport" in command
    assert command[command.index("-rtsp_transport") + 1] == "tcp"
    assert "-fflags" not in command
    assert "nobuffer" not in command
    assert "-probesize" in command
    assert int(command[command.index("-probesize") + 1]) >= 1_000_000
    assert "-analyzeduration" in command
    assert int(command[command.index("-analyzeduration") + 1]) >= 1_000_000
    assert "fps=10" in command


def test_live_stream_buffer_settings_keep_connection_alive_during_short_stalls() -> None:
    assert api.LIVE_STREAM_STALE_FRAME_SECONDS >= 8
    assert api.LIVE_STREAM_STALE_FRAME_INTERVAL_SECONDS <= 1.0
    assert api.LIVE_STREAM_READ_TIMEOUT_SECONDS > api.LIVE_STREAM_STALE_FRAME_INTERVAL_SECONDS
