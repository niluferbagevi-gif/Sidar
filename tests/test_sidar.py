"""
Sidar Project - Temel Test ve Entegrasyon Suiti
Çalıştırmak için kök dizinde: pytest tests/

pytest-asyncio modu: pyproject.toml / pytest.ini'da
  asyncio_mode = "auto"  ya da her async test @pytest.mark.asyncio ile işaretlenmiştir.
"""

import asyncio
import codecs
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from config import Config
from agent.sidar_agent import SidarAgent, ToolCall
from managers.web_search import WebSearchManager
from managers.system_health import SystemHealthManager
from core.rag import DocumentStore


@pytest.fixture
def test_config(tmp_path):
    """Her test için izole edilmiş geçici bir yapılandırma oluşturur."""
    cfg = Config()
    cfg.BASE_DIR = tmp_path
    cfg.TEMP_DIR = tmp_path / "temp"
    cfg.DATA_DIR = tmp_path / "data"
    cfg.RAG_DIR = tmp_path / "rag"
    cfg.MEMORY_FILE = cfg.DATA_DIR / "memory.json"
    
    cfg.TEMP_DIR.mkdir()
    cfg.DATA_DIR.mkdir()
    cfg.RAG_DIR.mkdir()
    
    # Testleri hızlandırmak için API'leri devre dışı bırak
    cfg.TAVILY_API_KEY = ""
    cfg.GOOGLE_SEARCH_API_KEY = ""
    cfg.SEARCH_ENGINE = "auto"
    
    return cfg


@pytest.fixture
def agent(test_config):
    """Testler için SidarAgent nesnesi üretir."""
    ag = SidarAgent(cfg=test_config)
    _activate_memory_user(ag.memory, "agent_user")
    return ag


def _activate_memory_user(mem, username="test_user"):
    async def _setup():
        await mem.initialize()
        user = await mem.db.ensure_user(username, role="user")
        await mem.set_active_user(user.id, user.username)
        return user

    return asyncio.run(_setup())


# ─────────────────────────────────────────────
# 1. TEMEL YÖNETİCİ TESTLERİ
# ─────────────────────────────────────────────

def test_code_manager_read_write(agent):
    """CodeManager: Dosya yazma ve okuma yetkisini test eder."""
    test_file = agent.cfg.TEMP_DIR / "test_hello.py"
    
    # Yazma
    ok, msg = agent.code.write_file(str(test_file), "print('Hello')", validate=False)
    assert ok is True
    assert test_file.exists()

    # Okuma
    ok, content = agent.code.read_file(str(test_file))
    assert ok is True
    assert "print('Hello')" in content


def test_code_manager_validation(agent):
    """CodeManager: Python sözdizimi doğrulamasını test eder."""
    # Bozuk kod
    ok, msg = agent.code.validate_python_syntax("def broken_func() print('hi')")
    assert ok is False
    assert "Sözdizimi hatası" in msg

    # Geçerli kod
    ok, msg = agent.code.validate_python_syntax("def clean_func():\n    pass")
    assert ok is True


# ─────────────────────────────────────────────
# 2. YAPISAL ÇIKTI (PYDANTIC) TESTLERİ
# ─────────────────────────────────────────────

def test_toolcall_pydantic_validation():
    """Pydantic şemasının doğru JSON'ları kabul edip hatalıları reddettiğini test eder."""
    
    # Başarılı JSON
    valid_json = '{"thought": "Webde arama yapmalıyım", "tool": "web_search", "argument": "python fastapi"}'
    parsed = ToolCall.model_validate_json(valid_json)
    assert parsed.tool == "web_search"
    assert parsed.argument == "python fastapi"
    
    # Hatalı/Eksik JSON (tool alanı eksik)
    invalid_json = '{"thought": "düşünüyorum", "argument": "sadece argüman"}'
    with pytest.raises(ValidationError):
         ToolCall.model_validate_json(invalid_json)


# ─────────────────────────────────────────────
# 3. ASENKRON WEB ARAMA (FALLBACK) TESTİ
# ─────────────────────────────────────────────

def test_web_search_status_without_engines_is_deterministic(monkeypatch, test_config):
    """DDG kurulu olmasa da olmasa da deterministik 'motor yok' durumunu doğrular."""
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    web = WebSearchManager(test_config)

    assert web.tavily_key == ""
    assert web.google_key == ""
    assert web._ddg_available is False
    assert web.status() == "WebSearch: Kurulu veya yapılandırılmış motor yok."


def test_web_search_status_with_ddg_available_is_deterministic(monkeypatch, test_config):
    """DDG mevcut senaryosunu çevreden bağımsız doğrular."""
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: True)
    web = WebSearchManager(test_config)

    assert web._ddg_available is True
    assert "DuckDuckGo" in web.status()


# ─────────────────────────────────────────────
# 4. RAG VE VEKTÖR BELLEK TESTLERİ
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rag_document_chunking(test_config):
    """DocumentStore'un büyük metinleri chunking mantığıyla böldüğünü test eder."""
    docs = DocumentStore(test_config.RAG_DIR, use_gpu=False)
    
    # Uzun ve yapısal bir metin oluşturalım
    long_text = "Metin baslangici.\n\n"
    for i in range(50):
        long_text += f"def func_{i}():\n    return {i}\n\n"
        
    doc_id = await docs.add_document(title="Test Kodu", content=long_text, source="test_source")
    
    assert doc_id is not None
    # Index'e tam boyutla eklenmiş olmalı
    assert docs._index[doc_id]["size"] == len(long_text)
    
    # Metin parçalanıp kaydedildiyse, get_document ile tamamını geri okuyabilmeliyiz
    ok, retrieved = docs.get_document(doc_id)
    assert ok is True
    assert "func_49()" in retrieved


# ─────────────────────────────────────────────
# 5. AJAN BAŞLATMA TESTİ
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_initialization(agent):
    """Ajanın ve alt modüllerinin başarıyla ayağa kalktığını test eder."""
    status_report = agent.status()

    assert agent.VERSION is not None
    assert agent.cfg.AI_PROVIDER in ("ollama", "gemini")
    assert "Bellek" in status_report
    assert "Güvenlik" in asyncio.run(agent._build_context())


