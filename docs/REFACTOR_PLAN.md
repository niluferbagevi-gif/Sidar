# Büyük Production Dosyaları Refactor Planı

Bu plan, mevcut davranışı koruyarak yüksek sorumluluk yoğunluğuna sahip üretim dosyalarını
küçük, test edilebilir ve domain odaklı modüllere ayırmak için yaşayan takip dokümanıdır.
Dosya boyutu tek başına hata değildir; ancak endpoint, orchestration, storage veya tool execution
sorumlulukları aynı dosyada biriktiğinde review maliyeti ve regresyon riski artar. Bu nedenle her
adım küçük PR'lara bölünmeli, public/legacy import sözleşmeleri korunmalı ve mevcut unit/integration
testleri taşınan kodla birlikte çalışmaya devam etmelidir.

## Refactor ilkeleri

- **Davranış koruma:** Önce modül boundary'si çıkarılır, ardından fonksiyon/sınıf taşınır; route path,
  response schema, environment variable ve legacy export isimleri değişmez.
- **Küçük PR:** Her PR tek domain kümesine odaklanır; geniş dosya taşıma + davranış değişikliği aynı PR'a
  konmaz.
- **Test-first güvence:** Taşımadan önce mevcut testler hedef modüle yönlendirilir veya direkt modül testi
  eklenir; smoke/API testleri geriye dönük import yüzeyini doğrular.
- **Compatibility shim:** Büyük dosyada kalan `import`/wrapper/export geçici olabilir, fakat TODO ve takip
  satırıyla kaldırılacağı hedef faz belirtilmelidir.
- **Yan etki izolasyonu:** DB, shell, Docker, LLM, WebSocket ve dosya sistemi çağrıları domain servislerine
  ayrılırken fake/mock fixture'ları korunur.

## Öncelikli büyük dosyalar

| Dosya | Risk nedeni | Hedef modül sınırı | İlk düşük riskli adım | Test kapısı |
|---|---|---|---|---|
| `web_server.py` | Endpoint, WebSocket, middleware, auth, frontend fallback ve bootstrap tek dosyada yoğunlaşıyor. | `web/routes/ws_chat.py`, `web/routes/ws_voice.py`, `web/routes/collaboration.py`, `web/routes/webhooks.py`, `web/routes/operations.py`, `web/security.py`, `web/app_factory.py` | App factory ve GitHub webhook router çıkarımı yapıldı; sıradaki adım `/ws/chat` için router factory + legacy export shim. | `tests/unit/root/test_web_server.py`, `tests/unit/web/*`, smoke boot tests |
| `core/db.py` | Record modelleri, auth, migration, repository ve operational persistence aynı dosyada. | `core/db/auth.py`, `core/db/coverage.py`, `core/db/marketing.py`, `core/db/session.py`, ortak `core/db/models.py` | Read-only serializer/query helper'larını domain modüllerine taşıyıp `core.db` üzerinden re-export etmek. | `tests/unit/core/test_db.py`, migration integration tests |
| `core/rag/__init__.py` | Embedding, store, query, GraphRAG ve package init davranışları aynı dosyada. | `core/rag/embeddings.py`, `core/rag/store.py`, `core/rag/query.py`, `core/rag/graph.py`, `core/rag/facade.py` | Pure helper ve dataclass'ları gerçek uygulama dosyalarına taşıyıp `__init__` içinde public facade bırakmak. | `tests/unit/core/test_rag.py`, RAG integration tests |
| `managers/code_manager.py` | Shell execution, Docker sandbox, patching, LSP adapter ve güvenlik kontrolleri tek sınıfta. | `managers/code/runner.py`, `managers/code/docker.py`, `managers/code/patcher.py`, `managers/code/lsp.py`, `managers/code/security_adapter.py` | Mevcut `managers/code/*` modüllerini genişletip `CodeManager` içinde delegation kullanmak. | `tests/unit/managers/test_code_manager.py`, sandbox contract tests |
| `agent/sidar_agent.py` | Ana ajan orchestration, tool execution, self-heal, autonomy ve federation sorumlulukları birleşik. | `agent/tool_registry.py`, `agent/self_heal/executor.py`, `agent/autonomy/service.py`, `agent/federation/service.py` | Self-heal plan normalize/execute akışını servis katmanına taşıyıp `SidarAgent` facade metotlarını korumak. | `tests/unit/agent/test_sidar_agent.py`, CI remediation tests |
| `agent/roles/coverage_agent.py` | Coverage parsing, pytest output analysis, missing-test generation ve writer katmanları tek role içinde. | `agent/roles/coverage/analyzer.py`, `agent/roles/coverage/generator.py`, `agent/roles/coverage/writer.py`, `agent/roles/coverage/models.py` | Pure parsing/analyzer fonksiyonlarını yan etkisiz modüle taşıyıp role içinde orchestration bırakmak. | `tests/unit/agent/roles/test_coverage_agent.py`, coverage hotspot tests |

## Faz planı

1. **Faz 1 — Boundary ve facade:** Her hedef dosya için public API listesi çıkarılır, yeni modül oluşturulur,
   eski import yolu geçici re-export eder.
2. **Faz 2 — Pure helper taşıma:** Yan etkisiz parser/serializer/normalizer fonksiyonları taşınır; direkt
   modül testleri eklenir.
3. **Faz 3 — IO servisleri:** DB, shell, Docker, WebSocket ve LLM yan etkileri adapter/service sınıflarına
   ayrılır; fake fixture'lar bu sınıflara bağlanır.
4. **Faz 4 — Legacy shim azaltma:** Büyük dosyada kalan wrapper/export sayısı takip edilir; route/service
   sahipliği yeni modüllere geçtikçe shim kaldırılır.

## Kabul kriterleri

- Yeni modül public sözleşmesi ve import yolu testle korunur.
- Büyük dosya satır sayısı veya sorumluluk sayısı her fazda azalır; sadece satır taşıma değil domain ayrışması
  hedeflenir.
- Route path, CLI behavior, DB schema ve environment variable isimleri geriye dönük uyumlu kalır.
- Her PR açıklamasında taşınan sorumluluk, korunan legacy yüzey ve çalıştırılan test kapıları listelenir.
