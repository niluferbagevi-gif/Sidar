# `web/routes/rag.py` — RAG Doküman Rotaları

- **Kaynak dosya:** `web/routes/rag.py`
- **Not dosyası:** `docs/module-notes/web/routes/rag.py.md`

**Amaç:** RAG doküman deposu için CRUD ve arama uç noktalarını kaydeder
(dosya/URL ekleme, listeleme, silme, yükleme, arama); arama sorgu uzunluğunu
`_MAX_RAG_SEARCH_QUERY_CHARS` ile sınırlar.

**Özellikler:**
- `build_rag_router(...)` — `GET /rag/docs`, `POST /rag/add-file`,
  `POST /rag/add-url`, `DELETE /rag/docs/{doc_id}`, `POST /api/rag/upload`,
  `GET /rag/search` rotalarını kaydeder.