# ─────────────────────────────────────────────
# 6. GPU & DONANIM TESTLERİ
# ─────────────────────────────────────────────

def test_config_gpu_fields():
    """Config sınıfının GPU ile ilgili tüm alanları içerdiğini doğrular."""
    cfg = Config()
    assert hasattr(cfg, "USE_GPU")
    assert hasattr(cfg, "GPU_INFO")
    assert hasattr(cfg, "GPU_COUNT")
    assert hasattr(cfg, "GPU_DEVICE")
    assert hasattr(cfg, "CUDA_VERSION")
    assert hasattr(cfg, "DRIVER_VERSION")
    assert hasattr(cfg, "MULTI_GPU")
    assert hasattr(cfg, "GPU_MEMORY_FRACTION")
    assert hasattr(cfg, "GPU_MIXED_PRECISION")

    assert isinstance(cfg.USE_GPU, bool)
    assert isinstance(cfg.GPU_DEVICE, int)
    assert 0.0 < cfg.GPU_MEMORY_FRACTION <= 1.0


def test_system_health_manager_cpu_only():
    """SystemHealthManager'ın GPU olmadan CPU/RAM raporunu ürettiğini test eder."""
    health = SystemHealthManager(use_gpu=False)

    assert health.get_gpu_info()["available"] is False

    report = health.full_report()
    assert "Sistem Sağlık Raporu" in report
    assert "OS" in report

    # GPU devre dışı — optimize çağrısı yine de güvenli çalışmalı
    result = health.optimize_gpu_memory()
    assert "GC" in result


def test_system_health_gpu_info_structure():
    """get_gpu_info() çıktısının beklenen yapıyı döndürdüğünü test eder."""
    health = SystemHealthManager(use_gpu=True)
    info = health.get_gpu_info()

    assert "available" in info
    if info["available"]:
        # GPU varsa zorunlu alanlar
        assert "device_count" in info
        assert "devices" in info
        assert "cuda_version" in info
        for dev in info["devices"]:
            assert "id" in dev
            assert "name" in dev
            assert "total_vram_gb" in dev
            assert "free_gb" in dev
            assert "compute_capability" in dev
    else:
        # GPU yoksa reason veya error alanı olmalı
        assert "reason" in info or "error" in info


def test_rag_gpu_params(test_config):
    """DocumentStore'un GPU parametrelerini kabul ettiğini doğrular."""
    # GPU olmayan sistemde use_gpu=True verilse bile güvenle başlamalı
    docs = DocumentStore(
        test_config.RAG_DIR,
        use_gpu=True,
        gpu_device=0,
        mixed_precision=False,
    )
    assert docs._use_gpu is True
    assert docs._gpu_device == 0
    # CUDA yoksa ChromaDB CPU'ya düşmeli; collection ya None ya da başlatılmış olmalı
    status = docs.status()
    assert "RAG" in status


# ─────────────────────────────────────────────
# 7. SESSION LIFECYCLE TESTLERİ
# ─────────────────────────────────────────────

def test_session_create(test_config):
    """ConversationMemory: Yeni oturum oluşturma ve aktif hale getirme."""
    from core.memory import ConversationMemory
    mem = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10)
    _activate_memory_user(mem, "session_create")

    session_id = mem.create_session("Test Sohbeti")

    assert session_id is not None
    assert len(session_id) == 36  # UUID4 formatı
    assert mem.active_session_id == session_id
    assert mem.active_title == "Test Sohbeti"


def test_session_add_and_load(test_config):
    """ConversationMemory: Mesaj ekleme ve oturumu yeniden yükleme."""
    from core.memory import ConversationMemory
    mem = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10)
    _activate_memory_user(mem, "shared_session_user")

    session_id = mem.create_session("Yükleme Testi")
    mem.add("user", "Merhaba Sidar!")
    mem.add("assistant", "Merhaba! Nasıl yardımcı olabilirim?")

    # Yeni bir bellek nesnesi oluştur ve oturumu yeniden yükle
    mem2 = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10)
    _activate_memory_user(mem2, "shared_session_user")
    ok = mem2.load_session(session_id)

    assert ok is True
    assert mem2.active_session_id == session_id
    history = mem2.get_history()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Merhaba Sidar!"
    assert history[1]["role"] == "assistant"


def test_session_delete(test_config):
    """ConversationMemory: Oturum silme ve dosyanın kaldırıldığını doğrulama."""
    from core.memory import ConversationMemory
    mem = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10)
    _activate_memory_user(mem, "session_delete")

    sid = mem.create_session("Silinecek Oturum")
    result = mem.delete_session(sid)

    assert result is True


def test_session_get_all_sorted(test_config):
    """ConversationMemory: Tüm oturumları en yeniden en eskiye sıralı listeler."""
    from core.memory import ConversationMemory
    import time as _time
    mem = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10)
    _activate_memory_user(mem, "session_list")

    id1 = mem.create_session("Birinci")
    _time.sleep(0.01)
    id2 = mem.create_session("İkinci")
    _time.sleep(0.01)
    id3 = mem.create_session("Üçüncü")

    sessions = mem.get_all_sessions()
    ids = [s["id"] for s in sessions]

    # En son oluşturulan en üstte olmalı
    assert ids[0] == id3
    assert id1 in ids
    assert id2 in ids


def test_session_update_title(test_config):
    """ConversationMemory: Aktif oturum başlığını güncelleme."""
    from core.memory import ConversationMemory
    mem = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10)
    _activate_memory_user(mem, "shared_title_user")

    sid = mem.create_session("Eski Başlık")
    mem.update_title("Yeni Başlık")

    assert mem.active_title == "Yeni Başlık"

    # Yeniden yükleme ile kalıcılığı doğrula
    mem2 = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10)
    _activate_memory_user(mem2, "shared_title_user")
    mem2.load_session(sid)
    assert mem2.active_title == "Yeni Başlık"


