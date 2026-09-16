# `core/config_rag_store.py` — RAG Doküman Deposu Ayarları

- **Kaynak dosya:** `core/config_rag_store.py`
- **Not dosyası:** `docs/module-notes/core/config_rag_store.py.md`

**Amaç:** RAG bileşenlerinin kullandığı doküman-deposu ve pgvector backend
ayarlarını `RagStoreSettings` frozen dataclass'ı olarak yükler; chunk/top-k
varsayılanları için `config_rag_defaults.py`'ye dayanır.

**Özellikler:**
- `RagStoreSettings` — `web_fetch_max_chars`, `web_scrape_max_chars`,
  `rag_top_k`, `rag_chunk_size`, `rag_chunk_overlap`, `rag_file_threshold`,
  `rag_vector_backend`, `pgvector_table`, `pgvector_embedding_dim`,
  `pgvector_embedding_model`.
