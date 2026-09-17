# agent/autonomy/

- **Kaynak dizini:** `agent/autonomy/` (`__init__.py`, `service.py`)
- **Not dosyası:** `docs/module-notes/agent/autonomy.md`

## Amaç

`SidarAgent`'ın otonom (self-heal/CI-tetiklemeli) çalışma geçmişini tutan,
duruma bağımlı olmayan yardımcılar. `AutonomyStateOwner` (`Protocol`) yalnızca
`_autonomy_history: list[dict]` ve `_autonomy_lock: asyncio.Lock | None`
alanlarını gerektirir — gerçek `SidarAgent` bu iki alanı taşıyan sahip
nesnedir.

- **`ensure_autonomy_runtime_state(owner)`:** alanlar yoksa/`None`'sa
  başlatır (lazy init, `SidarAgent.__init__`'i şişirmeden).
- **`append_autonomy_history(owner, record)`:** `asyncio.Lock` altında bir
  kayıt ekler, geçmişi son 50 kayıtla sınırlar (bellek sızıntısını önler).
- **`get_autonomy_activity(owner, limit=20)`:** son `limit` kaydı,
  durum/kaynak bazında sayaçlarla ve `latest_trigger_id` ile birlikte döner —
  `web/routes/operations.py` gibi operasyon panellerinin beslediği veri
  şekli.

## Test kapısı

`tests/unit/agent/test_sidar_agent.py`,
`tests/unit/agent/maintenance/test_nightly.py` (autonomy geçmişini tüketen
gece işi üzerinden), `tests/unit/root/test_web_server.py`.