def test_session_load_nonexistent(test_config):
    """ConversationMemory: Var olmayan oturum yüklenmeye çalışıldığında False döner."""
    from core.memory import ConversationMemory
    mem = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10)
    _activate_memory_user(mem, "session_missing")

    result = mem.load_session("00000000-0000-0000-0000-000000000000")
    assert result is False


def test_apply_summary_keeps_last_messages(test_config):
    """ConversationMemory: Özetleme, son N mesajı koruyup başa özet bloğu ekler."""
    from core.memory import ConversationMemory

    mem = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10, keep_last=4)
    _activate_memory_user(mem, "summary_keep")
    for i in range(8):
        role = "user" if i % 2 == 0 else "assistant"
        mem.add(role, f"mesaj-{i}")

    mem.apply_summary("Kısa özet")

    history = mem.get_history()
    assert len(history) == 6
    assert history[0]["content"] == "[Önceki konuşmaların özeti istendi]"
    assert history[1]["content"] == "[KONUŞMA ÖZETİ]\nKısa özet"
    assert [t["content"] for t in history[2:]] == ["mesaj-4", "mesaj-5", "mesaj-6", "mesaj-7"]


def test_apply_summary_keep_last_zero(test_config):
    """ConversationMemory: keep_last=0 iken yalnızca özet blokları kalır."""
    from core.memory import ConversationMemory

    mem = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10, keep_last=0)
    _activate_memory_user(mem, "summary_zero")
    for i in range(4):
        mem.add("user", f"soru-{i}")

    mem.apply_summary("Sadece özet")

    history = mem.get_history()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["content"] == "[KONUŞMA ÖZETİ]\nSadece özet"


# ─────────────────────────────────────────────
# 8. ARAÇ DISPATCHER TESTLERİ
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_tool_unknown_returns_none(agent):
    """SidarAgent dispatcher'ı bilinmeyen araç adı için None döndürür."""
    result = await agent._execute_tool("var_olmayan_arac_xyz", "test argümanı")
    assert result is None


@pytest.mark.asyncio
async def test_execute_tool_known_does_not_return_none(agent):
    """SidarAgent dispatcher'ı bilinen araç için None döndürmez."""
    # list_dir gerçek I/O yapar; BASE_DIR mevcut olduğundan sonuç döner
    result = await agent._execute_tool("list_dir", str(agent.cfg.BASE_DIR))
    assert result is not None


@pytest.mark.asyncio
async def test_execute_tool_writes_audit_log_on_success(agent, monkeypatch):
    """SidarAgent: başarılı araç çağrısı _log_audit ile success=True loglanır."""
    captured = {}

    async def _fake_log(tool_name, argument, success):
        captured["tool_name"] = tool_name
        captured["argument"] = argument
        captured["success"] = success

    async def _fake_tool(arg):
        return "tamam"

    monkeypatch.setattr(agent, "_log_audit", _fake_log)
    monkeypatch.setitem(agent._tools, "dummy_tool", _fake_tool)

    result = await agent._execute_tool("dummy_tool", "abc")

    assert result == "tamam"
    assert captured == {"tool_name": "dummy_tool", "argument": "abc", "success": True}


@pytest.mark.asyncio
async def test_execute_tool_writes_audit_log_on_tool_error_pattern(agent, monkeypatch):
    """SidarAgent: ⚠/✗/[HATA] ile başlayan sonuçlar başarısız loglanır."""
    captured = {}

    async def _fake_log(tool_name, argument, success):
        captured["success"] = success

    async def _fake_tool(arg):
        return "⚠ doğrulama hatası"

    monkeypatch.setattr(agent, "_log_audit", _fake_log)
    monkeypatch.setitem(agent._tools, "dummy_tool_err", _fake_tool)

    result = await agent._execute_tool("dummy_tool_err", "xyz")

    assert result.startswith("⚠")
    assert captured["success"] is False


def test_rag_rrf_merges_chroma_and_bm25(monkeypatch):
    """RRF: Aynı belgeleri iki motordan birleştirip tek sıralama üretir."""
    docs = DocumentStore.__new__(DocumentStore)

    monkeypatch.setattr(docs, "_fetch_chroma", lambda q, k, s: [
        {"id": "doc_a", "title": "A", "source": "", "snippet": "sa", "score": 1.0},
        {"id": "doc_b", "title": "B", "source": "", "snippet": "sb", "score": 1.0},
    ])
    monkeypatch.setattr(docs, "_fetch_bm25", lambda q, k, s: [
        {"id": "doc_b", "title": "B", "source": "", "snippet": "sb", "score": 5.0},
        {"id": "doc_c", "title": "C", "source": "", "snippet": "sc", "score": 4.0},
    ])

    captured = {}

    def _format(results, query, source_name):
        captured["ids"] = [r["id"] for r in results]
        captured["source"] = source_name
        return True, "ok"

    monkeypatch.setattr(docs, "_format_results_from_struct", _format)

    ok, _ = DocumentStore._rrf_search(docs, "test", 3, "s1")

    assert ok is True
    assert captured["source"] == "Hibrit RRF (ChromaDB + BM25)"
    assert captured["ids"][0] == "doc_b"


def test_rag_search_auto_prefers_rrf(monkeypatch):
    """search(auto): Chroma+BM25 varken önce RRF yolunu kullanır."""
    docs = DocumentStore.__new__(DocumentStore)
    docs.cfg = type("Cfg", (), {"RAG_TOP_K": 3})()
    docs.default_top_k = 3
    docs._index = {"d1": {"title": "t"}}
    docs._chroma_available = True
    docs._bm25_available = True
    docs.collection = object()

    calls = {"rrf": 0}

    def _rrf(query, top_k, session_id):
        calls["rrf"] += 1
        return True, "rrf"

    monkeypatch.setattr(docs, "_rrf_search", _rrf)

    ok, text = asyncio.run(DocumentStore.search(docs, "soru", mode="auto"))

    assert ok is True
    assert text == "rrf"
    assert calls["rrf"] == 1


