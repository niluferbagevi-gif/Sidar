import re
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from core import dlp
from core.dlp import DLPDetection, DLPEngine, _is_valid_tckn, get_dlp_engine, mask_messages, mask_pii


def test_is_valid_tckn_for_valid_and_invalid_inputs():
    assert _is_valid_tckn("10000000146") is True
    assert _is_valid_tckn("12345678901") is False
    assert _is_valid_tckn("10000000145") is False
    assert _is_valid_tckn("01234567890") is False
    assert _is_valid_tckn("abcdefghijk") is False


def test_sub_masks_full_match_when_group_zero():
    engine = DLPEngine(replacement="[X]")
    pattern = re.compile(r"abc")

    masked, detections = engine._sub(pattern, "abc def", group_idx=0, name="full")

    assert masked == "[X] def"
    assert len(detections) == 1
    assert detections[0].pattern_name == "full"
    assert detections[0].start == 0
    assert detections[0].end == 3


def test_sub_masks_only_captured_group_and_keeps_prefix_suffix():
    engine = DLPEngine(replacement="[X]")
    pattern = re.compile(r"(prefix=)(\w+)")

    masked, detections = engine._sub(pattern, "prefix=secret", group_idx=2, name="partial")

    assert masked == "prefix=[X]"
    assert len(detections) == 1
    assert detections[0].pattern_name == "partial"


def test_mask_returns_early_for_empty_text():
    engine = DLPEngine()
    assert engine.mask("") == ("", [])


def test_mask_covers_all_enabled_patterns_and_logs(caplog):
    engine = DLPEngine(mask_long_hex=True, replacement="[MASK]", log_detections=True)

    text = "\n".join(
        [
            "Authorization: Bearer ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
            "token=sk-live-abcdefghijklmnopqrstuvwxyz1234",
            "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            "AKIA1234567890ABCDEF",
            "api_key=supersecretvalue123",
            "password=myStrongPw123",
            "tckn 10000000146",
            "mail test.user@example.com",
            "cc 4111111111111111",
            "jwt eyaaaaaaaaaa.bbbbbbbbbbb.ccccccccccc",
            "hex deadbeefdeadbeefdeadbeefdeadbeef",
        ]
    )

    with caplog.at_level("WARNING"):
        masked, detections = engine.mask(text)

    assert "[MASK]" in masked
    assert "test.user@example.com" not in masked
    assert "4111111111111111" not in masked
    assert "deadbeefdeadbeefdeadbeefdeadbeef" not in masked

    names = {d.pattern_name for d in detections}
    assert names == {
        "jwt",
        "bearer_token",
        "sk_key",
        "github_token",
        "aws_access_key",
        "kv_secret",
        "password",
        "tckn",
        "email",
        "credit_card",
        "long_hex",
    }
    assert any("DLP Maskeleme" in rec.message for rec in caplog.records)


def test_mask_leaves_invalid_tckn_untouched():
    engine = DLPEngine(mask_tckn=True)
    text = "candidate 12345678901"

    masked, detections = engine.mask(text)

    assert masked == text
    assert detections == []


def test_mask_skips_tckn_block_when_disabled_but_continues_other_patterns():
    engine = DLPEngine(mask_tckn=False, mask_email=True)
    text = "tckn 10000000146 mail user@example.com"
    masked, detections = engine.mask(text)
    assert "10000000146" in masked
    assert "user@example.com" not in masked
    assert any(d.pattern_name == "email" for d in detections)


def test_mask_messages_masks_only_string_contents_and_preserves_original_list():
    engine = DLPEngine(mask_email=True)
    original = [
        {"role": "user", "content": "hello alice@example.com"},
        {"role": "assistant", "content": "plain"},
        {"role": "system", "content": None},
        {"role": "tool"},
        {"role": "json", "content": {"nested": "value"}},
    ]

    masked_messages, detections = engine.mask_messages(original)

    assert original[0]["content"] == "hello alice@example.com"
    assert masked_messages[0]["content"] == "hello [MASKED]"
    assert masked_messages[1] is original[1]
    assert masked_messages[2] is original[2]
    assert masked_messages[3] is original[3]
    assert masked_messages[4] is original[4]
    assert detections and all(isinstance(d, DLPDetection) for d in detections)


def test_build_engine_from_env_disabled(monkeypatch):
    monkeypatch.setenv("DLP_ENABLED", "false")
    monkeypatch.setenv("DLP_LOG_DETECTIONS", "true")

    engine = dlp._build_engine_from_env()

    assert engine.mask_email is False
    assert engine.mask_jwt is False
    assert engine.log_detections is False


def test_build_engine_from_env_enabled_and_logging(monkeypatch):
    monkeypatch.setenv("DLP_ENABLED", "true")
    monkeypatch.setenv("DLP_LOG_DETECTIONS", "yes")

    engine = dlp._build_engine_from_env()

    assert engine.mask_email is True
    assert engine.log_detections is True


@pytest.mark.parametrize("enabled", ["1", "true", "yes"])
def test_enabled_env_variants(monkeypatch, enabled):
    monkeypatch.setenv("DLP_ENABLED", enabled)
    engine = dlp._build_engine_from_env()
    assert engine.mask_bearer is True


def test_get_dlp_engine_is_singleton(monkeypatch):
    monkeypatch.setenv("DLP_ENABLED", "true")
    dlp._ENGINE = None

    first = get_dlp_engine()
    second = get_dlp_engine()

    assert first is second


def test_convenience_functions_use_singleton(monkeypatch):
    dlp._ENGINE = DLPEngine(mask_email=True)

    assert mask_pii("mail me: a@b.com") == "mail me: [MASKED]"

    messages = [{"role": "user", "content": "x@y.com"}]
    masked = mask_messages(messages)
    assert masked[0]["content"] == "[MASKED]"


def test_get_dlp_engine_initialization_is_thread_safe(monkeypatch):
    dlp._ENGINE = None
    build_calls = 0
    build_calls_lock = threading.Lock()
    start_barrier = threading.Barrier(8)

    def _fake_build() -> DLPEngine:
        nonlocal build_calls
        with build_calls_lock:
            build_calls += 1
        return DLPEngine(mask_email=True)

    def _worker() -> DLPEngine:
        start_barrier.wait()
        return get_dlp_engine()

    monkeypatch.setattr(dlp, "_build_engine_from_env", _fake_build)

    with ThreadPoolExecutor(max_workers=8) as pool:
        engines = list(pool.map(lambda _i: _worker(), range(8)))

    assert build_calls == 1
    assert all(engine is engines[0] for engine in engines)
