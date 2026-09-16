# `core/config_sandbox.py` — Docker Kod Çalıştırma Sandbox Ayarları

- **Kaynak dosya:** `core/config_sandbox.py`
- **Not dosyası:** `docs/module-notes/core/config_sandbox.py.md`

**Amaç:** Docker REPL sandbox'ının kaynak limitlerini ve çalışma zamanı
ayarlarını `SandboxSettings` frozen dataclass'ı olarak yükler; `managers/code/`
altındaki güvenlik modüllerinin (`shell_sandbox.py`, `security_adapter.py`)
tükettiği canonical yapılandırma kaynağıdır — `CLAUDE.md`'deki "fail-closed
sandbox" ilkesinin ayar katmanı.

**Özellikler:**
- `SandboxSettings` — `sandbox_limits` (dict, CPU/bellek/zaman limitleri),
  `code_execution_backend`.
- `config_env_helpers`'daki prefixed helper'larla (`SIDAR_*` öncelikli) liste/
  int/bool/optional değerleri okur; env eksikse güvenli varsayılanlara düşer.
