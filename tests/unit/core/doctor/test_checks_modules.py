from __future__ import annotations

from core.doctor import DoctorCheck


def test_check_redis_passes_when_url_is_configured(monkeypatch):
    from core.doctor.checks import redis as redis_checks

    monkeypatch.setenv("SIDAR_REDIS_URL", "")
    monkeypatch.setenv("REDIS_URL", "redis://cache.local:6379/0")
    monkeypatch.setenv("SIDAR_EVENT_BUS_BACKEND", "redis")

    check = redis_checks.check_redis()

    assert check.status == "pass"
    assert check.message == "Redis URL is configured"
    assert check.details == {
        "redis_url_set": True,
        "event_bus_backend": "redis",
        "required_for_remote_event_bus": True,
    }


def test_check_redis_warns_when_redis_backend_has_no_url(monkeypatch):
    from core.doctor.checks import redis as redis_checks

    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("SIDAR_REDIS_URL", "")
    monkeypatch.setenv("SIDAR_EVENT_BUS_BACKEND", "redis")

    check = redis_checks.check_redis()

    assert check.status == "warn"
    assert (
        check.message == "Neither SIDAR_REDIS_URL nor REDIS_URL is set; "
        "Redis event bus will use local fallback"
    )
    assert check.details == {
        "redis_url_set": False,
        "event_bus_backend": "redis",
        "required_for_remote_event_bus": True,
    }


def test_check_redis_passes_when_only_sidar_redis_url_is_configured(monkeypatch):
    """Regression test: SIDAR_REDIS_URL is the primary variable, REDIS_URL a legacy alias.

    install_sidar.sh's own generated .env only sets SIDAR_REDIS_URL, and the real
    connection resolver (core.config_rate_limit.resolve_redis_url) checks it first.
    Checking REDIS_URL alone used to report a false "not configured" warning for
    every install that never sets the legacy alias.
    """
    from core.doctor.checks import redis as redis_checks

    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("SIDAR_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SIDAR_EVENT_BUS_BACKEND", "redis")

    check = redis_checks.check_redis()

    assert check.status == "pass"
    assert check.message == "Redis URL is configured"
    assert check.details["redis_url_set"] is True


def test_check_redis_passes_when_non_redis_backend_has_no_url(monkeypatch):
    from core.doctor.checks import redis as redis_checks

    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("SIDAR_REDIS_URL", "")
    monkeypatch.setenv("SIDAR_EVENT_BUS_BACKEND", "kafka")

    check = redis_checks.check_redis()

    assert check.status == "pass"
    assert check.message == "Redis is not the selected event bus backend"
    assert check.details == {
        "redis_url_set": False,
        "event_bus_backend": "kafka",
        "required_for_remote_event_bus": False,
    }


def test_check_rag_index_ready_delegates_to_doctor(monkeypatch):
    from core.doctor.checks import rag as rag_checks

    sentinel = DoctorCheck("rag_index", "pass", "ok", {})
    monkeypatch.setattr(rag_checks._doctor, "check_rag_index_ready", lambda: sentinel)

    assert rag_checks.check_rag_index_ready() is sentinel


def test_check_docker_test_image_delegates_to_doctor(monkeypatch):
    from core.doctor.checks import gpu as gpu_checks

    sentinel = DoctorCheck("docker_test_image", "pass", "ok", {})
    monkeypatch.setattr(gpu_checks._doctor, "check_docker_test_image", lambda: sentinel)

    assert gpu_checks.check_docker_test_image() is sentinel


def test_check_graphrag_entity_memory_ready_delegates_to_doctor(monkeypatch):
    from core.doctor.checks import rag as rag_checks

    sentinel = DoctorCheck("graphrag_entity_memory", "pass", "ok", {})
    monkeypatch.setattr(rag_checks._doctor, "check_graphrag_entity_memory_ready", lambda: sentinel)

    assert rag_checks.check_graphrag_entity_memory_ready() is sentinel


def test_check_rag_readiness_delegates_to_doctor(monkeypatch):
    from core.doctor.checks import rag as rag_checks

    sentinel = DoctorCheck("rag", "pass", "ok", {})
    monkeypatch.setattr(rag_checks._doctor, "check_rag_readiness", lambda: sentinel)

    assert rag_checks.check_rag_readiness() is sentinel


def _stub_which(present: set[str]):
    def _which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in present else None

    return _which


def test_check_media_tools_warns_when_ffmpeg_is_missing(monkeypatch):
    from core.doctor.checks import media as media_checks

    monkeypatch.setattr(media_checks.shutil, "which", _stub_which({"yt-dlp", "whisper"}))

    check = media_checks.check_media_tools()

    assert check.status == "warn"
    assert check.message == (
        "ffmpeg not found; multimodal video/audio parsing will fail at runtime"
    )
    assert check.details == {
        "ffmpeg_found": False,
        "yt_dlp_found": True,
        "whisper_found": True,
    }


def test_check_media_tools_warns_when_only_optional_tools_are_missing(monkeypatch):
    from core.doctor.checks import media as media_checks

    monkeypatch.setattr(media_checks.shutil, "which", _stub_which({"ffmpeg"}))

    check = media_checks.check_media_tools()

    assert check.status == "warn"
    assert check.message == "ffmpeg is present; optional media tool(s) not found: yt-dlp, whisper"
    assert check.details == {
        "ffmpeg_found": True,
        "yt_dlp_found": False,
        "whisper_found": False,
    }


def test_check_media_tools_passes_when_all_tools_are_found(monkeypatch):
    from core.doctor.checks import media as media_checks

    monkeypatch.setattr(media_checks.shutil, "which", _stub_which({"ffmpeg", "yt-dlp", "whisper"}))

    check = media_checks.check_media_tools()

    assert check.status == "pass"
    assert check.message == "ffmpeg, yt-dlp, and whisper are all available"
    assert check.details == {
        "ffmpeg_found": True,
        "yt_dlp_found": True,
        "whisper_found": True,
    }
