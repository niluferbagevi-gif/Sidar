"""
agent/auto_handle.py için birim testleri.
_MULTI_STEP_RE ve _DOT_CMD_RE regex kalıpları (ağır bağımlılıklar olmadan).
"""
from __future__ import annotations

import re


# ── Regex'leri doğrudan kaynak dosyadan kopyalayıp test et ──

_MULTI_STEP_RE = re.compile(
    r"\bardından\b|\bsonrasında\b|\bönce\b.{1,60}\bsonra\b"
    r"|\b\d+\s*[\.\)]\s+\w|\bve\s+ardından\b|\bşunları\s+(yap|bul|göster|listele)\b"
    r"|\bfirst\b.{0,200}\bthen\b|\bstep\s*\d|\bnext\b",
    re.IGNORECASE | re.DOTALL,
)

_DOT_CMD_RE = re.compile(r"^\s*\.(status|health|clear|audit|gpu)\b", re.IGNORECASE)


# ══════════════════════════════════════════════════════════════
# _MULTI_STEP_RE
# ══════════════════════════════════════════════════════════════

class TestMultiStepRe:
    def test_ardından_detected(self):
        assert _MULTI_STEP_RE.search("Kodu yaz ardından test et") is not None

    def test_sonrasında_detected(self):
        assert _MULTI_STEP_RE.search("Dosyayı oku sonrasında sil") is not None

    def test_önce_sonra_detected(self):
        assert _MULTI_STEP_RE.search("önce kodu incele sonra düzelt") is not None

    def test_numbered_step_detected(self):
        assert _MULTI_STEP_RE.search("1. Kodu incele") is not None

    def test_first_then_detected(self):
        assert _MULTI_STEP_RE.search("First write the function then test it") is not None

    def test_step_n_detected(self):
        assert _MULTI_STEP_RE.search("step 1: install dependencies") is not None

    def test_next_detected(self):
        assert _MULTI_STEP_RE.search("next, run the tests") is not None

    def test_simple_query_not_detected(self):
        assert _MULTI_STEP_RE.search("FastAPI nedir?") is None

    def test_empty_string_not_detected(self):
        assert _MULTI_STEP_RE.search("") is None

    def test_single_word_not_detected(self):
        assert _MULTI_STEP_RE.search("merhaba") is None


# ══════════════════════════════════════════════════════════════
# _DOT_CMD_RE
# ══════════════════════════════════════════════════════════════

class TestDotCmdRe:
    def test_dot_status(self):
        assert _DOT_CMD_RE.match(".status") is not None

    def test_dot_health(self):
        assert _DOT_CMD_RE.match(".health") is not None

    def test_dot_clear(self):
        assert _DOT_CMD_RE.match(".clear") is not None

    def test_dot_audit(self):
        assert _DOT_CMD_RE.match(".audit") is not None

    def test_dot_gpu(self):
        assert _DOT_CMD_RE.match(".gpu") is not None

    def test_case_insensitive(self):
        assert _DOT_CMD_RE.match(".STATUS") is not None
        assert _DOT_CMD_RE.match(".Health") is not None

    def test_leading_whitespace_allowed(self):
        assert _DOT_CMD_RE.match("  .status") is not None

    def test_no_dot_not_matched(self):
        assert _DOT_CMD_RE.match("status") is None

    def test_unknown_dot_command_not_matched(self):
        assert _DOT_CMD_RE.match(".unknown") is None

    def test_trailing_text_after_command_allowed(self):
        assert _DOT_CMD_RE.match(".health extra") is not None
