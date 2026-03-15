"""
Sidar Project - Belge Deposu ve Arama (RAG)
ChromaDB tabanlı Vektör Arama + BM25 Hibrit Sistemi.
Sürüm: 2.7.0 (GPU Hızlandırmalı Embedding + Motor Bağımsız Sorgu)

Özellikler:
1. Vektör Arama (ChromaDB): Anlamsal yakınlık (Semantic Search) - Chunking destekli
   → USE_GPU=true ise sentence-transformers CUDA üzerinde çalışır
   → GPU_MIXED_PRECISION=true ise FP16 ile bellek tasarrufu sağlanır
2. BM25 (SQLite FTS5): Disk tabanlı kelime sıklığı ve nadirlik tabanlı arama
3. Fallback: Basit anahtar kelime eşleşmesi
"""

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import asyncio
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import Config

logger = logging.getLogger(__name__)


def _build_embedding_function(use_gpu: bool = False,
                               gpu_device: int = 0,
                               mixed_precision: bool = False):
    """
    ChromaDB için GPU-farkında embedding fonksiyonu oluşturur.

    use_gpu=True  →  sentence-transformers all-MiniLM-L6-v2  CUDA üzerinde çalışır.
    use_gpu=False →  ChromaDB varsayılan CPU embedding'i kullanılır (None).

    Döndürülen nesne None ise ChromaDB kendi varsayılanını kullanır.
    """
    if not use_gpu:
        return None  # ChromaDB varsayılan (CPU) embedding fonksiyonu

    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        import torch

        device = f"cuda:{gpu_device}" if torch.cuda.is_available() else "cpu"

        if mixed_precision and device.startswith("cuda"):
            # FP16 desteği — torch.amp ile embedding modeli daha az VRAM kullanır
            import torch.amp  # noqa: F401  (import kontrolü)

        ef = SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2",
            device=device,
        )

        # Mixed precision: sentence-transformers encode sırasında half() uygula
        if mixed_precision and device.startswith("cuda"):
            _orig_call = ef.__call__

            def _fp16_call(input):
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    return _orig_call(input)

            ef.__call__ = _fp16_call

        logger.info(
            "🚀 ChromaDB GPU Embedding: device=%s  mixed_precision=%s",
            device, mixed_precision,
        )
        return ef

    except Exception as exc:
        logger.warning(
            "⚠️  GPU embedding başlatılamadı, CPU'ya dönülüyor: %s", exc
        )
        return None


