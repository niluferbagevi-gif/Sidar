# `web/process_lifecycle.py` — Web Runtime Süreç Yaşam Döngüsü

- **Kaynak dosya:** `web/process_lifecycle.py`
- **Not dosyası:** `docs/module-notes/web/process_lifecycle.py.md`

**Amaç:** Web sunucusu kapanırken (graceful shutdown) yetim alt süreçleri
(örn. Ollama child process'leri) bulup temizleyen yardımcılar; `ps`
komutunu yalnızca güvenilir mutlak sistem yollarından (`SAFE_PS_PATHS`)
çözerek PATH hijacking riskini engeller. Alt süreç çağrıları
`core/utils/trusted_subprocess.py` üzerinden geçer.

**Özellikler:**
- `resolve_safe_ps_binary(*, safe_paths=SAFE_PS_PATHS)` — yalnızca
  `/bin/ps`/`/usr/bin/ps` gibi mutlak, sabit yolları kabul eder.
- `list_child_ollama_pids(...)` — çalışan Ollama child process PID'lerini
  listeler.
- `reap_child_processes_nonblocking()` — zombie/yetim süreçleri bloklamadan
  temizler.
- `terminate_process_pids(...)` — verilen PID'lere nazik/zorla sonlandırma
  uygular.
