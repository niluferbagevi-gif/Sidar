"""Media/multimodal tooling Doctor checks."""

from __future__ import annotations

import shutil
from typing import Any

from core.doctor import DoctorCheck


def check_media_tools() -> DoctorCheck:
    """Report presence of the external CLI tools core.multimodal shells out to.

    README.md documents ffmpeg as a required system dependency for multimodal
    video/audio parsing, but nothing checked for it before this: install_sidar.sh
    has no ffmpeg probe, and core.multimodal only discovers it is missing at
    runtime, mid-request, via a RuntimeError (see extract_video_frames and
    extract_audio_track). yt-dlp and whisper back optional remote-video and
    speech-to-text paths that already degrade gracefully on their own when
    absent, so they are reported here for visibility only, not escalated.

    This mirrors check_gpu()'s pattern: a missing optional runtime dependency is
    a non-fatal "warn" surfaced at install/readiness time, not a fatal "fail",
    so a fresh install still completes and the gap is visible before a user
    hits a surprise RuntimeError on their first video/audio request.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    yt_dlp_path = shutil.which("yt-dlp")
    whisper_path = shutil.which("whisper")
    details: dict[str, Any] = {
        "ffmpeg_found": ffmpeg_path is not None,
        "yt_dlp_found": yt_dlp_path is not None,
        "whisper_found": whisper_path is not None,
    }

    if ffmpeg_path is None:
        return DoctorCheck(
            "media",
            "warn",
            "ffmpeg not found; multimodal video/audio parsing will fail at runtime",
            details,
        )

    missing_optional = [
        name
        for name, path in (("yt-dlp", yt_dlp_path), ("whisper", whisper_path))
        if path is None
    ]
    if missing_optional:
        return DoctorCheck(
            "media",
            "warn",
            "ffmpeg is present; optional media tool(s) not found: " + ", ".join(missing_optional),
            details,
        )

    return DoctorCheck("media", "pass", "ffmpeg, yt-dlp, and whisper are all available", details)


__all__ = ["check_media_tools"]
