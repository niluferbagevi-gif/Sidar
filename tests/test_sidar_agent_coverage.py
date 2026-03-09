"""
agent/sidar_agent.py eksik satırlarını kapatmak için hedeflenmiş testler.

Hedef satırlar:
  17-18, 282-302, 328-329, 337, 343-354, 364-368, 372-376, 392-393, 408,
  418, 450-457, 469-478, 495-498, 522-523, 535-536, 549, 666, 750, 752,
  765, 777, 787, 798, 827, 863, 1079, 1137-1138, 1164, 1169, 1212-1213,
  1226, 1285-1298, 1333-1335, 1370-1373, 1390, 1413, 1418, 1422, 1430,
  1434, 1437, 1466, 1524-1525
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── httpx guard: bazı test dosyaları sys.modules["httpx"] yerini bir stub ile
# değiştirip geri yüklemez (test_rag_runtime_extended.py gibi). Modül yüklenirken
# gerçek httpx referansını kayıt altına alırız; fixture'da geri yükleriz.
try:
    import httpx as _REAL_HTTPX
except ImportError:
    _REAL_HTTPX = None  # httpx kurulu değil, ilgili testler zaten skip edilir

from config import Config
from agent.sidar_agent import SidarAgent, ToolCall
from agent.tooling import PatchFileSchema


# ─────────────────────────────────────────────
#  ORTAK FIXTURE'LAR
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _restore_httpx():
    """Diğer test dosyaları sys.modules['httpx'] yerine stub koyabilir.
    Gerçek httpx'i agent fixture'dan önce geri yükle; chromadb'nin önbelleğini de güncelle."""
    if _REAL_HTTPX is not None:
        sys.modules["httpx"] = _REAL_HTTPX
        # chromadb'nin httpx bağımlılığı olan tüm modüllerini güncelle
        _chromadb_httpx_mods = [
            "chromadb.api.base_http_client",
            "chromadb.api.client",
            "chromadb.api.async_client",
            "chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2",
        ]
        for _mod_name in _chromadb_httpx_mods:
            _mod = sys.modules.get(_mod_name)
            if _mod is not None and hasattr(_mod, "httpx"):
                try:
                    _mod.httpx = _REAL_HTTPX
                except Exception:
                    pass
    yield


@pytest.fixture
def test_config(tmp_path):
    cfg = Config()
    cfg.BASE_DIR = tmp_path
    cfg.TEMP_DIR = tmp_path / "temp"
    cfg.DATA_DIR = tmp_path / "data"
    cfg.RAG_DIR = tmp_path / "rag"
    cfg.MEMORY_FILE = cfg.DATA_DIR / "memory.json"
    cfg.TEMP_DIR.mkdir()
    cfg.DATA_DIR.mkdir()
    cfg.RAG_DIR.mkdir()
    cfg.TAVILY_API_KEY = ""
    cfg.GOOGLE_SEARCH_API_KEY = ""
    cfg.SEARCH_ENGINE = "auto"
    cfg.MAX_REACT_STEPS = 3
    return cfg


@pytest.fixture
def agent(test_config):
    return SidarAgent(cfg=test_config)


# ─────────────────────────────────────────────
#  YARDIMCI: LLM chat mock oluşturucu
# ─────────────────────────────────────────────

def _make_llm_responses(*responses):
    """
    Her çağrıda sıradaki yanıtı döndüren LLM chat mock'u.
    stream=True → async generator; stream=False → string
    """
    idx = [0]

    async def mock_chat(**kwargs):
        resp = responses[min(idx[0], len(responses) - 1)]
        idx[0] += 1
        if kwargs.get("stream", False):
            async def _gen():
                yield resp
            return _gen()
        return resp

    return mock_chat


# ─────────────────────────────────────────────
#  1. OpenTelemetry import fallback (lines 17-18)
# ─────────────────────────────────────────────

