import asyncio
from types import SimpleNamespace

from core.ci_remediation import build_root_cause_summary
from core.db import Database
from core.llm_metrics import LLMMetricsCollector
from core import multimodal as multimodal_mod
from core.voice import _Pyttsx3Adapter


def test_database_configure_backend_resolves_raw_relative_sqlite_paths(tmp_path):
    cfg = SimpleNamespace(
        DATABASE_URL="relative/raw.db",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
    )

    db = Database(cfg=cfg)

    assert db._backend == "sqlite"
    assert db._sqlite_path == tmp_path / "relative" / "raw.db"


def test_ci_remediation_root_cause_prefers_explicit_first_sentence():
    summary = build_root_cause_summary(
        {"failure_summary": "fallback summary", "root_cause_hint": "hint should not win"},
        "Root cause: flaky teardown leaves websocket pending.\nExtra details below.",
    )

    assert summary == "Root cause: flaky teardown leaves websocket pending."


def test_resolve_remote_media_stream_ignores_non_mapping_ytdlp_metadata(monkeypatch):
    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda name: name == "yt-dlp")

    def _capture_non_mapping(command):
        if "--dump-single-json" in command:
            return "[]"
        return "https://cdn.example.com/stream.webm\n"

    monkeypatch.setattr(multimodal_mod, "_run_subprocess_capture", _capture_non_mapping)

    resolved = asyncio.run(
        multimodal_mod.resolve_remote_media_stream("https://youtu.be/dQw4w9WgXcQ", prefer_video=False)
    )

    assert resolved["resolved_url"] == "https://cdn.example.com/stream.webm"
    assert resolved["metadata"] == {}
    assert resolved["title"] == ""


def test_llm_metrics_unknown_model_cost_returns_zero_without_lookup():
    assert LLMMetricsCollector.estimate_cost_usd("unknown", "mystery-model", 123, 456) == 0.0


def test_pyttsx3_adapter_synthesize_returns_unavailable_payload_when_import_failed():
    adapter = _Pyttsx3Adapter()
    adapter._import_error = "pyttsx3 missing"

    result = asyncio.run(adapter.synthesize("Merhaba", voice="tr"))

    assert result == {
        "success": False,
        "audio_bytes": b"",
        "mime_type": "audio/wav",
        "provider": "pyttsx3",
        "voice": "tr",
        "reason": "pyttsx3 missing",
    }
