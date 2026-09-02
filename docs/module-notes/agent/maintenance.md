# agent/maintenance/

- **Kaynak dizini:** `agent/maintenance/` (`__init__.py`, `nightly.py`)
- **Not dosyası:** `docs/module-notes/agent/maintenance.md`

## Amaç

`nightly.py::run_nightly_memory_maintenance(agent, *, force=False,
reason="nightly_idle", entity_memory_factory=get_entity_memory)` — `SidarAgent`
boşta kaldığında (varsayılan `NIGHTLY_MEMORY_IDLE_SECONDS=1800`) çalışan bellek
sıkıştırma/temizlik işi. `_NightlyAgentLike` (`Protocol`, yalnızca
`TYPE_CHECKING`) çağıran nesnenin gereken minimum yüzeyini (`cfg`, `docs`,
`memory`, dağıtık lease metotları, autonomy history) belgeler; gerçek tip
her zaman `SidarAgent`'tır.

Akış: `ENABLE_NIGHTLY_MEMORY_PRUNING` kapalıysa/boşta değilse erken döner;
yerel `asyncio.Lock` ile eşzamanlı çalışmayı, `_acquire_nightly_distributed_lease`
ile de çoklu worker/instance arası çakışmayı önler. Kilit altında sırasıyla:

1. `core.entity_memory.get_entity_memory` (varsayılan factory) ile süresi
   dolmuş entity kayıtlarını temizler (`entity_report`).
2. `agent.memory.run_nightly_consolidation` ile eski konuşma oturumlarını
   sıkıştırır (`NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS`/`_SESSION_MIN_MESSAGES`).
3. Etkilenen her oturum için `agent.docs.consolidate_session_documents`
   çağırıp RAG doküman sayısını da `NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS`'a göre
   budar.

Her adım kendi `try/except`'i içinde izole edilmiş — biri başarısız olsa da
(`"status": "failed"`) diğerleri çalışmaya devam eder; sonuç raporu
`agent._append_autonomy_history`'ye kaydedilir.

## Test kapısı

`tests/unit/agent/maintenance/test_nightly.py`.
