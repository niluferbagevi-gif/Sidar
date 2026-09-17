# agent/self_heal/

- **Kaynak dizini:** `agent/self_heal/` (`__init__.py`, `orchestrator.py`,
  `planner.py`, `executor.py`)
- **Not dosyası:** `docs/module-notes/agent/self_heal.md`

## Amaç

`SidarAgent`'ın CI hata giderme (self-heal) akışını üç sorumluluğa bölen servis
sınırı. `agent/sidar_agent.py`, üçünü de doğrudan import edip ince wrapper
metotlarla (`_attempt_autonomous_self_heal` vb.) çağırıyor; `agent/triggers.py`
CI tetikleyicisi de bu wrapper'lar üzerinden akışı başlatıyor.

- **`orchestrator.py::attempt_autonomous_self_heal(agent, *, ci_context,
  diagnosis, remediation, human_approval=None)`:** Üst seviye kapı. Sırasıyla
  `ENABLE_AUTONOMOUS_SELF_HEAL` bayrağını, remediation loop'un `"planned"`
  durumda olup olmadığını ve `needs_human_approval` bayrağını kontrol eder;
  HITL onayı gerekiyorsa `SELF_HEAL_DEFAULT_DECISION` (`prompt`/`approve`/
  `reject`) varsayılanına düşer. `__init__.py`'de export edilmiyor —
  `agent/sidar_agent.py` `agent.self_heal.orchestrator`'dan doğrudan import
  ediyor.
- **`planner.py::collect_snapshots`/`resolve_scope_batches`/`build_plan`:**
  LLM'e gönderilecek yama planını üretir. `collect_snapshots`, en fazla ilk 6
  `scope_paths`'i okuyup `{"path", "content"}` sözlükleri döner;
  `_CodeReader`/`_ChatClient` `Protocol`'leri agent runtime'ından ayrık test
  edilebilirlik sağlar. Kendi ifadesiyle: deterministik teşhis/politika
  `core/ci_remediation.py`'de kalır, bu modül yalnızca LLM'e sunulacak planı
  üretir.
- **`executor.py::execute_mechanical_autofix`/`execute_self_heal_plan`/
  `restore_self_heal_backups`:** Yan etkili uygulama adımı — scope doğrulama,
  yama uygulama, doğrulama komutları ve rollback. `execute_mechanical_autofix`,
  LLM planı oluşturulmadan önce deterministik bir Ruff autofix dener ve
  doğrular (kısa devre); başarısız olursa `restore_self_heal_backups` yedekleri
  geri yazar. `_CodeManagerLike` `Protocol`'ü gerçek `CodeManager`'ın
  `read_file`/`write_file`/`patch_file`/`run_shell_in_sandbox` yüzeyini test
  amaçlı daraltır.

## Test kapısı

`tests/unit/agent/self_heal/test_executor.py` (hafif `_CodeManagerLike` stub'ı
ile mekanik autofix kısa devre dallarını hedefler) ve
`tests/integration/workflow/test_self_heal_e2e.py` (gerçek sandbox stack'iyle
uçtan uca akış); `orchestrator.py`/`planner.py` `tests/unit/agent/
test_sidar_agent.py` üzerinden `SidarAgent`'ın wrapper metotları aracılığıyla
dolaylı test ediliyor.
