# `core/config_rag_defaults.py` — RAG Varsayılanları

- **Kaynak dosya:** `core/config_rag_defaults.py`
- **Not dosyası:** `docs/module-notes/core/config_rag_defaults.py.md`

**Amaç:** RAG ve semantic cache için statik varsayılan değerleri tutar. Adı, runtime store
ayarları (`core/config_rag_store.py`) ve RAG implementasyonu (`core/rag/`) ile
karışmaması için `_defaults` ekiyle seçilmiştir.

**Özellikler:**
- `SEMANTIC_CACHE_THRESHOLD_DEFAULT`, `RAG_TOP_K_DEFAULT`, `RAG_CHUNK_SIZE_DEFAULT`,
  `RAG_CHUNK_OVERLAP_DEFAULT`, `RAG_FILE_THRESHOLD_DEFAULT`.
