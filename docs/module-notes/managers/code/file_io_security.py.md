# `managers/code/file_io_security.py` — CodeManager Dosya IO Güvenlik Yardımcıları

- **Kaynak dosya:** `managers/code/file_io_security.py`
- **Not dosyası:** `docs/module-notes/managers/code/file_io_security.py.md`

**Amaç:** `CodeManager`'ın dosya okuma/yazma işlemlerini, her erişimden önce
`manager.security_adapter.can_read()`/`can_write()` politika kontrolünden
geçirerek sarmalar.

**Özellikler:**
- `read_file()` — güvenlik kontrolü + varlık/dizin kontrolü, `manager._lock`
  altında UTF-8 okuma (hatalı byte'lar `errors="replace"` ile tolere edilir),
  isteğe bağlı satır numaralandırma.
- `write_file()` — aynı güvenlik kontrolü + isteğe bağlı sözdizimi
  doğrulaması ile yazma.
- `strip_markdown_code_fences()` — LLM çıktısındaki markdown kod bloğu
  işaretlerini (```` ``` ````) temizler, üretilen içeriğin dosyaya
  yazılmadan önce sarmalayıcılardan arındırılmasını sağlar.
- Gerçek izin verme/reddetme kararı burada değil,
  `managers/code/security_adapter.py`'deki `CodeSecurityAdapter` üzerinden
  verilir — bu modül yalnızca sonucu IO akışına uygular.
