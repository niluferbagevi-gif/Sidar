"""
Kritik yol performans baseline testleri (pytest-benchmark).

Bu testler, sistemin temel operasyonlarının performans regresyonlarını
tespit etmek için tasarlanmıştır. `pytest-benchmark` eklentisi gerektirir.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Modül stub'ları (native bağımlılıklar olmadan çalışabilmek için) ─────────


def _ensure_stubs() -> None:
    """Benchmark testlerin çalışması için minimum stub'ları enjekte eder."""
    if "config" not in sys.modules:
        cfg_mod = types.ModuleType("config")

        class _Config:
            AI_PROVIDER = "ollama"
            OLLAMA_MODEL = "qwen2.5-coder:7b"
            BASE_DIR = "/tmp/sidar_bench"
            USE_GPU = False
            GPU_DEVICE = 0
            RAG_TOP_K = 3
            RAG_CHUNK_SIZE = 500
            RAG_CHUNK_OVERLAP = 100
            ACCESS_LEVEL = "full"
            WEB_HOST = "0.0.0.0"
            WEB_PORT = 7860

            @staticmethod
            def initialize_directories() -> bool:
                return True

        cfg_mod.Config = _Config
        cfg_mod.get_bool_env = lambda _k, default=False: default
        sys.modules["config"] = cfg_mod


_ensure_stubs()


# ═══════════════════════════════════════════════════════════════════════════════
# SecurityManager benchmark testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestSecurityManagerBenchmark:
    """managers.security.SecurityManager için performans baseline testleri."""

    @pytest.fixture(autouse=True)
    def _setup_security(self):
        from managers.security import SecurityManager

        self.sm = SecurityManager(access_level="full")

    def test_is_safe_path_allowed(self, benchmark):
        """Güvenli yol kontrolü — izin verilen yol."""
        benchmark(self.sm.is_safe_path, "/tmp/safe_file.txt")

    def test_is_safe_path_blocked(self, benchmark):
        """Güvenli yol kontrolü — bloklanmış yol."""
        benchmark(self.sm.is_safe_path, "/etc/passwd")

    def test_can_read(self, benchmark):
        """Okuma izni kontrolü."""
        benchmark(self.sm.can_read)

    def test_can_write(self, benchmark):
        """Yazma izni kontrolü."""
        benchmark(self.sm.can_write, "/tmp/test_output.txt")

    def test_can_execute(self, benchmark):
        """Çalıştırma izni kontrolü."""
        benchmark(self.sm.can_execute)

    def test_set_level_and_restore(self, benchmark):
        """Güvenlik seviyesi değişimi + geri alma."""

        def _toggle():
            self.sm.set_level("sandbox")
            self.sm.set_level("full")

        benchmark(_toggle)


# ═══════════════════════════════════════════════════════════════════════════════
# ConversationMemory benchmark testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestConversationMemoryBenchmark:
    """core.memory.ConversationMemory için performans baseline testleri."""

    @pytest.fixture(autouse=True)
    def _setup_memory(self, tmp_path):
        # core.db bağımlılığını stub'la
        if "core.db" not in sys.modules:
            db_stub = types.ModuleType("core.db")
            db_stub.Database = MagicMock()
            sys.modules["core.db"] = db_stub

        from core.memory import ConversationMemory

        self.Memory = ConversationMemory
        self.tmp_path = tmp_path

    def test_get_messages_for_llm_empty(self, benchmark):
        """Boş geçmiş üzerinde mesaj listesi oluşturma."""
        mem = self.Memory.__new__(self.Memory)
        mem._messages: list = []
        mem._system_prompt = ""
        benchmark(mem.get_messages_for_llm)

    def test_get_messages_for_llm_100_items(self, benchmark):
        """100 mesajlık geçmiş üzerinde mesaj listesi oluşturma."""
        mem = self.Memory.__new__(self.Memory)
        mem._messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"Mesaj {i}"}
            for i in range(100)
        ]
        mem._system_prompt = "Sen bir AI asistanısın."
        benchmark(mem.get_messages_for_llm)


# ═══════════════════════════════════════════════════════════════════════════════
# DocumentGraph (RAG alt bileşeni) benchmark testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestDocumentGraphBenchmark:
    """core.rag.DocumentGraph için performans baseline testleri."""

    @pytest.fixture(autouse=True)
    def _setup_graph(self, tmp_path):
        for dep in (
            "chromadb",
            "chromadb.utils",
            "chromadb.utils.embedding_functions",
            "sentence_transformers",
            "rank_bm25",
            "torch",
        ):
            if dep not in sys.modules:
                sys.modules[dep] = types.ModuleType(dep)

        from core.rag import DocumentGraph

        self.graph = DocumentGraph(root_dir=tmp_path)

    def test_add_node(self, benchmark):
        """Graf'a düğüm ekleme."""
        counter = {"n": 0}

        def _add():
            counter["n"] += 1
            self.graph.add_node(f"node_{counter['n']}", kind="file")

        benchmark(_add)

    def test_add_edge(self, benchmark):
        """Graf'a kenar ekleme."""
        self.graph.add_node("src", kind="file")
        self.graph.add_node("dst", kind="file")
        benchmark(self.graph.add_edge, "src", "dst", kind="depends_on")

    def test_clear(self, benchmark):
        """Graf temizleme."""
        for i in range(50):
            self.graph.add_node(f"node_{i}", kind="file")
        benchmark(self.graph.clear)


# ═══════════════════════════════════════════════════════════════════════════════
# BM25 rank-bm25 vektör araması benchmark testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestBM25Benchmark:
    """rank_bm25 kütüphanesi için performans baseline testleri."""

    @pytest.fixture(autouse=True)
    def _setup_bm25(self):
        try:
            from rank_bm25 import BM25Okapi

            corpus = [
                ["python", "ile", "yazılım", "geliştirme"],
                ["makine", "öğrenimi", "ve", "derin", "öğrenme"],
                ["sidar", "ajan", "sistemi", "mimarisi"],
                ["test", "otomasyonu", "ve", "kalite", "güvencesi"],
                ["fastapi", "web", "sunucu", "rest", "api"],
            ] * 20  # 100 döküman
            self.bm25 = BM25Okapi(corpus)
            self.available = True
        except ImportError:
            self.available = False

    def test_bm25_query(self, benchmark):
        """BM25 sorgusu skoru hesaplama."""
        if not self.available:
            pytest.skip("rank_bm25 kurulu değil")

        query = ["sidar", "ajan"]
        benchmark(self.bm25.get_scores, query)

    def test_bm25_top_n(self, benchmark):
        """BM25 üst-N döküman getirme."""
        if not self.available:
            pytest.skip("rank_bm25 kurulu değil")

        query = ["python", "geliştirme"]
        benchmark(self.bm25.get_top_n, query, list(range(100)), n=5)
