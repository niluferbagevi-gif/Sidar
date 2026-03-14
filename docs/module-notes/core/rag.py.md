# 3.10 `core/rag.py` — RAG Motoru (783 satır)

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** ChromaDB (vektör) + BM25 + Keyword hibrit belge deposu. v3.0 ile birlikte **RRF birleştirme**, **oturum izolasyonu** ve disk tabanlı BM25 altyapısı birlikte çalışır.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l core/rag.py` çıktısına göre **783** olarak ölçülmüştür.

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