class DocumentStore:
    """
    Yerel belge deposu — ChromaDB ile semantik arama.

    Güncellemeler (v2.6.0):
    - Recursive Character Chunking ile büyük belgeleri mantıksal parçalara ayırır.
    - USE_GPU=true ise GPU hızlandırmalı embedding fonksiyonu kullanılır.
    - GPU_MIXED_PRECISION=true ise FP16 ile VRAM tasarrufu sağlanır.
    """

    def __init__(
        self,
        store_dir: Path,
        top_k: Optional[int] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        use_gpu: bool = False,
        gpu_device: int = 0,
        mixed_precision: bool = False,
        cfg: Optional[Config] = None,
    ) -> None:
        self.cfg = cfg or Config()
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.index_file    = self.store_dir / "index.json"
        self.default_top_k = top_k if top_k is not None else getattr(self.cfg, "RAG_TOP_K", 3)
        self._chunk_size = chunk_size if chunk_size is not None else getattr(self.cfg, "RAG_CHUNK_SIZE", 1000)
        self._chunk_overlap = (
            chunk_overlap
            if chunk_overlap is not None
            else getattr(self.cfg, "RAG_CHUNK_OVERLAP", 200)
        )

        # GPU embedding ayarları
        self._use_gpu          = use_gpu
        self._gpu_device       = gpu_device
        self._mixed_precision  = mixed_precision

        # ChromaDB delete+upsert atomikliği için lock
        self._write_lock = threading.Lock()

        # Meta verileri yükle
        self._index: Dict[str, Dict] = self._load_index()

        # Arama motorlarını başlat
        self._chroma_available = self._check_import("chromadb")

        self.chroma_client = None
        self.collection    = None

        if self._chroma_available:
            self._init_chroma()

        # BM25 (SQLite FTS5) Başlatma
        self._bm25_available = True
        self._init_fts()

    def _apply_hf_runtime_env(self) -> None:
        """HF model yükleme davranışını Config üzerinden ortama uygula."""
        hf_token = getattr(self.cfg, "HF_TOKEN", "")
        if hf_token:
            os.environ["HF_TOKEN"] = hf_token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

        if getattr(self.cfg, "HF_HUB_OFFLINE", False):
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

    # ─────────────────────────────────────────────
    #  BAŞLANGIÇ & AYARLAR
    # ─────────────────────────────────────────────

    def _check_import(self, module_name: str) -> bool:
        import importlib
        try:
            importlib.import_module(module_name)
            return True
        except ImportError:
            return False

    def _init_chroma(self) -> None:
        """ChromaDB istemcisini ve koleksiyonunu başlat (GPU embedding destekli)."""
        try:
            import chromadb

            # Embedding modeli başlatılmadan önce HF runtime değişkenlerini uygula.
            self._apply_hf_runtime_env()

            # Veritabanını data/rag/chroma_db içinde tut
            db_path = self.store_dir / "chroma_db"
            self.chroma_client = chromadb.PersistentClient(path=str(db_path))

            # GPU-farkında embedding fonksiyonu
            embedding_fn = _build_embedding_function(
                use_gpu=self._use_gpu,
                gpu_device=self._gpu_device,
                mixed_precision=self._mixed_precision,
            )

            create_kwargs: Dict = {"metadata": {"hnsw:space": "cosine"}}
            if embedding_fn is not None:
                create_kwargs["embedding_function"] = embedding_fn

            self.collection = self.chroma_client.get_or_create_collection(
                name="sidar_knowledge_base",
                **create_kwargs,
            )

            device_info = (
                f"cuda:{self._gpu_device}" if self._use_gpu and embedding_fn else "cpu"
            )
            logger.info(
                "ChromaDB vektör veritabanı başlatıldı. Embedding device: %s",
                device_info,
            )
        except Exception as exc:
            logger.error("ChromaDB başlatma hatası: %s", exc)
            self._chroma_available = False

    def _init_fts(self) -> None:
        """SQLite FTS5 sanal tablosunu başlatır (Disk tabanlı BM25)."""
        import sqlite3
        try:
            db_path = self.store_dir / "bm25_fts.db"
            self.fts_conn = sqlite3.connect(db_path, check_same_thread=False)
            self.fts_conn.row_factory = sqlite3.Row
            with self._write_lock:
                # FTS5 eklentisi ile sanal tablo oluştur (Türkçe karakter destekli)
                self.fts_conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS bm25_index USING fts5(
                        doc_id UNINDEXED,
                        session_id UNINDEXED,
                        content,
                        tokenize='unicode61 remove_diacritics 1'
                    );
                """)
                # Eski verileri migrate et (FTS5 boşsa ve önceden eklenmiş belgeler varsa)
                cursor = self.fts_conn.execute("SELECT count(*) as c FROM bm25_index")
                if cursor.fetchone()["c"] == 0 and self._index:
                    logger.info("Mevcut belgeler SQLite FTS5 disk motoruna aktarılıyor...")
                    for doc_id, meta in self._index.items():
                        doc_file = self.store_dir / f"{doc_id}.txt"
                        try:
                            content = doc_file.read_text(encoding="utf-8")
                            session_id = meta.get("session_id", "global")
                            self.fts_conn.execute(
                                "INSERT INTO bm25_index (doc_id, session_id, content) VALUES (?, ?, ?)",
                                (doc_id, session_id, content)
                            )
                        except Exception:
                            pass
                self.fts_conn.commit()
            logger.info("SQLite FTS5 (BM25) veritabanı disk üzerinde başarıyla başlatıldı.")
        except Exception as exc:
            logger.error("FTS5 başlatma hatası: %s", exc)
            self._bm25_available = False

    def _load_index(self) -> Dict[str, Dict]:
        if self.index_file.exists():
            try:
                return json.loads(self.index_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("RAG index okunamadı: %s", exc)
        return {}

    def _save_index(self) -> None:
        self.index_file.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ─────────────────────────────────────────────
    #  BELGE YÖNETİMİ & CHUNKING
    # ─────────────────────────────────────────────

    def _recursive_chunk_text(self, text: str, size: int, overlap: int) -> List[str]:
        """
        Metni kod yapısına uygun ayırıcılarla (separators) mantıksal parçalara böler.
        LangChain'in RecursiveCharacterTextSplitter mantığını simüle eder.
        """
        if not text:
            return []

        # Öncelik sırasına göre ayırıcılar (Python ve genel metin için optimize)
        separators = ["\nclass ", "\ndef ", "\n\n", "\n", " ", ""]

        def _split(text_part: str, sep_idx: int) -> List[str]:
            """Recursive bölme fonksiyonu"""
            if len(text_part) <= size:
                return [text_part]
            
            if sep_idx >= len(separators):
                # Hiçbir ayırıcı ile bölünemiyorsa zorla böl (character limit)
                step = max(1, size - overlap)
                return [text_part[i:i + size] for i in range(0, len(text_part), step)]

            sep = separators[sep_idx]
            # Ayırıcıya göre böl (ayırıcı başta kalsın diye lookahead simülasyonu yapılabilir ama basit split yeterli)
            # Not: Python split ayırıcıyı yutar, tekrar eklemek gerekebilir.
            # Burada basit split kullanıyoruz, bağlam kaybı olmaması için overlap önemli.
            if sep == "":
                parts = list(text_part) # Karakter karakter
            else:
                parts = text_part.split(sep)
                # Ayırıcıyı parçalara geri ekleyelim (özellikle class/def için önemli)
                parts = [parts[0]] + [sep + p for p in parts[1:]] if parts else []

            new_chunks = []
            current_chunk = ""

            for part in parts:
                # Eğer parça tek başına bile çok büyükse, bir sonraki ayırıcı ile böl
                if len(part) > size:
                    if current_chunk:
                        new_chunks.append(current_chunk)
                        current_chunk = ""
                    sub_chunks = _split(part, sep_idx + 1)
                    new_chunks.extend(sub_chunks)
                    continue

                # Mevcut parça ile limiti aşıyor mu?
                if len(current_chunk) + len(part) > size:
                    new_chunks.append(current_chunk)
                    # Overlap mekanizması: Bir önceki chunk'ın sonundan biraz al
                    overlap_len = min(len(current_chunk), overlap)
                    current_chunk = current_chunk[-overlap_len:] + part
                else:
                    current_chunk += part
            
            if current_chunk:
                new_chunks.append(current_chunk)
            
            return new_chunks

        return _split(text, 0)

    def _chunk_text(
        self,
        text: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> List[str]:
        """Chunking ayarlarını Config'den çözerek recursive parçalama yap."""
        c_size = chunk_size or getattr(self.cfg, "RAG_CHUNK_SIZE", self._chunk_size)
        c_overlap = chunk_overlap or getattr(self.cfg, "RAG_CHUNK_OVERLAP", self._chunk_overlap)
        return self._recursive_chunk_text(text, c_size, c_overlap)

    def _add_document_sync(
        self,
        title: str,
        content: str,
        source: str = "",
        tags: Optional[List[str]] = None,
        session_id: str = "global"
    ) -> str:
        doc_id = uuid.uuid4().hex[:12]
        parent_id = hashlib.md5(f"{title}{source}".encode()).hexdigest()[:12]
        tags = tags or []

        chunks = self._chunk_text(content)
        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "source": source,
                "title": title,
                "tags": ",".join(tags),
                "parent_id": parent_id,
                "chunk_index": i,
                "session_id": session_id,
            }
            for i in range(len(chunks))
        ]

        with self._write_lock:
            doc_file = self.store_dir / f"{doc_id}.txt"
            doc_file.write_text(content, encoding="utf-8")

            self._index[doc_id] = {
                "title": title,
                "source": source,
                "tags": tags,
                "size": len(content),
                "preview": content[:300],
                "parent_id": parent_id,
                "session_id": session_id,
            }
            self._save_index()
            self._update_bm25_cache_on_add(doc_id, content)

            if self._chroma_available and self.collection:
                try:
                    self.collection.delete(where={"parent_id": parent_id})
                    if chunks:
                        self.collection.upsert(
                            ids=ids,
                            documents=chunks,
                            metadatas=metadatas,
                        )
                    if chunks:
                        logger.info(
                            "ChromaDB: %s belgesi (%s) %d parçaya ayrılarak eklendi. (Oturum: %s)",
                            doc_id, parent_id, len(chunks), session_id
                        )
                except Exception as exc:
                    logger.error("ChromaDB belge ekleme hatası: %s", exc)

        logger.info("RAG belge eklendi: [%s] %s (%d karakter) [Oturum: %s]", doc_id, title, len(content), session_id)
        return doc_id

    async def add_document(
        self,
        title: str,
        content: str,
        source: str = "",
        tags: Optional[List[str]] = None,
        session_id: str = "global",
    ) -> str:
        return await asyncio.to_thread(
            self._add_document_sync,
            title,
            content,
            source,
            tags,
            session_id,
        )

    async def add_document_from_url(self, url: str, title: str = "", tags: Optional[List[str]] = None, session_id: str = "global") -> Tuple[bool, str]:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = await client.get(url)
            resp.raise_for_status()
            content = self._clean_html(resp.text)

            if not title:
                m = re.search(r"<title[^>]*>([^<]+)</title>", resp.text, re.IGNORECASE)
                title = m.group(1).strip() if m else url.split("/")[-1] or url

            doc_id = await self.add_document(title, content, url, tags, session_id)
            return True, f"✓ Belge eklendi: [{doc_id}] {title} ({len(content)} karakter)"
        except Exception as exc:
            logger.error("URL belge çekme hatası: %s", exc)
            return False, f"[HATA] URL belge eklenemedi: {exc}"

    def add_document_from_file(self, path: str, title: str = "", tags: Optional[List[str]] = None, session_id: str = "global") -> Tuple[bool, str]:
        _TEXT_EXTS = {".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".html", ".css", ".js", ".ts", ".sh", ".sql", ".csv", ".xml", ".rst", ".env", ".example", ".gitignore", ".dockerignore", ""}
        try:
            file = Path(path).resolve()
            if not file.exists(): return False, f"✗ Dosya bulunamadı: {path}"
            if not file.is_file(): return False, f"✗ Belirtilen yol bir dosya değil: {path}"
            if file.suffix.lower() not in _TEXT_EXTS: return False, f"✗ Desteklenmeyen dosya türü: {file.suffix}"

            content = file.read_text(encoding="utf-8", errors="replace")
            if not content.strip(): return False, f"✗ Dosya boş: {path}"
            if not title: title = file.name

            source = f"file://{file}"
            doc_id = self._add_document_sync(title, content, source=source, tags=tags or [], session_id=session_id)
            return True, f"✓ Dosya RAG deposuna eklendi: [{doc_id}] {title} ({len(content):,} karakter)"
        except Exception as exc:
            logger.error("Dosya belge ekleme hatası (%s): %s", path, exc)
            return False, f"[HATA] Dosya eklenemedi: {exc}"

    def get_index_info(self, session_id: Optional[str] = None) -> List[Dict]:
        return [
            {
                "id":      doc_id,
                "title":   meta.get("title", "?"),
                "source":  meta.get("source", ""),
                "size":    meta.get("size", 0),
                "preview": meta.get("preview", "")[:120],
                "tags":    meta.get("tags", []),
                "session_id": meta.get("session_id", "global"),
            }
            for doc_id, meta in self._index.items()
            if session_id is None or meta.get("session_id", "global") == session_id
        ]

    @property
    def doc_count(self) -> int:
        """Dizindeki belge sayısını döndürür."""
        return len(self._index)

    def delete_document(self, doc_id: str, session_id: str = "global") -> str:
        """Belgeyi tüm depolardan sil (İzolasyon Korumalı)."""
        if doc_id not in self._index:
            return f"✗ Belge bulunamadı: {doc_id}"

        # İzolasyon yetki kontrolü
        meta = self._index[doc_id]
        if meta.get("session_id", "global") != session_id and session_id != "global":
            return f"✗ HATA: Bu belgeye erişim yetkiniz yok (Farklı bir sohbete ait)."

        with self._write_lock:
            if doc_id not in self._index:
                return f"✗ Belge zaten silinmiş: {doc_id}"

            title = self._index[doc_id].get("title", doc_id)

            # 1. Dosya sil
            doc_file = self.store_dir / f"{doc_id}.txt"
            if doc_file.exists():
                doc_file.unlink()

            # 2. ChromaDB'den sil
            if self._chroma_available and self.collection:
                try:
                    parent_id = self._index[doc_id].get("parent_id", doc_id)
                    self.collection.delete(where={"parent_id": parent_id})
                except Exception as exc:
                    logger.error("ChromaDB silme hatası: %s", exc)

            # 3. Index'ten ve BM25'ten sil
            del self._index[doc_id]
            self._save_index()
            self._update_bm25_cache_on_delete(doc_id)

        return f"✓ Belge silindi: [{doc_id}] {title}"

    def get_document(self, doc_id: str, session_id: str = "global") -> Tuple[bool, str]:
        """Belge ID ile tam içerik getir (İzolasyon Korumalı)."""
        if doc_id not in self._index:
            return False, f"✗ Belge bulunamadı: {doc_id}"

        meta = self._index[doc_id]
        if meta.get("session_id", "global") != session_id and session_id != "global":
            return False, f"✗ HATA: Bu belgeye erişim yetkiniz yok (Farklı bir sohbete ait)."

        doc_file = self.store_dir / f"{doc_id}.txt"
        if not doc_file.exists():
            return False, f"✗ Belge dosyası eksik: {doc_id}"
        content = doc_file.read_text(encoding="utf-8")
        return True, f"[{doc_id}] {meta['title']}\nKaynak: {meta.get('source', '-')}\n\n{content}"

    # ─────────────────────────────────────────────
    #  ARAMA (HİBRİT)
    # ─────────────────────────────────────────────

    def _search_sync(self, query: str, top_k: Optional[int] = None, mode: str = "auto", session_id: str = "global") -> Tuple[bool, str]:
        if top_k is None: top_k = getattr(self.cfg, "RAG_TOP_K", self.default_top_k)

        session_docs = [k for k, v in self._index.items() if v.get("session_id", "global") == session_id]
        if not session_docs:
            return False, "⚠ Bu oturum için belge deposu boş. Belge eklemek için: TOOL:docs_add:<başlık>|<url>"

        if mode == "vector":
            if self._chroma_available and self.collection: return self._chroma_search(query, top_k, session_id)
            return False, "Vektör arama kullanılamıyor — ChromaDB kurulu değil."

        if mode == "bm25":
            if self._bm25_available: return self._bm25_search(query, top_k, session_id)
            return False, "BM25 kullanılamıyor — SQLite FTS5 başlatılamadı."

        if mode == "keyword": return self._keyword_search(query, top_k, session_id)

        if self._chroma_available and self._bm25_available and self.collection:
            try: return self._rrf_search(query, top_k, session_id)
            except Exception as exc: logger.warning("RRF arama hatası (Fallback yapılıyor): %s", exc)

        if self._chroma_available and self.collection:
            try: return self._chroma_search(query, top_k, session_id)
            except Exception as exc: logger.warning("ChromaDB arama hatası (BM25'e düşülüyor): %s", exc)

        if self._bm25_available: return self._bm25_search(query, top_k, session_id)
        return self._keyword_search(query, top_k, session_id)

    async def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        mode: str = "auto",
        session_id: str = "global",
    ) -> Tuple[bool, str]:
        return await asyncio.to_thread(self._search_sync, query, top_k, mode, session_id)

    def _rrf_search(self, query: str, top_k: int, session_id: str) -> Tuple[bool, str]:
        chroma_results = self._fetch_chroma(query, top_k, session_id)
        bm25_results = self._fetch_bm25(query, top_k, session_id)

        if not chroma_results and not bm25_results: return self._keyword_search(query, top_k, session_id)

        k = 60
        rrf_scores, docs_map = {}, {}

        for rank, res in enumerate(chroma_results):
            doc_id = res["id"]
            docs_map[doc_id] = res
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        for rank, res in enumerate(bm25_results):
            doc_id = res["id"]
            if doc_id not in docs_map: docs_map[doc_id] = res
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        ranked_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        final_results = []
        for doc_id, score in ranked_docs:
            doc_info = docs_map[doc_id]
            doc_info["score"] = score
            final_results.append(doc_info)

        return self._format_results_from_struct(final_results, query, source_name="Hibrit RRF (ChromaDB + BM25)")

    def _fetch_chroma(self, query: str, top_k: int, session_id: str) -> list:
        try: collection_size = self.collection.count()
        except Exception: collection_size = top_k * 2

        n_results = min(top_k * 2, max(collection_size, 1))

        # Filtreleme ChromaDB düzeyinde Where parametresiyle yapılıyor
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where={"session_id": session_id}
        )

        if not results["ids"] or not results["ids"][0]: return []

        found_docs, seen_parents = [], set()
        for i, chunk_content in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            parent_id = meta.get("parent_id")
            if parent_id in seen_parents and len(seen_parents) >= top_k: continue
            seen_parents.add(parent_id)
            found_docs.append({
                "id": parent_id, "title": meta.get("title", "?"),
                "source": meta.get("source", ""), "snippet": chunk_content, "score": 1.0
            })
            if len(found_docs) >= top_k: break
        return found_docs

    def _chroma_search(self, query: str, top_k: int, session_id: str) -> Tuple[bool, str]:
        results = self._fetch_chroma(query, top_k, session_id)
        return self._format_results_from_struct(results, query, source_name="Vektör Arama (ChromaDB + Chunking)")

    def _update_bm25_cache_on_add(self, doc_id: str, content: str) -> None:
        """Yeni belgeyi SQLite FTS5 disk tablosuna kaydet.
        Not: Bu metod zaten _write_lock tutan bir bloktan çağrılır — içeride kilit alınmaz.
        """
        if not self._bm25_available:
            return
        session_id = self._index.get(doc_id, {}).get("session_id", "global")
        self.fts_conn.execute("DELETE FROM bm25_index WHERE doc_id = ?", (doc_id,))
        self.fts_conn.execute(
            "INSERT INTO bm25_index (doc_id, session_id, content) VALUES (?, ?, ?)",
            (doc_id, session_id, content)
        )
        self.fts_conn.commit()

    def _update_bm25_cache_on_delete(self, doc_id: str) -> None:
        """Silinen belgeyi SQLite FTS5'ten kaldır.
        Not: Bu metod zaten _write_lock tutan bir bloktan çağrılır — içeride kilit alınmaz.
        """
        if not self._bm25_available:
            return
        self.fts_conn.execute("DELETE FROM bm25_index WHERE doc_id = ?", (doc_id,))
        self.fts_conn.commit()

    def _fetch_bm25(self, query: str, top_k: int, session_id: str) -> list:
        """Diskteki FTS5 veritabanından milisaniyelik BM25 araması yap."""
        if not self._bm25_available:
            return []

        words = [w for w in query.replace('"', '').replace("'", "").split() if w.isalnum()]
        if not words:
            return []

        # Kelimelerden herhangi birini içerenleri bul (OR mantığı)
        match_query = " OR ".join(words)

        sql = """
            SELECT doc_id, bm25(bm25_index) as score
            FROM bm25_index
            WHERE bm25_index MATCH ? AND session_id = ?
            ORDER BY score
            LIMIT ?
        """

        try:
            cursor = self.fts_conn.execute(sql, (match_query, session_id, top_k))
            rows = cursor.fetchall()
        except Exception as exc:
            logger.warning("FTS5 Arama Hatası: %s", exc)
            return []

        results = []
        for row in rows:
            doc_id = row["doc_id"]
            # FTS5 bm25 fonksiyonu negatif değer döndürür (en negatif = en alakalı). Bunu pozitife çeviriyoruz.
            score = abs(row["score"])


            meta = self._index.get(doc_id, {})
            doc_file = self.store_dir / f"{doc_id}.txt"
            try:
                content = doc_file.read_text(encoding="utf-8")
            except FileNotFoundError:
                content = ""
            snippet = self._extract_snippet(content, query)
            results.append({
                "id": doc_id, "title": meta.get("title", "?"),
                "source": meta.get("source", ""), "snippet": snippet, "score": score
            })
        return results

    def _bm25_search(self, query: str, top_k: int, session_id: str) -> Tuple[bool, str]:
        results = self._fetch_bm25(query, top_k, session_id)
        return self._format_results_from_struct(results, query, source_name="BM25")

    def _keyword_search(self, query: str, top_k: int, session_id: str) -> Tuple[bool, str]:
        keywords = query.lower().split()
        scored = []

        for doc_id, meta in list(self._index.items()):
            if meta.get("session_id", "global") != session_id: continue

            doc_file = self.store_dir / f"{doc_id}.txt"
            try: text = doc_file.read_text(encoding="utf-8").lower()
            except FileNotFoundError: text = ""

            title_lower = meta["title"].lower()
            tags_lower = " ".join(meta.get("tags", [])).lower()

            score = sum(text.count(kw) + title_lower.count(kw) * 5 + tags_lower.count(kw) * 3 for kw in keywords)
            if score > 0: scored.append((doc_id, score))

        ranked = sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for doc_id, score in ranked:
            doc_file = self.store_dir / f"{doc_id}.txt"
            try: content = doc_file.read_text(encoding="utf-8")
            except FileNotFoundError: content = ""
            meta = self._index.get(doc_id, {})
            snippet = self._extract_snippet(content, query)
            results.append({
                "id": doc_id, "title": meta.get("title", "?"),
                "source": meta.get("source", ""), "snippet": snippet, "score": score
            })

        return self._format_results_from_struct(results, query, source_name="Kelime Eşleşmesi")

    def _format_results_from_struct(self, results: list, query: str, source_name: str) -> Tuple[bool, str]:
        """Ortak sonuç biçimlendirici."""
        if not results:
            return False, f"'{query}' için belge deposunda ilgili sonuç bulunamadı."

        lines = [f"[RAG Arama: {query}] (Motor: {source_name})", ""]
        for res in results:
            lines.append(f"**[{res['id']}] {res['title']}**")
            if res['source']:
                lines.append(f"  Kaynak: {res['source']}")
            
            # Snippet uzunluğunu sınırla ve satır sonlarını temizle
            snippet = res['snippet'].replace("\n", " ").strip()
            if len(snippet) > 400:
                snippet = snippet[:400] + "..."
            
            lines.append(f"  {snippet}")
            lines.append("")

        return True, "\n".join(lines)

    @staticmethod
    def _extract_snippet(content: str, query: str, window: int = 400) -> str:
        """Sorgudaki ilk anahtar kelimenin etrafındaki metni çıkar (BM25 ve Keyword için)."""
        keywords = query.lower().split()
        content_lower = content.lower()
        
        # Önce tam eşleşme ara
        for kw in keywords:
            idx = content_lower.find(kw)
            if idx != -1:
                start = max(0, idx - 100)
                end = min(len(content), idx + window)
                snippet = content[start:end].strip()
                return f"...{snippet}..." if start > 0 else snippet
        
        # Bulunamazsa baş tarafı döndür
        return content[:window] + ("..." if len(content) > window else "")

    # ─────────────────────────────────────────────
    #  LİSTELEME & STATÜ
    # ─────────────────────────────────────────────

    def list_documents(self, session_id: Optional[str] = None) -> str:
        docs = {k: v for k, v in self._index.items() if session_id is None or v.get("session_id", "global") == session_id}
        if not docs:
            return "Belge deposu boş veya bu oturum için belge bulunamadı."

        lines = [f"[Belge Deposu — {len(docs)} belge]", ""]
        for doc_id, meta in docs.items():
            tags = ", ".join(meta.get("tags", [])) or "-"
            size_kb = meta.get("size", 0) / 1024
            lines.append(f"  [{doc_id}] {meta['title']}")
            lines.append(f"    Kaynak: {meta.get('source', '-')} | Boyut: {size_kb:.1f} KB | Etiketler: {tags}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────
    #  YARDIMCILAR
    # ─────────────────────────────────────────────

    @staticmethod
    def _clean_html(html: str) -> str:
        """HTML'yi temiz metne dönüştür."""
        clean = re.sub(
            r"<(script|style)[^>]*>.*?</(script|style)>",
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        clean = clean.replace("&nbsp;", " ").replace("&quot;", '"')
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    def status(self) -> str:
        engines = []
        if self._chroma_available:
            gpu_tag = f"GPU cuda:{self._gpu_device}" if self._use_gpu else "CPU"
            engines.append(f"ChromaDB (Chunking + {gpu_tag})")
        if self._bm25_available:
            engines.append("BM25 (SQLite FTS5)")
        if not engines:
            engines.append("Anahtar Kelime")

        return f"RAG: {len(self._index)} belge | Motorlar: {', '.join(engines)}"  