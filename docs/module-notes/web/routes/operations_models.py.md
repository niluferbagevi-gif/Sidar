# `web/routes/operations_models.py` — Operations/Poyraz/Coverage İstek Modelleri

- **Kaynak dosya:** `web/routes/operations_models.py`
- **Not dosyası:** `docs/module-notes/web/routes/operations_models.py.md`

**Amaç:** `web/routes/operations.py` ve `web/routes/coverage_ops.py`'nin
paylaştığı Pydantic istek modellerini barındırır (operasyon checklist'i,
içerik varlığı, kampanya, Poyraz araç çalıştırma, coverage QA).

**Özellikler:**
- `OperationChecklistCreateRequest`, `ContentAssetCreateRequest`,
  `CampaignCreateRequest`, `PoyrazToolRunRequest`, `LandingPageDraftRequest`,
  `CampaignCopyGenerateRequest`, `ServiceOperationsPlanRequest` —
  operasyon/pazarlama bridge payload'ları.
- `CoverageAnalyzeRequest`, `CoverageGenerateRequest`, `CoverageBatchRequest`
  — test coverage QA route'larının payload'ları.