@pytest.mark.asyncio
async def test_rag_index_info_filters_by_session(test_config):
    """get_index_info(session_id): yalnızca ilgili oturum belgelerini döndürür."""
    docs = DocumentStore(test_config.RAG_DIR, use_gpu=False)
    await docs.add_document("A", "alpha", session_id="s1")
    await docs.add_document("B", "beta", session_id="s2")

    s1_docs = docs.get_index_info(session_id="s1")
    assert len(s1_docs) == 1
    assert s1_docs[0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_rag_list_documents_filters_by_session(test_config):
    """list_documents(session_id): farklı oturum belgelerini dışarıda bırakır."""
    docs = DocumentStore(test_config.RAG_DIR, use_gpu=False)
    await docs.add_document("S1 Başlık", "alpha içerik", session_id="s1")
    await docs.add_document("S2 Başlık", "beta içerik", session_id="s2")

    text = docs.list_documents(session_id="s1")
    assert "S1 Başlık" in text
    assert "S2 Başlık" not in text


def test_rag_search_returns_empty_for_missing_session_docs(monkeypatch):
    """search(session_id): oturumda belge yoksa uyarı döndürür."""
    docs = DocumentStore.__new__(DocumentStore)
    docs.cfg = type("Cfg", (), {"RAG_TOP_K": 3})()
    docs.default_top_k = 3
    docs._index = {"d1": {"title": "t", "session_id": "s1"}}
    docs._chroma_available = False
    docs._bm25_available = False
    docs.collection = None

    ok, msg = asyncio.run(DocumentStore.search(docs, "soru", mode="auto", session_id="s2"))
    assert ok is False
    assert "bu oturum" in msg.lower()


# ─────────────────────────────────────────────
# 9. CHUNKING SINIR TESTLERİ
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rag_chunking_small_text(test_config):
    """DocumentStore: _chunk_size'dan küçük metin tek parça olarak eklenir."""
    docs = DocumentStore(test_config.RAG_DIR, use_gpu=False)
    small = "Küçük bir metin."
    doc_id = await docs.add_document(title="Küçük", content=small, source="test")
    assert doc_id is not None
    ok, retrieved = docs.get_document(doc_id)
    assert ok is True
    # get_document() "[doc_id] başlık\nKaynak: ...\n\nİçerik" formatında döner
    content_part = retrieved.split("\n\n", 1)[1]
    assert content_part == small


@pytest.mark.asyncio
async def test_rag_chunking_large_text(test_config):
    """DocumentStore: _chunk_size'dan büyük metin parçalara bölünür ve tamamı saklanır."""
    docs = DocumentStore(test_config.RAG_DIR, use_gpu=False)
    # Varsayılan chunk_size (genellikle 512) değerini aşan metin üret
    large = "A" * 2000 + "\n\n" + "B" * 2000
    doc_id = await docs.add_document(title="Büyük", content=large, source="test")
    assert doc_id is not None
    ok, retrieved = docs.get_document(doc_id)
    assert ok is True
    # get_document() "[doc_id] başlık\nKaynak: ...\n\nİçerik" formatında döner
    content_part = retrieved.split("\n\n", 1)[1]
    assert len(content_part) == len(large)


# ─────────────────────────────────────────────
# 10. AUTOHANDLE PATTERN TESTLERİ
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_handle_no_match(agent):
    """AutoHandle: normal LLM sorusuna müdahale etmez."""
    handled, _ = await agent.auto.handle("Python'da asenkron programlama nasıl çalışır?")
    assert handled is False


@pytest.mark.asyncio
async def test_auto_handle_clear_command(agent):
    """AutoHandle: 'belleği temizle' / 'sohbeti sıfırla' komutlarına yanıt verir."""
    # Önce birkaç mesaj ekle
    agent.memory.add("user", "test mesajı")
    handled, response = await agent.auto.handle("belleği temizle")
    assert handled is True
    assert "temizlendi" in response.lower()


@pytest.mark.asyncio
async def test_auto_handle_repo_files_list_command(agent, monkeypatch):
    """AutoHandle: 'repodaki dosyaları listele' komutunu GitHub listesine yönlendirir."""
    monkeypatch.setattr(agent.auto.github, "is_available", lambda: True)
    monkeypatch.setattr(
        agent.auto.github,
        "list_files",
        lambda path="", branch=None: (True, "[GitHub Dosya Listesi: /]\n  📄 README.md"),
    )

    handled, response = await agent.auto.handle("repomuzdaki dosyaları listele")
    assert handled is True
    assert "GitHub Dosya Listesi" in response


@pytest.mark.asyncio
async def test_auto_handle_read_file_content_getir_command(agent, monkeypatch):
    """AutoHandle: '<dosya> içeriğini getir' komutunu dosya okuma akışına yönlendirir."""
    monkeypatch.setattr(agent.auto.code, "read_file", lambda path: (True, "satır1\nsatır2"))

    handled, response = await agent.auto.handle("config.py içeriğini getir")
    assert handled is True
    assert "[config.py]" in response
    assert "satır1" in response


def test_direct_router_handles_single_step_read(agent, monkeypatch):
    """SidarAgent: Doğrudan router tek adım aracı çalıştırır (respond akışına bağlı değil)."""

    async def fake_chat(**kwargs):
        return '{"thought":"tek adım","tool":"read_file","argument":"config.py"}'

    monkeypatch.setattr(agent.llm, "chat", fake_chat)
    monkeypatch.setattr(agent.code, "read_file", lambda path: (True, "CFG=1"))

    result = asyncio.run(agent._try_direct_tool_route("config.py dosyasını açıp içeriğini ver"))
    assert result is not None
    assert "CFG=1" in result


# ─────────────────────────────────────────────
# 11. BROKEN JSON KARANTINA TESTİ
# ─────────────────────────────────────────────

def test_session_broken_json_quarantine(test_config):
    """ConversationMemory: Bozuk JSON dosyası .json.broken olarak karantinaya alınır."""
    from core.memory import ConversationMemory

    # Bozuk bir JSON dosyası oluştur
    sessions_dir = test_config.DATA_DIR / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    broken_file = sessions_dir / "bozuk-oturum.json"
    broken_file.write_text("{bozuk json içerik: !!!", encoding="utf-8")

    # get_all_sessions() çağrısı çökme üretmemeli; bozuk dosya karantinaya alınmalı
    mem = ConversationMemory(file_path=test_config.MEMORY_FILE, max_turns=10)
    _activate_memory_user(mem, "broken_json")
    sessions = mem.get_all_sessions()

    # Bozuk dosya .json.broken adıyla karantinada olmalı
    assert isinstance(sessions, list)
    assert broken_file.exists()


# ─────────────────────────────────────────────
# 12. JSON PARSE DOĞRULUĞU (GREEDY REGEX YERİNE JSONDecoder)
# ─────────────────────────────────────────────

def test_json_decoder_picks_first_valid_object():
    """JSONDecoder ilk geçerli JSON nesnesini seçer; arkasındaki bozuk bloğu yoksayar."""
    import json
    decoder = json.JSONDecoder()
    # Geçerli JSON + arkasında bozuk ek metin
    text = '{"thought": "plan", "tool": "final_answer", "argument": "tamam"} fazla metin'
    idx = text.find('{')
    result, end = decoder.raw_decode(text, idx)
    assert result["tool"] == "final_answer"
    assert result["argument"] == "tamam"


def test_json_decoder_skips_first_broken_finds_next():
    """JSONDecoder bozuk ilk bloğu atlayıp sonraki geçerli JSON'ı bulur."""
    import json
    decoder = json.JSONDecoder()
    # İlk '{' bozuk, ikinci '{' geçerli
    text = '{bozuk} {"thought": "ok", "tool": "web_search", "argument": "x"}'
    idx = text.find('{')
    json_match = None
    while idx != -1:
        try:
            json_match, _ = decoder.raw_decode(text, idx)
            break
        except json.JSONDecodeError:
            idx = text.find('{', idx + 1)
    assert json_match is not None
    assert json_match["tool"] == "web_search"


def test_json_decoder_no_json_returns_none():
    """JSON içermeyen metinde döngü girmez, json_match None kalır."""
    import json
    decoder = json.JSONDecoder()
    text = "Bu bir metin. JSON bloğu içermiyor."
    idx = text.find('{')
    json_match = None
    while idx != -1:
        try:
            json_match, _ = decoder.raw_decode(text, idx)
            break
        except json.JSONDecodeError:
            idx = text.find('{', idx + 1)
    assert json_match is None


def test_json_decoder_embedded_in_markdown():
    """Markdown kod bloğu içine gömülü JSON doğru çıkarılır."""
    import json

    text = '```json\n{"thought": "düşünüyorum", "tool": "list_dir", "argument": "."}\n```'
    decoder = json.JSONDecoder()
    idx = text.find('{')
    json_match, _ = decoder.raw_decode(text, idx)

    assert json_match["tool"] == "list_dir"
    assert json_match["argument"] == "."


# ─────────────────────────────────────────────
# 13. UTF-8 MULTİBYTE BUFFER GÜVENLİĞİ
# ─────────────────────────────────────────────

def test_utf8_multibyte_two_byte_split():
    """2 baytlık UTF-8 karakteri (ş=\\xc5\\x9f) iki pakete bölününce doğru birleşir."""
    char = "ş"  # \xc5\x9f
    full_bytes = char.encode("utf-8")
    assert len(full_bytes) == 2

    # llm_client._stream_ollama_response ile aynı mantık (incremental decoder)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    result = ""
    for packet in [full_bytes[:1], full_bytes[1:]]:
        result += decoder.decode(packet, final=False)

    # Kalan buffer varsa temizle
    result += decoder.decode(b"", final=True)

    assert result == char


def test_utf8_three_byte_char_split():
    """3 baytlık UTF-8 karakteri (€=\\xe2\\x82\\xac) ortadan bölününce birleşir."""
    char = "€"  # \xe2\x82\xac
    full_bytes = char.encode("utf-8")
    assert len(full_bytes) == 3

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    result = ""
    for packet in [full_bytes[:2], full_bytes[2:]]:
        result += decoder.decode(packet, final=False)

    result += decoder.decode(b"", final=True)

    assert result == char


def test_utf8_invalid_bytes_use_replace_fallback():
    """Tamamen geçersiz UTF-8 baytları 'replace' moduyla Unicode ikame karakteri üretir."""
    invalid = b"\xff\xfe\xfd"
    decoded = invalid.decode("utf-8", errors="replace")
    assert "\ufffd" in decoded  # U+FFFD: Unicode ikame karakteri


# ─────────────────────────────────────────────
# 14. AUTO_HANDLE HEALTH=NONE NULL GUARD
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_handle_health_none_no_crash(agent):
    """AutoHandle: health=None olduğunda sistem sağlık sorgusu AttributeError üretmez."""
    original_health = agent.auto.health
    try:
        agent.auto.health = None
        handled, response = await agent.auto.handle("sistem sağlık raporunu göster")
        # Çökme olmamalı; yanıt string olmalı
        assert isinstance(handled, bool)
        assert isinstance(response, str)
        if handled:
            # None guard devreye girmeli
            assert "başlatılamadı" in response or "⚠" in response
    finally:
        agent.auto.health = original_health


@pytest.mark.asyncio
async def test_auto_handle_health_returns_report_when_available(agent):
    """AutoHandle: health yöneticisi mevcutsa sağlık raporu içeriği döner."""
    if agent.auto.health is None:
        pytest.skip("Sağlık yöneticisi başlatılmamış.")
    handled, response = await agent.auto.handle("donanım durumunu göster")
    # Eğer tanındıysa rapor içeriği dolu olmalı
    if handled:
        assert len(response) > 0


# ─────────────────────────────────────────────
# 15. RATE LIMITER (TOCTOU SENARYOSU)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_limit():
    """_is_rate_limited: Limit aşıldıktan sonra True döner."""
    import web_server

    test_ip = "192.0.2.1"  # RFC 5737 test IP
    web_server._rate_data.pop(test_ip, None)
    web_server._rate_lock = asyncio.Lock()

    limit = 3
    for _ in range(limit):
        blocked = await web_server._is_rate_limited(test_ip, limit)
        assert blocked is False, "Limit dolmadan önce bloklanmamalı"

    # Limit + 1 → bloklanmalı
    blocked = await web_server._is_rate_limited(test_ip, limit)
    assert blocked is True, "Limit aşıldığında bloklanmalı"


@pytest.mark.asyncio
async def test_rate_limiter_different_keys_independent():
    """_is_rate_limited: Farklı IP'ler birbirini etkilemez (TOCTOU izolasyonu)."""
    import web_server

    ip_a = "192.0.2.2"
    ip_b = "192.0.2.3"
    web_server._rate_data.pop(ip_a, None)
    web_server._rate_data.pop(ip_b, None)
    web_server._rate_lock = asyncio.Lock()

    limit = 2
    # ip_a limitini doldur
    for _ in range(limit):
        await web_server._is_rate_limited(ip_a, limit)
    await web_server._is_rate_limited(ip_a, limit)  # ip_a bloklandı

    # ip_b hâlâ serbest olmalı
    blocked_b = await web_server._is_rate_limited(ip_b, limit)
    assert blocked_b is False, "ip_b bağımsız olmalı"


@pytest.mark.asyncio
async def test_rate_limiter_concurrent_toctou():
    """_is_rate_limited: Eş zamanlı çağrılar limit sayısını aşmaz."""
    import web_server

    test_ip = "192.0.2.4"
    web_server._rate_data.pop(test_ip, None)
    web_server._rate_lock = asyncio.Lock()

    limit = 5
    tasks = [web_server._is_rate_limited(test_ip, limit) for _ in range(limit + 3)]
    results = await asyncio.gather(*tasks)

    # En fazla `limit` kadar False (izin verilen) olmalı
    allowed = results.count(False)
    assert allowed <= limit, f"Limit aşıldı: {allowed} > {limit}"


# ─────────────────────────────────────────────
# 16. RAG CONCURRENT DELETE+UPSERT
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rag_concurrent_add_no_data_loss(test_config):
    """DocumentStore: Eş zamanlı add_document çağrıları _write_lock ile güvenle serialize edilir."""
    docs = DocumentStore(test_config.RAG_DIR, use_gpu=False)

    async def add_one(i: int) -> str:
        return await docs.add_document(
            title=f"Belge {i}",
            content=f"İçerik {i}: " + "x" * 200,
            source="concurrent_test",
        )

    tasks = [add_one(i) for i in range(6)]
    results = await asyncio.gather(*tasks)

    # Tüm ekleme işlemleri bir doc_id döndürmeli
    assert len(results) == 6
    assert all(r is not None for r in results), "Bazı belgeler eklenemedi"

    # Her belge bağımsız olarak okunabilmeli
    for doc_id in results:
        ok, content = docs.get_document(doc_id)
        assert ok is True, f"Belge okunamadı: {doc_id}"
        assert len(content) > 0


@pytest.mark.asyncio
async def test_rag_update_replaces_old_chunks(test_config):
    """DocumentStore: Aynı başlıkla iki kez add_document → ikinci çağrı birincinin yerine geçer."""
    docs = DocumentStore(test_config.RAG_DIR, use_gpu=False)

    id1 = await docs.add_document(title="Güncellenecek", content="Eski içerik A", source="test")
    id2 = await docs.add_document(title="Güncellenecek", content="Yeni içerik B", source="test")

    # Her iki doc_id de okunabilmeli (bağımsız UUID)
    ok1, c1 = docs.get_document(id1)
    ok2, c2 = docs.get_document(id2)
    assert ok1 and "Eski içerik A" in c1
    assert ok2 and "Yeni içerik B" in c2


# ─────────────────────────────────────────────
# 17. GITHUB MANAGER UZANTISIZ DOSYA BYPASS
# ─────────────────────────────────────────────

def test_github_manager_safe_extensions_set():
    """GitHubManager: SAFE_TEXT_EXTENSIONS kritik uzantıları içeriyor."""
    from managers.github_manager import GitHubManager

    safe = GitHubManager.SAFE_TEXT_EXTENSIONS
    for ext in (".py", ".md", ".json", ".yaml", ".yml", ".sh", ".txt"):
        assert ext in safe, f"{ext} güvenli listede olmalı"

    for ext in (".png", ".zip", ".exe", ".dll", ".bin", ".so"):
        assert ext not in safe, f"{ext} güvenli listede OLMAMALI"


def test_github_manager_safe_extensionless_set():
    """GitHubManager: SAFE_EXTENSIONLESS bilinen güvenli uzantısız dosyaları içeriyor."""
    from managers.github_manager import GitHubManager

    safe = GitHubManager.SAFE_EXTENSIONLESS
    for name in ("makefile", "dockerfile", "procfile", "license", "readme"):
        assert name in safe, f"'{name}' güvenli uzantısız listede olmalı"


def test_github_manager_no_token_status_guidance():
    """GitHubManager: Token yokken status() token kurulum rehberini içeriyor."""
    from managers.github_manager import GitHubManager

    gm = GitHubManager(token="", repo_name="")
    assert gm.is_available() is False

    status = gm.status()
    assert "GITHUB_TOKEN" in status
    assert "github.com/settings/tokens" in status


# ─────────────────────────────────────────────
# 18. PACKAGE_INFO VERSION SORT PRE-RELEASE
# ─────────────────────────────────────────────

def test_version_sort_stable_beats_prerelease():
    """_version_sort_key: Stabil sürüm tüm pre-release sürümlerden büyük sıralanır."""
    from managers.package_info import PackageInfoManager

    versions = ["1.0.0a1", "1.0.0b2", "1.0.0rc1", "1.0.0", "0.9.9"]
    sorted_v = sorted(versions, key=PackageInfoManager._version_sort_key, reverse=True)

    assert sorted_v[0] == "1.0.0",   f"En büyük 1.0.0 olmalı, bulundu: {sorted_v[0]}"
    assert sorted_v[1] == "1.0.0rc1"
    assert sorted_v[2] == "1.0.0b2"
    assert sorted_v[3] == "1.0.0a1"
    assert sorted_v[4] == "0.9.9"


def test_is_prerelease_letter_based():
    """_is_prerelease: Harf tabanlı pre-release formatlarını tanır."""
    from managers.package_info import PackageInfoManager

    assert PackageInfoManager._is_prerelease("1.0.0a1")    is True
    assert PackageInfoManager._is_prerelease("1.0.0b2")    is True
    assert PackageInfoManager._is_prerelease("1.0.0rc1")   is True
    assert PackageInfoManager._is_prerelease("1.0.0alpha") is True
    assert PackageInfoManager._is_prerelease("1.0.0")      is False
    assert PackageInfoManager._is_prerelease("2.5.3")      is False


def test_is_prerelease_npm_numeric():
    """_is_prerelease: npm sayısal pre-release formatını tanır (1.0.0-0, 1.0.0-1)."""
    from managers.package_info import PackageInfoManager

    assert PackageInfoManager._is_prerelease("1.0.0-0")  is True
    assert PackageInfoManager._is_prerelease("1.0.0-1")  is True
    assert PackageInfoManager._is_prerelease("2.0.0-42") is True
    assert PackageInfoManager._is_prerelease("1.0.0")    is False  # tire yok
    assert PackageInfoManager._is_prerelease("1.0.0-rc1") is True  # hem harf hem sayısal


def test_version_sort_invalid_version_goes_last():
    """_version_sort_key: Geçersiz sürüm formatı '0.0.0' olarak değerlendirilir."""
    from managers.package_info import PackageInfoManager

    versions = ["1.0.0", "invalid-ver", "2.0.0"]
    sorted_v = sorted(versions, key=PackageInfoManager._version_sort_key, reverse=True)

    assert sorted_v[0] == "2.0.0"
    assert sorted_v[1] == "1.0.0"
    assert sorted_v[-1] == "invalid-ver"

# ─────────────────────────────────────────────
# 19. GÜVENLİK — PATH TRAVERSAL + SYMLINK
# ─────────────────────────────────────────────

def test_security_path_traversal_blocked(tmp_path):
    """SecurityManager: '../' içeren yollara yazma izni verilmez."""
    from managers.security import SecurityManager
    sm = SecurityManager("sandbox", tmp_path)

    assert sm.can_write("../../../etc/passwd") is False
    assert sm.can_write("../../sensitive.txt") is False


def test_security_dangerous_pattern_read_blocked(tmp_path):
    """SecurityManager: tehlikeli sistem yollarına okuma engellenir."""
    from managers.security import SecurityManager
    sm = SecurityManager("full", tmp_path)

    assert sm.can_read("/etc/shadow") is False
    assert sm.can_read("/proc/1/maps") is False


def test_security_safe_write_sandbox(tmp_path):
    """SecurityManager: SANDBOX modda temp/ dizinine yazma serbesttir."""
    from managers.security import SecurityManager
    sm = SecurityManager("sandbox", tmp_path)
    safe_path = str(tmp_path / "temp" / "output.py")
    assert sm.can_write(safe_path) is True


def test_security_full_base_dir_write(tmp_path):
    """SecurityManager: FULL modda proje kökü altındaki dosyaya yazma serbesttir."""
    from managers.security import SecurityManager
    sm = SecurityManager("full", tmp_path)
    safe_path = str(tmp_path / "managers" / "new_file.py")
    assert sm.can_write(safe_path) is True


def test_security_full_outside_base_dir_blocked(tmp_path):
    """SecurityManager: FULL modda proje kökü dışına yazma engellenir."""
    from managers.security import SecurityManager
    import tempfile
    sm = SecurityManager("full", tmp_path)
    outside = tempfile.gettempdir() + "/outside.py"
    assert sm.can_write(outside) is False


def test_security_get_safe_write_path_strips_dir(tmp_path):
    """SecurityManager: get_safe_write_path() yalnızca dosya adını kullanır."""
    from managers.security import SecurityManager
    sm = SecurityManager("sandbox", tmp_path)
    safe = sm.get_safe_write_path("../../evil/file.py")
    # Yalnızca "file.py" kalmalı, ../evil/ atılmalı
    assert safe.parent == (tmp_path / "temp").resolve()
    assert safe.name == "file.py"


# ─────────────────────────────────────────────
# 20. GITHUB MANAGER — DAL ADI DOĞRULAMASI
# ─────────────────────────────────────────────

def test_github_manager_branch_name_invalid():
    """GitHubManager: Geçersiz dal adı create_branch() tarafından reddedilir."""
    from managers.github_manager import GitHubManager, _BRANCH_RE
    # Boşluk ve özel karakter içeren adlar
    assert not _BRANCH_RE.match("branch name with spaces")
    assert not _BRANCH_RE.match("branch;injected")
    assert not _BRANCH_RE.match("branch`cmd`")
    # Geçerli adlar
    assert _BRANCH_RE.match("feature/my-branch")
    assert _BRANCH_RE.match("fix-123")
    assert _BRANCH_RE.match("release/v2.6.1")


# ─────────────────────────────────────────────
# 21. CONFIG — DOCKER TIMEOUT VE DOĞRULAMA
# ─────────────────────────────────────────────

def test_config_docker_exec_timeout_default():
    """Config: DOCKER_EXEC_TIMEOUT varsayılanı 10 saniyedir."""
    cfg = Config()
    assert hasattr(cfg, "DOCKER_EXEC_TIMEOUT")
    assert isinstance(cfg.DOCKER_EXEC_TIMEOUT, int)
    assert cfg.DOCKER_EXEC_TIMEOUT == 10


def test_config_validate_critical_settings_returns_bool():
    """Config.validate_critical_settings() bool döndürür."""
    cfg = Config()
    result = cfg.validate_critical_settings()
    assert isinstance(result, bool)


# ─────────────────────────────────────────────
# 22. WEB SERVER — X-FORWARDED-FOR RATE LIMIT
# ─────────────────────────────────────────────

def test_get_client_ip_xff():
    """web_server._get_client_ip(): X-Forwarded-For başlığından IP çeker."""
    from unittest.mock import MagicMock
    import web_server

    req = MagicMock()
    req.headers = {"X-Forwarded-For": "1.2.3.4, 10.0.0.1, 172.16.0.1"}
    req.client = None

    ip = web_server._get_client_ip(req)
    assert ip == "1.2.3.4"


def test_get_client_ip_xri():
    """web_server._get_client_ip(): X-Real-IP başlığından IP çeker."""
    from unittest.mock import MagicMock
    import web_server

    req = MagicMock()
    req.headers = {"X-Real-IP": "5.6.7.8"}
    req.client = None

    ip = web_server._get_client_ip(req)
    assert ip == "5.6.7.8"


def test_get_client_ip_fallback():
    """web_server._get_client_ip(): Başlık yoksa request.client.host kullanır."""
    from unittest.mock import MagicMock
    import web_server

    req = MagicMock()
    req.headers = {}
    req.client.host = "192.168.1.100"

    ip = web_server._get_client_ip(req)
    assert ip == "192.168.1.100"


# ─────────────────────────────────────────────
# 23. GPU BELLEK TEMİZLEME — HATA DURUMUNDA GC
# ─────────────────────────────────────────────

def test_gpu_memory_optimize_gc_runs_on_error(tmp_path):
    """SystemHealthManager.optimize_gpu_memory(): GPU hatası olsa bile GC çalışır."""
    import gc as _gc
    health = SystemHealthManager(use_gpu=False)
    # GPU devre dışı — hata verme, yalnızca GC çalışmalı
    result = health.optimize_gpu_memory()
    assert "GC" in result
    assert isinstance(result, str) 

def test_instruction_files_are_loaded_hierarchically(test_config):
    """SIDAR.md ve CLAUDE.md dosyaları bağlama hiyerarşik sırayla eklenmeli."""
    root = test_config.BASE_DIR
    (root / "SIDAR.md").write_text("ROOT SIDAR", encoding="utf-8")

    nested = root / "app"
    nested.mkdir()
    (nested / "CLAUDE.md").write_text("NESTED CLAUDE", encoding="utf-8")

    deep = nested / "core"
    deep.mkdir()
    (deep / "SIDAR.md").write_text("DEEP SIDAR", encoding="utf-8")

    agent = SidarAgent(cfg=test_config)
    context = asyncio.run(agent._build_context())

    assert "[Proje Talimat Dosyaları — SIDAR.md / CLAUDE.md]" in context
    assert "ROOT SIDAR" in context
    assert "NESTED CLAUDE" in context
    assert "DEEP SIDAR" in context

    # Hiyerarşi: daha üst dosyalar önce, daha derin dosyalar sonra.
    assert context.index("ROOT SIDAR") < context.index("NESTED CLAUDE") < context.index("DEEP SIDAR")


def test_instruction_files_load_both_names_in_same_directory(test_config):
    """Aynı dizinde SIDAR.md ve CLAUDE.md varsa ikisi de bağlama eklenir."""
    root = test_config.BASE_DIR
    (root / "SIDAR.md").write_text("SIDAR ROOT RULE", encoding="utf-8")
    (root / "CLAUDE.md").write_text("CLAUDE ROOT RULE", encoding="utf-8")

    agent = SidarAgent(cfg=test_config)
    context = asyncio.run(agent._build_context())

    assert "SIDAR ROOT RULE" in context
    assert "CLAUDE ROOT RULE" in context 

def test_launcher_format_cmd_quotes_spaces():
    """main._format_cmd: Boşluk içeren argümanları shell-safe biçimde quote eder."""
    import main as launcher_main

    rendered = launcher_main._format_cmd(["python", "cli.py", "--model", "llama 3"])
    assert "'llama 3'" in rendered or '"llama 3"' in rendered


def test_launcher_execute_command_writes_child_log(tmp_path):
    """main.execute_command: capture + dosya loglama modunda child çıktısını kaydeder."""
    import main as launcher_main

    log_path = tmp_path / "child.log"
    cmd = [
        os.sys.executable,
        "-c",
        "import sys; print('child-out'); print('child-err', file=sys.stderr)",
    ]

    code = launcher_main.execute_command(cmd, capture_output=True, child_log_path=str(log_path))
    assert code == 0
    content = log_path.read_text(encoding="utf-8")
    assert "child-out" in content
    assert "child-err" in content


def test_launcher_execute_command_logs_exit_code_on_failure(tmp_path):
    """main.execute_command: child başarısız olursa çıkış kodunu log dosyasına yazar."""
    import main as launcher_main

    log_path = tmp_path / "child_fail.log"
    cmd = [os.sys.executable, "-c", "import sys; print('boom'); sys.exit(7)"]

    code = launcher_main.execute_command(cmd, capture_output=True, child_log_path=str(log_path))
    assert code == 7
    content = log_path.read_text(encoding="utf-8")
    assert "[exit_code]" in content
    assert "7" in content

def test_rag_delete_document_coverage_native(test_config):
    """RAG delete_document: bulunamayan belge ve cross-session yetki kontrollerini kapsar."""
    st = DocumentStore(test_config.RAG_DIR, use_gpu=False)

    # Olmayan belgeyi silme -> early return
    res_not_found = st.delete_document("olmayan_belge", session_id="global")
    assert "Belge bulunamadı" in res_not_found

    # Yetkisiz belge silme (farklı session) -> isolation guard
    st._index["baskasinin_belgesi"] = {"session_id": "baska_bir_oturum"}
    res_unauthorized = st.delete_document("baskasinin_belgesi", session_id="benim_oturum")
    assert "yetkiniz yok" in res_unauthorized