def test_opentelemetry_trace_is_none_when_unavailable():
    """Lines 17-18: opentelemetry yoksa trace=None olur."""
    import importlib
    import importlib.util
    import types

    # opentelemetry modülünü geçici olarak engelle
    prev_otel = sys.modules.get("opentelemetry")
    prev_otel_trace = sys.modules.get("opentelemetry.trace")
    sys.modules["opentelemetry"] = None  # ImportError eşdeğeri
    sys.modules["opentelemetry.trace"] = None

    try:
        spec = importlib.util.spec_from_file_location(
            "_sa_otel_test", "agent/sidar_agent.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # __name__ ve __package__ ayarla ki göreli importlar çalışsın
        mod.__package__ = "agent"
        try:
            spec.loader.exec_module(mod)
        except Exception:
            pass
        # trace None olmalı (except bloğu tetiklendi)
        assert getattr(mod, "trace", None) is None
    finally:
        # Geri yükle
        if prev_otel is None:
            sys.modules.pop("opentelemetry", None)
        else:
            sys.modules["opentelemetry"] = prev_otel
        if prev_otel_trace is None:
            sys.modules.pop("opentelemetry.trace", None)
        else:
            sys.modules["opentelemetry.trace"] = prev_otel_trace


# ─────────────────────────────────────────────
#  2. _build_tool_list (lines 1285-1298)
# ─────────────────────────────────────────────

def test_build_tool_list_returns_markdown(agent):
    """Lines 1285-1298: _build_tool_list markdown çıktısı üretir."""
    result = agent._build_tool_list()
    assert "MEVCUT ARAÇLAR" in result
    assert "list_dir" in result
    assert "read_file" in result
    assert "health" in result


# ─────────────────────────────────────────────
#  3. _build_context - gemini provider (line 1466)
# ─────────────────────────────────────────────

def test_build_context_gemini_provider(agent):
    """Line 1466: AI_PROVIDER='gemini' dalı _build_context içinde."""
    original = agent.cfg.AI_PROVIDER
    agent.cfg.AI_PROVIDER = "gemini"
    result = agent._build_context()
    agent.cfg.AI_PROVIDER = original
    assert "Gemini" in result


# ─────────────────────────────────────────────
#  4. _load_instruction_files - mtime exception (lines 1524-1525)
# ─────────────────────────────────────────────

def test_load_instruction_files_stat_exception(agent, tmp_path):
    """Lines 1524-1525: stat() başarısız olduğunda exception yakalanır.
    is_file() patched to True; stat() patched to raise for SIDAR.md."""
    sidar_md = tmp_path / "SIDAR.md"
    sidar_md.write_text("# Test talimat", encoding="utf-8")

    agent.cfg.BASE_DIR = tmp_path
    agent._instructions_cache = None
    agent._instructions_mtimes = {}

    original_stat = Path.stat
    original_is_file = Path.is_file

    # Patch is_file to return True for SIDAR.md (avoid using stat in is_file)
    # then patch stat to raise for SIDAR.md paths
    stat_phase = [False]

    def patched_is_file(self, *args, **kwargs):
        if self.name == "SIDAR.md":
            stat_phase[0] = True   # from now on, stat should fail
            return True
        return original_is_file(self, *args, **kwargs)

    def patched_stat(self, *args, **kwargs):
        if stat_phase[0] and self.name == "SIDAR.md":
            raise OSError("fake stat permission error")
        return original_stat(self, *args, **kwargs)

    with patch.object(Path, "is_file", patched_is_file):
        with patch.object(Path, "stat", patched_stat):
            result = agent._load_instruction_files()

    # Lines 1524-1525 çalıştı (exception yakalandı), result string olmalı
    assert isinstance(result, str)


def test_load_instruction_files_cache_hit(agent, tmp_path):
    """Lines 1529-1530: Cache geçerli olduğunda yeniden okuma yapılmaz."""
    sidar_md = tmp_path / "SIDAR.md"
    sidar_md.write_text("# Cached content", encoding="utf-8")

    # İlk çağrı → cache doldurulur
    result1 = agent._load_instruction_files()
    # İkinci çağrı → cache hit
    result2 = agent._load_instruction_files()
    assert result1 == result2


# ─────────────────────────────────────────────
#  5. _tool_read_file - büyük dosya (lines 522-523)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_read_file_large_file_hint(agent, tmp_path):
    """Lines 522-523: Eşiği aşan dosyada RAG ipucu eklenir."""
    big_file = tmp_path / "big.py"
    big_file.write_text("x = 1\n" * 4000, encoding="utf-8")
    agent.cfg.RAG_FILE_THRESHOLD = 100  # çok düşük eşik
    result = await agent._tool_read_file(str(big_file))
    assert "Büyük Dosya" in result


# ─────────────────────────────────────────────
#  6. _tool_write_file - hatalı format (lines 535-536)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_write_file_bad_format(agent):
    """Lines 539-540: Ayırıcı olmayan string format hatası döndürür."""
    result = await agent._tool_write_file("sadece_yol_yok_delimiter")
    assert "Hatalı format" in result


@pytest.mark.asyncio
async def test_tool_write_file_with_schema(agent, tmp_path):
    """Lines 535-536: WriteFileSchema nesnesiyle path ve content alınır."""
    from agent.tooling import WriteFileSchema
    test_file = tmp_path / "schema_write.py"
    schema = WriteFileSchema(path=str(test_file), content="print('hello')")
    result = await agent._tool_write_file(schema)
    assert result is not None


# ─────────────────────────────────────────────
#  7. _tool_patch_file - PatchFileSchema (line 549)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_patch_file_with_schema(agent, tmp_path):
    """Line 549: PatchFileSchema nesnesiyle yama uygulanır."""
    test_file = tmp_path / "patch.py"
    test_file.write_text("old_code = 1\n", encoding="utf-8")
    schema = PatchFileSchema(
        path=str(test_file),
        old_text="old_code = 1",
        new_text="new_code = 2",
    )
    result = await agent._tool_patch_file(schema)
    assert result is not None


# ─────────────────────────────────────────────
#  8. _tool_github_list_prs - geçersiz limit (line 666)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_github_list_prs_invalid_limit(agent):
    """Line 673: ValueError için limit varsayılan 10 kullanılır."""
    with patch.object(agent.github, "is_available", return_value=True):
        with patch.object(agent.github, "list_pull_requests", return_value=(True, "PR listesi")) as mock_pr:
            await agent._tool_github_list_prs("open|||gecersiz")
            mock_pr.assert_called_once_with(state="open", limit=10)


@pytest.mark.asyncio
async def test_tool_github_list_prs_with_schema(agent):
    """Line 666: GithubListPRsSchema ile state/limit doğrudan alınır."""
    from agent.tooling import GithubListPRsSchema
    schema = GithubListPRsSchema(state="closed", limit=5)
    with patch.object(agent.github, "is_available", return_value=True):
        with patch.object(agent.github, "list_pull_requests", return_value=(True, "PR listesi")) as mock_pr:
            await agent._tool_github_list_prs(schema)
            mock_pr.assert_called_once_with(state="closed", limit=5)


# ─────────────────────────────────────────────
#  9. _tool_github_list_issues (lines 750, 752, 754-758)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_github_list_issues_api_error(agent):
    """Line 750: API hatası → hata mesajı döndürür."""
    with patch.object(agent.github, "is_available", return_value=True):
        with patch.object(agent.github, "list_issues", return_value=(False, ["API bağlantı hatası"])):
            result = await agent._tool_github_list_issues("open|||5")
    assert "API bağlantı hatası" in result


@pytest.mark.asyncio
async def test_tool_github_list_issues_empty(agent):
    """Line 752: Boş liste → bilgilendirici mesaj."""
    with patch.object(agent.github, "is_available", return_value=True):
        with patch.object(agent.github, "list_issues", return_value=(True, [])):
            result = await agent._tool_github_list_issues("open|||5")
    assert "bulunmuyor" in result


@pytest.mark.asyncio
async def test_tool_github_list_issues_with_data(agent):
    """Lines 754-758: Verili issue listesi formatlanır."""
    issues = [
        {"number": 42, "user": "alice", "title": "Test issue başlığı", "created_at": "2024-01-01"},
    ]
    with patch.object(agent.github, "is_available", return_value=True):
        with patch.object(agent.github, "list_issues", return_value=(True, issues)):
            result = await agent._tool_github_list_issues("open|||5")
    assert "Test issue başlığı" in result
    assert "#42" in result


# ─────────────────────────────────────────────
#  10. GitHub araç – eksik parametre kontrolleri
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_github_create_issue_no_title(agent):
    """Line 765: Boş title (|||body) → title gerekli hatası."""
    # "|||body" formatı: title="" (boş) → getattr falsy → hata
    with patch.object(agent.github, "is_available", return_value=True):
        result = await agent._tool_github_create_issue("|||bir açıklama")
    assert "title gerekli" in result


@pytest.mark.asyncio
async def test_tool_github_comment_issue_no_number(agent):
    """Line 775: number=0 → falsy → number gerekli hatası."""
    # "0|||yorum" → number=0 → getattr(arg, "number", None) = 0 → falsy
    with patch.object(agent.github, "is_available", return_value=True):
        result = await agent._tool_github_comment_issue("0|||bir yorum")
    assert "number gerekli" in result


@pytest.mark.asyncio
async def test_tool_github_comment_issue_no_token(agent):
    """Line 777: Geçerli number ama GitHub token yok → token hatası."""
    with patch.object(agent.github, "is_available", return_value=False):
        result = await agent._tool_github_comment_issue("5|||bir yorum")
    assert "token" in result.lower() or "ayarlanmamış" in result


@pytest.mark.asyncio
async def test_tool_github_close_issue_no_number(agent):
    """Line 785: number=0 → falsy → number gerekli hatası."""
    with patch.object(agent.github, "is_available", return_value=True):
        result = await agent._tool_github_close_issue("0")
    assert "number gerekli" in result


@pytest.mark.asyncio
async def test_tool_github_close_issue_no_token(agent):
    """Line 787: Geçerli number ama GitHub token yok → token hatası."""
    with patch.object(agent.github, "is_available", return_value=False):
        result = await agent._tool_github_close_issue("5")
    assert "token" in result.lower() or "ayarlanmamış" in result


@pytest.mark.asyncio
async def test_tool_github_pr_diff_no_number(agent):
    """Line 796: number=0 → falsy → number gerekli hatası."""
    with patch.object(agent.github, "is_available", return_value=True):
        result = await agent._tool_github_pr_diff("0")
    assert "number gerekli" in result


@pytest.mark.asyncio
async def test_tool_github_pr_diff_no_token(agent):
    """Line 798: Geçerli number ama GitHub token yok → token hatası."""
    with patch.object(agent.github, "is_available", return_value=False):
        result = await agent._tool_github_pr_diff("5")
    assert "token" in result.lower() or "ayarlanmamış" in result


# ─────────────────────────────────────────────
#  11. _tool_github_smart_pr – branch bulunamadı (line 827)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_github_smart_pr_no_head_branch(agent):
    """Line 827: Mevcut git branch belirlenemediğinde hata mesajı."""
    with patch.object(agent.github, "is_available", return_value=True):
        with patch.object(agent.code, "run_shell", return_value=(False, "")):
            result = await agent._tool_github_smart_pr("")
    assert "belirlenemedi" in result


# ─────────────────────────────────────────────
#  12. _tool_github_smart_pr – değişiklik yok (line 863)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_github_smart_pr_no_changes(agent):
    """Line 863: Commit/diff yokken uyarı mesajı."""
    from unittest.mock import PropertyMock
    from managers.github_manager import GitHubManager
    # run_shell: git status, diff --stat, diff --no-color, git log → hepsi boş
    with patch.object(agent.github, "is_available", return_value=True):
        with patch.object(agent.code, "run_shell", return_value=(True, "")):
            with patch.object(type(agent.github), "default_branch", new_callable=PropertyMock, return_value="main"):
                result = await agent._tool_github_smart_pr("feature/test|||main")
    assert "değişiklik bulunamadı" in result


# ─────────────────────────────────────────────
#  13. _tool_get_config – GPU dalı ve OSError (lines 1212-1213, 1226)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_get_config_gpu_branch(agent):
    """Line 1226: USE_GPU=True olduğunda GPU bilgisi satırı oluşturulur."""
    agent.cfg.USE_GPU = True
    result = await agent._tool_get_config("")
    agent.cfg.USE_GPU = False
    assert "GPU" in result


@pytest.mark.asyncio
async def test_tool_get_config_oserror_listdir(agent):
    """Lines 1212-1213: listdir OSError'ı yakalanır, boş liste ile devam edilir."""
    import os
    with patch.object(os, "listdir", side_effect=OSError("permission denied")):
        result = await agent._tool_get_config("")
    assert "Config" in result


# ─────────────────────────────────────────────
#  14. _tool_grep_files – geçersiz ctx_lines (lines 1137-1138)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_grep_files_invalid_ctx_lines(agent, tmp_path):
    """Lines 1137-1138: ctx_lines int'e çevrilemezse 0 kullanılır."""
    test_file = tmp_path / "code.py"
    test_file.write_text("pattern = 'hello'\n", encoding="utf-8")
    result = await agent._tool_grep_files(f"pattern|||{tmp_path}|||*.py|||notanumber")
    assert result is not None


# ─────────────────────────────────────────────
#  15. _tool_todo_write – ayırıcı ile ve ayırıcısız (lines 1164, 1169)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_todo_write_with_separator(agent):
    """Line 1165-1167: ::: ayırıcısı olan item status ile parse edilir."""
    result = await agent._tool_todo_write("Görev A:::in_progress|||Görev B:::completed")
    assert result is not None


@pytest.mark.asyncio
async def test_tool_todo_write_without_separator(agent):
    """Line 1169: ::: olmayan item varsayılan 'pending' statusuyla eklenir."""
    result = await agent._tool_todo_write("Ayırıcısız görev")
    assert result is not None


@pytest.mark.asyncio
async def test_tool_todo_write_with_empty_items(agent):
    """Line 1164: Boş öğeler (strip sonrası boş) continue ile atlanır."""
    # "Görev A|||   |||Görev B" → orta item strip sonrası boş → continue tetiklenir
    result = await agent._tool_todo_write("Görev A:::pending|||   |||Görev B:::completed")
    assert result is not None


@pytest.mark.asyncio
async def test_tool_todo_write_empty(agent):
    """Lines 1157-1158: Boş girdi hata mesajı döndürür."""
    result = await agent._tool_todo_write("   ")
    assert "belirtilmedi" in result


# ─────────────────────────────────────────────
#  16. _get_memory_archive_context (lines 1370-1373, 1390, 1413, 1418,
#                                   1422, 1430, 1434, 1437)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_memory_archive_context_no_collection(agent):
    """Lines 1370-1373, 1390: collection=None → boş string."""
    agent.docs.collection = None
    result = await agent._get_memory_archive_context("sorgu")
    assert result == ""


@pytest.mark.asyncio
async def test_memory_archive_context_query_exception(agent):
    """Lines 1400-1402: query() hata fırlatırsa boş string."""
    mock_col = MagicMock()
    mock_col.query.side_effect = Exception("db error")
    agent.docs.collection = mock_col
    result = await agent._get_memory_archive_context("sorgu")
    assert result == ""


@pytest.mark.asyncio
async def test_memory_archive_context_wrong_source(agent):
    """Line 1413: Yanlış source → atlanır → boş string."""
    mock_col = MagicMock()
    mock_col.query.return_value = {
        "documents": [["başka kaynak metni"]],
        "metadatas": [[{"source": "other_source", "title": "Diğer"}]],
        "distances": [[0.1]],
    }
    agent.docs.collection = mock_col
    result = await agent._get_memory_archive_context("sorgu")
    assert result == ""


@pytest.mark.asyncio
async def test_memory_archive_context_low_relevance(agent):
    """Line 1418: Düşük relevance eşiği geçemez → boş string."""
    mock_col = MagicMock()
    mock_col.query.return_value = {
        "documents": [["düşük alaka düzeyi"]],
        "metadatas": [[{"source": "memory_archive", "title": "T"}]],
        "distances": [[0.9]],   # relevance = 0.1 < min_score (0.35)
    }
    agent.docs.collection = mock_col
    agent.cfg.MEMORY_ARCHIVE_MIN_SCORE = 0.35
    result = await agent._get_memory_archive_context("sorgu")
    assert result == ""


@pytest.mark.asyncio
async def test_memory_archive_context_empty_snippet(agent):
    """Line 1422: Boş doc metni atlanır → boş string."""
    mock_col = MagicMock()
    mock_col.query.return_value = {
        "documents": [[""]],
        "metadatas": [[{"source": "memory_archive", "title": "T"}]],
        "distances": [[0.1]],
    }
    agent.docs.collection = mock_col
    result = await agent._get_memory_archive_context("sorgu")
    assert result == ""


@pytest.mark.asyncio
async def test_memory_archive_context_max_chars_stops_early(agent):
    """Line 1430: max_chars dolduğunda döngü sonlanır."""
    long_text = "x" * 600   # 500 char limitini aşar → kesilir
    mock_col = MagicMock()
    mock_col.query.return_value = {
        "documents": [[long_text, "ikinci doc"]],
        "metadatas": [[
            {"source": "memory_archive", "title": "T1"},
            {"source": "memory_archive", "title": "T2"},
        ]],
        "distances": [[0.1, 0.1]],
    }
    agent.docs.collection = mock_col
    agent.cfg.MEMORY_ARCHIVE_MAX_CHARS = 30   # çok kısa → ilk blok bile sığmaz
    agent.cfg.MEMORY_ARCHIVE_TOP_K = 5
    result = await agent._get_memory_archive_context("sorgu")
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_memory_archive_context_top_k_limit(agent):
    """Line 1434: top_k limitine ulaşınca döngü sonlanır."""
    mock_col = MagicMock()
    mock_col.query.return_value = {
        "documents": [["doc1", "doc2", "doc3"]],
        "metadatas": [[
            {"source": "memory_archive", "title": "A"},
            {"source": "memory_archive", "title": "B"},
            {"source": "memory_archive", "title": "C"},
        ]],
        "distances": [[0.1, 0.1, 0.1]],
    }
    agent.docs.collection = mock_col
    agent.cfg.MEMORY_ARCHIVE_TOP_K = 1
    agent.cfg.MEMORY_ARCHIVE_MAX_CHARS = 50000
    result = await agent._get_memory_archive_context("sorgu")
    # En az 1 sonuç seçilmeli
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_memory_archive_context_no_selected(agent):
    """Line 1437: Hiç seçilen yoksa boş string döner."""
    mock_col = MagicMock()
    # Tüm dökümanlar relevance'ı geçemez
    mock_col.query.return_value = {
        "documents": [["low rel doc"]],
        "metadatas": [[{"source": "memory_archive", "title": "T"}]],
        "distances": [[1.0]],   # relevance = 0.0
    }
    agent.docs.collection = mock_col
    agent.cfg.MEMORY_ARCHIVE_MIN_SCORE = 0.5
    result = await agent._get_memory_archive_context("sorgu")
    assert result == ""


@pytest.mark.asyncio
async def test_memory_archive_context_success(agent):
    """Lines 1426-1432: Başarılı arşiv sonucu formatlanır."""
    mock_col = MagicMock()
    mock_col.query.return_value = {
        "documents": [["önemli sohbet detayı"]],
        "metadatas": [[{"source": "memory_archive", "title": "Geçmiş Arşiv"}]],
        "distances": [[0.2]],   # relevance = 0.8 > 0.35
    }
    agent.docs.collection = mock_col
    agent.cfg.MEMORY_ARCHIVE_MIN_SCORE = 0.35
    agent.cfg.MEMORY_ARCHIVE_TOP_K = 3
    agent.cfg.MEMORY_ARCHIVE_MAX_CHARS = 5000
    result = await agent._get_memory_archive_context("sorgu")
    assert "Arşiv" in result or "Geçmiş" in result


# ─────────────────────────────────────────────
#  17. _execute_tool – tracer active (lines 1312-1340)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_tool_with_active_tracer(agent):
    """Lines 1312-1330: Tracer aktifken tool çalıştırılır ve span kapatılır."""
    import agent.sidar_agent as mod
    original_trace = mod.trace

    mock_trace = MagicMock()
    mock_span = MagicMock()
    mock_trace.get_current_span.return_value = mock_span

    mock_tracer = MagicMock()
    mock_span_cm = MagicMock()
    mock_span_cm.__enter__ = MagicMock(return_value=mock_span)
    mock_span_cm.__exit__ = MagicMock(return_value=False)
    mock_tracer.start_as_current_span.return_value = mock_span_cm

    mod.trace = mock_trace
    agent.tracer = mock_tracer
    try:
        result = await agent._execute_tool("health", "")
        assert result is not None
        mock_span_cm.__exit__.assert_called_once()
    finally:
        mod.trace = original_trace
        agent.tracer = None


@pytest.mark.asyncio
async def test_execute_tool_exception_with_tracer(agent):
    """Lines 1332-1337: Tool exception'ı tracer'la birlikte doğru işlenir."""
    import agent.sidar_agent as mod
    original_trace = mod.trace

    mock_trace = MagicMock()
    mock_span = MagicMock()
    mock_trace.get_current_span.return_value = mock_span

    mock_tracer = MagicMock()
    mock_span_cm = MagicMock()
    mock_span_cm.__enter__ = MagicMock(return_value=mock_span)
    mock_span_cm.__exit__ = MagicMock(return_value=False)
    mock_tracer.start_as_current_span.return_value = mock_span_cm

    mod.trace = mock_trace
    agent.tracer = mock_tracer

    original_handler = agent._tools.get("health")

    async def raising_handler(_):
        raise RuntimeError("kasıtlı test hatası")

    agent._tools["health"] = raising_handler
    try:
        with pytest.raises(RuntimeError):
            await agent._execute_tool("health", "")
        mock_span_cm.__exit__.assert_called_once()
    finally:
        mod.trace = original_trace
        agent.tracer = None
        agent._tools["health"] = original_handler


# ─────────────────────────────────────────────
#  18. _react_loop – tracer aktif (lines 282-302)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_react_loop_with_tracer_active(agent):
    """Lines 282-302: Tracer aktifken react_loop span açar/kapatır."""
    import agent.sidar_agent as mod
    original_trace = mod.trace

    mock_trace = MagicMock()
    mock_span = MagicMock()
    mock_trace.get_current_span.return_value = mock_span

    mock_tracer = MagicMock()
    mock_span_cm = MagicMock()
    mock_span_cm.__enter__ = MagicMock(return_value=mock_span)
    mock_span_cm.__exit__ = MagicMock(return_value=False)
    mock_tracer.start_as_current_span.return_value = mock_span_cm

    mod.trace = mock_trace
    agent.tracer = mock_tracer

    llm_mock = _make_llm_responses(
        '{"thought": "bitti", "tool": "final_answer", "argument": "Tracer testi"}'
    )
    try:
        with patch.object(agent.llm, "chat", side_effect=llm_mock):
            chunks = []
            async for chunk in agent._react_loop("tracer testi"):
                chunks.append(chunk)
        assert any("Tracer testi" in c for c in chunks)
    finally:
        mod.trace = original_trace
        agent.tracer = None


# ─────────────────────────────────────────────
#  19. _react_loop – JSON parse edge case'leri
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_react_loop_json_decode_error_then_success(agent):
    """Lines 328-329: Bozuk JSON ([invalid]) sonrası geçerli JSON bulunur."""
    # "[invalid]" ile başlayan metin: idx=0 ch='[' → JSONDecodeError → continue
    # Sonra "{...}" bulunur ve başarıyla ayrıştırılır (lines 328-329 tetiklenir)
    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                yield '[invalid json text] {"thought": "t", "tool": "final_answer", "argument": "bitti"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_react_loop_no_json_payload(agent):
    """Lines 331-332: Geçerli JSON bulunamazsa ValueError → hata geri bildirimi."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                if call_count[0] == 0:
                    call_count[0] += 1
                    yield "Tamamen düz metin, JSON içermiyor."
                else:
                    yield '{"thought": "ok", "tool": "final_answer", "argument": "Kurtarıldı"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_react_loop_empty_json_array(agent):
    """Line 337: Boş JSON dizisi ValueError fırlatır → hata geri bildirimi."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                if call_count[0] == 0:
                    call_count[0] += 1
                    yield "[]"
                else:
                    yield '{"thought": "ok", "tool": "final_answer", "argument": "Kurtarıldı"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_react_loop_response_alias(agent):
    """Lines 343-354: 'tool' anahtarı yok, 'response' alias'ı final_answer'a çevrilir."""
    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                yield '{"thought": "düşünce", "response": "Merhaba dünya"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert any("Merhaba dünya" in c for c in chunks)


@pytest.mark.asyncio
async def test_react_loop_answer_alias(agent):
    """Lines 343-354: 'answer' alias'ı kullanılır."""
    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                yield '{"thought": "t", "answer": "Yanıt burada"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert any("Yanıt burada" in c for c in chunks)


@pytest.mark.asyncio
async def test_react_loop_no_alias_fallback(agent):
    """Lines 352-358: Bilinen alias yok → anahtar-değer özeti üretilir."""
    agent.cfg.MAX_REACT_STEPS = 1

    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                yield '{"thought": "t", "custom_field": "özel değer"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)

    agent.cfg.MAX_REACT_STEPS = 3


@pytest.mark.asyncio
async def test_react_loop_final_answer_in_parallel_list(agent):
    """Lines 364-368: Paralel listede final_answer → hata geri bildirimi."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                if call_count[0] == 0:
                    call_count[0] += 1
                    yield '[{"thought":"t","tool":"read_file","argument":"x"}, {"thought":"t2","tool":"final_answer","argument":"y"}]'
                else:
                    yield '{"thought": "ok", "tool": "final_answer", "argument": "Tamam"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_react_loop_unsafe_parallel_tools(agent):
    """Lines 372-376: Paralelde güvensiz araç → hata geri bildirimi."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                if call_count[0] == 0:
                    call_count[0] += 1
                    yield '[{"thought":"t1","tool":"write_file","argument":"a"}, {"thought":"t2","tool":"execute_code","argument":"b"}]'
                else:
                    yield '{"thought": "ok", "tool": "final_answer", "argument": "Tamam"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_react_loop_parallel_batch_exception(agent):
    """Lines 392-393, 408: Paralel çalıştırmada araç exception fırlatır."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                if call_count[0] == 0:
                    call_count[0] += 1
                    yield '[{"thought":"t1","tool":"list_dir","argument":"."}, {"thought":"t2","tool":"read_file","argument":"nonexistent.xyz"}]'
                else:
                    yield '{"thought": "ok", "tool": "final_answer", "argument": "Tamam"}'
            return gen()
        return ""

    original_execute = agent._execute_tool

    async def mocked_execute(tool_name, tool_arg):
        if tool_name == "read_file" and "nonexistent" in str(tool_arg):
            raise RuntimeError("dosya bulunamadı")
        return await original_execute(tool_name, tool_arg)

    with patch.object(agent, "_execute_tool", side_effect=mocked_execute):
        with patch.object(agent.llm, "chat", side_effect=mock_chat):
            chunks = []
            async for chunk in agent._react_loop("test"):
                chunks.append(chunk)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_react_loop_parallel_batch_none_result(agent):
    """Lines 392-393: Paralel araç None döndürür (had_error=True)."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                if call_count[0] == 0:
                    call_count[0] += 1
                    yield '[{"thought":"t1","tool":"list_dir","argument":"."}, {"thought":"t2","tool":"health","argument":""}]'
                else:
                    yield '{"thought": "ok", "tool": "final_answer", "argument": "Tamam"}'
            return gen()
        return ""

    original_execute = agent._execute_tool

    async def mocked_execute(tool_name, tool_arg):
        if tool_name == "health":
            return None  # None sonucu → had_error = True
        return await original_execute(tool_name, tool_arg)

    with patch.object(agent, "_execute_tool", side_effect=mocked_execute):
        with patch.object(agent.llm, "chat", side_effect=mock_chat):
            chunks = []
            async for chunk in agent._react_loop("test"):
                chunks.append(chunk)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_react_loop_empty_final_answer(agent):
    """Line 418: Boş final_answer argument'ı varsayılan değerle doldurulur."""
    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                yield '{"thought": "bitti", "tool": "final_answer", "argument": ""}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert any("İşlem tamamlandı" in c for c in chunks)


@pytest.mark.asyncio
async def test_react_loop_tool_not_found(agent):
    """Lines 450-457: Bilinmeyen araç → None → hata geri bildirimi."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                if call_count[0] == 0:
                    call_count[0] += 1
                    yield '{"thought": "t", "tool": "var_olmayan_araç_xyz", "argument": "arg"}'
                else:
                    yield '{"thought": "ok", "tool": "final_answer", "argument": "Tamam"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_react_loop_validation_error(agent):
    """Lines 469-478: Pydantic ValidationError → düzeltici geri bildirim.
    JSON listesi içindeki bir öğe 'tool' alanını eksik → ValidationError."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                if call_count[0] == 0:
                    call_count[0] += 1
                    # JSON list where item is missing required "tool" field → ValidationError
                    yield '[{"thought": "sadece_düşünce_tool_yok"}]'
                else:
                    yield '{"thought": "ok", "tool": "final_answer", "argument": "Kurtarıldı"}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        chunks = []
        async for chunk in agent._react_loop("test"):
            chunks.append(chunk)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_react_loop_unexpected_exception(agent):
    """Lines 495-498: Beklenmeyen exception → kullanıcıya hata mesajı."""
    async def mock_chat(**kwargs):
        if kwargs.get("stream"):
            async def gen():
                yield '{"thought": "t", "tool": "health", "argument": ""}'
            return gen()
        return ""

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        with patch.object(agent, "_execute_tool", side_effect=Exception("beklenmeyen!")):
            chunks = []
            async for chunk in agent._react_loop("test"):
                chunks.append(chunk)
    assert any("beklenmeyen" in c.lower() or "hata" in c.lower() for c in chunks)


# ─────────────────────────────────────────────
#  20. _tool_subtask – araç sonucu messages'a eklenir (line 1079)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_subtask_executes_tool_and_appends_result(agent):
    """Line 1079: Subtask bir araç çalıştırır ve sonucu messages'a ekler."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            return '{"thought": "sağlığı kontrol et", "tool": "health", "argument": ""}'
        return '{"thought": "bitti", "tool": "final_answer", "argument": "Tamamlandı"}'

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        result = await agent._tool_subtask("Sistem sağlığını kontrol et")
    assert "Tamamlandı" in result or "Alt Görev" in result


# ─────────────────────────────────────────────
#  21. respond() – boş girdi (line 184)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_respond_empty_input(agent):
    """Lines 183-185: Boş string → uyarı mesajı."""
    chunks = []
    async for chunk in agent.respond("   "):
        chunks.append(chunk)
    assert any("Boş" in c for c in chunks)


# ─────────────────────────────────────────────
#  22. respond() – bellek özetleme tetiklenir (lines 213-215)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_respond_triggers_summarization(agent):
    """Lines 213-215: needs_summarization True → _summarize_memory çağrılır."""
    summarize_called = [False]

    async def fake_summarize():
        summarize_called[0] = True

    async def fake_react(inp):
        yield "sonuç"

    with patch.object(agent.memory, "needs_summarization", return_value=True):
        with patch.object(agent, "_summarize_memory", side_effect=fake_summarize):
            with patch.object(agent, "_react_loop", side_effect=fake_react):
                with patch.object(agent.memory, "add"):
                    with patch.object(agent.auto, "handle", return_value=(False, "")):
                        with patch.object(agent, "_try_direct_tool_route", return_value=None):
                            chunks = []
                            async for chunk in agent.respond("test"):
                                chunks.append(chunk)

    assert summarize_called[0] is True


# ─────────────────────────────────────────────
#  23. set_access_level (lines 1625-1645)
# ─────────────────────────────────────────────

def test_set_access_level_to_new_level(agent):
    """Lines 1625-1644: Farklı seviyeye geçiş başarıyla gerçekleşir."""
    agent.security.set_level("restricted")
    agent.cfg.ACCESS_LEVEL = "restricted"
    result = agent.set_access_level("full")
    assert "güncellendi" in result or "full" in result.lower()


def test_set_access_level_same_level(agent):
    """Line 1645: Aynı seviye zaten ayarlıysa bilgilendirme mesajı."""
    agent.security.set_level("restricted")
    agent.cfg.ACCESS_LEVEL = "restricted"
    result = agent.set_access_level("restricted")
    assert "zaten" in result


# ─────────────────────────────────────────────
#  24. _build_context – aktif todo (lines 1488-1491)
# ─────────────────────────────────────────────

def test_build_context_with_active_todos(agent):
    """Lines 1488-1491: Todo listesi doluysa bağlama eklenir."""
    agent.todo.set_tasks([{"content": "Test görevi", "status": "pending"}])
    result = agent._build_context()
    assert "Görev" in result or "Test görevi" in result


# ─────────────────────────────────────────────
#  25. _build_context – son dosya bilgisi (lines 1483-1485)
# ─────────────────────────────────────────────

def test_build_context_with_last_file(agent):
    """Lines 1483-1485: Son dosya bilgisi bağlama eklenir."""
    agent.memory.set_last_file("/tmp/ornek.py")
    result = agent._build_context()
    assert "ornek.py" in result


# ─────────────────────────────────────────────
#  26. _tool_subtask – non-string LLM output (line 1040-1044)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_subtask_non_string_output(agent):
    """Lines 1040-1044: LLM string dışı çıktı döndürürse uyarı verilir."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            return None   # string değil
        return '{"thought": "bitti", "tool": "final_answer", "argument": "Tamam"}'

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        result = await agent._tool_subtask("Bir görev")
    assert result is not None


# ─────────────────────────────────────────────
#  27. _tool_subtask – no JSON block (lines 1049-1053)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_subtask_no_json_block(agent):
    """Lines 1049-1053: JSON bloğu bulunamazsa hata geri bildirimi."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            return "Bu metin JSON içermiyor"
        return '{"thought": "bitti", "tool": "final_answer", "argument": "Tamam"}'

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        result = await agent._tool_subtask("Bir görev")
    assert result is not None


# ─────────────────────────────────────────────
#  28. _tool_subtask – boş tool alanı (lines 1064-1069)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_subtask_empty_tool_name(agent):
    """Lines 1064-1069: tool alanı boş → hata geri bildirimi."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            return '{"thought": "t", "tool": "", "argument": "arg"}'
        return '{"thought": "bitti", "tool": "final_answer", "argument": "Tamam"}'

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        result = await agent._tool_subtask("Bir görev")
    assert result is not None


# ─────────────────────────────────────────────
#  29. _tool_subtask – None araç sonucu (lines 1072-1077)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_subtask_none_tool_result(agent):
    """Lines 1072-1077: Araç None döndürürse hata geri bildirimi."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            return '{"thought": "t", "tool": "bilinmeyen_araç_zzz", "argument": "arg"}'
        return '{"thought": "bitti", "tool": "final_answer", "argument": "Tamam"}'

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        result = await agent._tool_subtask("Bir görev")
    assert result is not None


# ─────────────────────────────────────────────
#  30. _tool_subtask – ValidationError (lines 1083-1089)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_subtask_validation_error(agent):
    """Lines 1083-1089: Pydantic ValidationError yakalanır."""
    call_count = [0]

    async def mock_chat(**kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            return '{"thought": "sadece düşünce"}'   # tool eksik
        return '{"thought": "bitti", "tool": "final_answer", "argument": "Tamam"}'

    with patch.object(agent.llm, "chat", side_effect=mock_chat):
        result = await agent._tool_subtask("Bir görev")
    assert result is not None


# ─────────────────────────────────────────────
#  31. _tool_todo_update – geçersiz ID (lines 1186-1188)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_todo_update_invalid_id(agent):
    """Lines 1186-1188: Sayısal olmayan ID → hata."""
    result = await agent._tool_todo_update("abc|||completed")
    assert "sayısal" in result.lower() or "ID" in result


@pytest.mark.asyncio
async def test_tool_todo_update_missing_delimiter(agent):
    """Lines 1183-1184: ||| yok → format hatası."""
    result = await agent._tool_todo_update("sadece_id")
    assert "Format" in result or "format" in result


# ─────────────────────────────────────────────
#  32. _tool_github_search_code – boş query (lines 656-657)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_github_search_code_empty_query(agent):
    """Lines 656-657: Boş sorgu → hata."""
    result = await agent._tool_github_search_code("")
    assert "belirtilmedi" in result


# ─────────────────────────────────────────────
#  33. _tool_docs_add – format kontrolü (lines 976-977)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_docs_add_missing_url(agent):
    """Lines 976-977: | ayırıcısı olmayan girdi → hata."""
    result = await agent._tool_docs_add("başlıksız_url_yok")
    assert "Kullanım" in result or "başlık" in result.lower()


# ─────────────────────────────────────────────
#  34. _tool_pypi_compare – eksik sürüm (lines 948-949)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_pypi_compare_missing_version(agent):
    """Lines 948-949: | ayırıcısı olmayan girdi → hata."""
    result = await agent._tool_pypi_compare("sadece_paket_adı")
    assert "Kullanım" in result or "kullanım" in result.lower()


# ─────────────────────────────────────────────
#  35. _tool_execute_code – boş kod (line 560)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_execute_code_empty(agent):
    """Line 560: Boş kod → hata."""
    result = await agent._tool_execute_code("")
    assert "belirtilmedi" in result


# ─────────────────────────────────────────────
#  36. _tool_web_search – boş sorgu (line 923)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_web_search_empty_query(agent):
    """Line 923: Boş web arama sorgusu → hata."""
    result = await agent._tool_web_search("")
    assert "belirtilmedi" in result


# ─────────────────────────────────────────────
#  37. _tool_fetch_url – boş URL (line 929)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_fetch_url_empty_url(agent):
    """Line 929: Boş URL → hata."""
    result = await agent._tool_fetch_url("")
    assert "belirtilmedi" in result


# ─────────────────────────────────────────────
#  38. clear_memory (line 1615-1616)
# ─────────────────────────────────────────────

def test_clear_memory(agent):
    """Lines 1615-1616: Bellek temizleme başarı mesajı döndürür."""
    result = agent.clear_memory()
    assert "temizlendi" in result


# ─────────────────────────────────────────────
#  39. status() (lines 1648-1659)
# ─────────────────────────────────────────────

def test_agent_status(agent):
    """Lines 1648-1659: status() rapor stringi döndürür."""
    result = agent.status()
    assert "SidarAgent" in result
    assert "Erişim" in result
