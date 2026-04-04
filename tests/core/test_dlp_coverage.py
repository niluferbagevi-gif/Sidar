from __future__ import annotations

import core.dlp as dlp


def test_is_valid_tckn_rejects_invalid_shapes_and_bad_checksums() -> None:
    assert dlp._is_valid_tckn("") is False
    assert dlp._is_valid_tckn("01234567890") is False
    assert dlp._is_valid_tckn("123456789a1") is False
    assert dlp._is_valid_tckn("10000000145") is False
    assert dlp._is_valid_tckn("10000000146") is True


def test_sub_masks_group_zero_and_group_with_prefix_suffix() -> None:
    engine = dlp.DLPEngine(replacement="<X>")

    masked_all, detections_all = engine._sub(dlp._RE_EMAIL, "mail me: user@example.com", 0, "email")
    assert masked_all == "mail me: <X>"
    assert detections_all[0].original_value == "user@exa…"

    masked_group, detections_group = engine._sub(
        dlp._RE_BEARER,
        "Authorization: Bearer abcdefghijklmnopqrstuvwx",
        2,
        "bearer_token",
    )
    assert masked_group == "Authorization: Bearer <X>"
    assert detections_group[0].pattern_name == "bearer_token"


def test_mask_handles_empty_text_and_tckn_paths_and_logging(caplog) -> None:
    engine = dlp.DLPEngine(log_detections=True)

    assert engine.mask("") == ("", [])

    text = "valid=10000000146 invalid=12345678910"
    masked, detections = engine.mask(text)
    assert "[MASKED]" in masked
    assert "12345678910" in masked
    assert any(d.pattern_name == "tckn" for d in detections)

    assert "DLP:" in caplog.text


def test_mask_can_skip_tckn_block_and_continue_other_patterns() -> None:
    engine = dlp.DLPEngine(mask_tckn=False)

    masked, detections = engine.mask("mail=user@example.com tckn=10000000146")

    assert "[MASKED]" in masked
    assert "10000000146" in masked
    assert all(d.pattern_name != "tckn" for d in detections)


def test_mask_messages_tracks_detected_and_passthrough_messages() -> None:
    engine = dlp.DLPEngine()

    messages = [
        {"role": "user", "content": "email user@example.com"},
        {"role": "assistant", "content": ""},
        {"role": "system", "content": None},
        {"role": "tool", "content": {"not": "a-string"}},
    ]

    masked_messages, detections = engine.mask_messages(messages)

    assert masked_messages[0]["content"] != messages[0]["content"]
    assert masked_messages[1] is messages[1]
    assert masked_messages[2] is messages[2]
    assert masked_messages[3] is messages[3]
    assert detections


def test_mask_pii_uses_global_engine(monkeypatch) -> None:
    class _StubEngine:
        def mask(self, text: str):
            return f"stub::{text}", [dlp.DLPDetection("x", 0, 1, "***")]

    monkeypatch.setattr(dlp, "get_dlp_engine", lambda: _StubEngine())

    assert dlp.mask_pii("secret") == "stub::secret"
