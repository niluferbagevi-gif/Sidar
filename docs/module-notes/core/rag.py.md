# 3.19 `core/rag/` — RAG Motoru (package facade, 19 modül + `backends/`, toplam 4.528 satır)

## Güncel kaynak yerleşimi

`core.rag` artık tek dosyalık `core/rag.py` modülü değil, geriye dönük uyumlu bir
package facade'dır (`from core.rag import DocumentStore` gibi mevcut importlar
korunur). Ana `DocumentStore` gövdesi hâlâ `core/rag/__init__.py` içinde (1.581
satır) yaşar; RRF/BM25/vektör arama motoru soyutlaması, GraphRAG ve destek
fonksiyonları ise ayrı modüllere ayrıştırılmıştır:

- `core/rag/__init__.py`: `DocumentStore` public facade ve ana orkestrasyon.
- `core/rag/facade.py`, `query.py`, `strategies.py`: sorgu planlama ve arama modu seçimi.
- `core/rag/backends/chroma.py`, `backends/bm25.py`, `backends/keyword.py`, `backends/pgvector.py`: motor bazlı arama backend'leri.
- `core/rag/chunking.py`: `RecursiveCharacterTextSplitter` benzeri chunking motoru.
- `core/rag/embeddings_wrapper.py`: GPU/FP16 embedding fonksiyonu ve offline HF runtime ayarları.
- `core/rag/graph.py`, `graph_formatting.py`, `entity_graph_store.py`, `entity_extraction.py`, `llm_entity_extraction.py`, `projection.py`: GraphRAG (modül bağımlılık grafiği + entity graph) katmanı.
- `core/rag/document_store.py`, `session_documents.py`, `metadata.py`, `formatting.py`, `readiness.py`, `entity_helpers.py`, `pgvector_helpers.py`: belge yaşam döngüsü, oturum izolasyonu ve destek yardımcıları.

`docs/REFACTOR_PLAN.md` bu paketin `__init__.py` içindeki kalan gerçek
implementasyonu daha küçük servis modüllerine (`store.py`, `graph_service.py`,
`index_service.py`) taşıma planını takip eder.

## Rapor İçeriği (Taşınan Bölüm — davranış hâlâ geçerli, dosya adları güncellendi)

**Amaç:** ChromaDB (vektör) + BM25 + Keyword hibrit belge deposu. v3.0 ile birlikte **RRF birleştirme**, **oturum izolasyonu** ve disk tabanlı BM25 altyapısı birlikte çalışır.

**Arama Modları (v3.0):**

| Mod | Motor | Açıklama |
|-----|-------|----------|
| `auto` | **RRF (ChromaDB + BM25)** → ChromaDB → BM25 → Keyword | Her iki motor hazırsa `_rrf_search` ile birleştirme (k=60) |
| `vector` | ChromaDB (cosine similarity + `session_id` where filtresi) | Anlamsal arama |
| `bm25` | SQLite FTS5 (`bm25_fts.db`) + `bm25()` skoru | Disk tabanlı tam metin arama; `tokenize='unicode61 remove_diacritics 1'` |
| `keyword` | Anahtar kelime eşleşmesi (`session_id` kontrolü) | Başlık ×5, etiket ×3, içerik ×1 ağırlıkla skor |

**RRF Algoritması (`_rrf_search`):**
```python
# Her iki motordan sonuç alınır; rank tabanlı birleştirme
rrf_score(doc) = Σ  1 / (k + rank_i)   (k=60, TREC'19 standardı)
```
ChromaDB ve BM25 sonuçları `_fetch_chroma()` / `_fetch_bm25()` ayrı metodlarıyla alınır; skorlar birleştirilerek `top_k` sonuç döndürülür.

**Oturum İzolasyonu (`session_id`):**
- `add_document()`: her belgeye `session_id` metadata alanı eklenir
- `_fetch_chroma()`: `where={"session_id": session_id}` ChromaDB filtresi
- `_fetch_bm25()`: SQL düzeyinde `session_id = ?` filtresiyle FTS5 araması yapılır
- `_keyword_search()`: `meta.get("session_id")` kontrolü
- `delete_document()`: farklı oturumun belgesini silmeye karşı yetki kontrolü
- `get_index_info()`: `session_id=None` → tüm belgeler; `session_id=<id>` → oturuma özgü

**Chunking Motoru:**
`_recursive_chunk_text()` LangChain'in `RecursiveCharacterTextSplitter` mantığını simüle eder. Öncelik sırası: `\nclass ` → `\ndef ` → `\n\n` → `\n` → ` ` → karakter. Overlap mekanizması bağlam sürekliliğini korur.

**Embedding Runtime Notları:**
- `_build_embedding_function()` — `USE_GPU=true` ise `sentence-transformers/all-MiniLM-L6-v2` modeli CUDA üzerinde çalışır; `GPU_MIXED_PRECISION=true` ise FP16 ile VRAM tasarrufu sağlanır.
- `_apply_hf_runtime_env()` — `HF_HUB_OFFLINE=true` iken `HF_HUB_OFFLINE=1` ve `TRANSFORMERS_OFFLINE=1` ortam değişkenleri zorlanarak çevrimdışı kurumsal ağlarda stabil çalışma sağlanır.

**BM25 Disk Motoru (FTS5):**
- `_init_fts()` ile `bm25_fts.db` üzerinde `bm25_index` sanal tablosu oluşturulur.
- Belge ekleme/silme akışında `_update_bm25_cache_on_add()` ve `_update_bm25_cache_on_delete()` ile FTS indeks güncel tutulur.
- Sonuç gösteriminde `_extract_snippet()` kullanılarak sorgu anahtar kelimesi etrafından kırpılmış bağlamsal metin döndürülür.

**Belge Yönetimi:**
- `add_document(session_id)`: dosya sistemi + index.json + ChromaDB chunked upsert (thread-safe `_write_lock`) + FTS5 güncelleme
- `add_document_from_url(session_id)`: httpx asenkron HTTP çekme + HTML temizleme + ekleme
- `add_document_from_file(session_id)`: uzantı whitelist kontrolü (.py, .md, .json, .yaml, vb.)
- `delete_document(session_id)`: izolasyon yetki kontrolü sonrası dosya + ChromaDB + FTS5 kayıt silme

---
