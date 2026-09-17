# `launcher/process.py` — Launcher Subprocess Yardımcıları

- **Kaynak dosya:** `launcher/process.py`
- **Not dosyası:** `docs/module-notes/launcher/process.py.md`

**Amaç:** `main.py`'den (eskiden ~130 satırlık tek dosyanın parçası olarak)
birebir çıkarılan komut kurma ve canlı çıktı akıtma yardımcıları; `main.py`
geriye dönük uyumluluk için bu fonksiyonlara ince sarmalayıcılar tutar.
Alt süreç çalıştırma `core/utils/trusted_subprocess.py`'nin
`popen_trusted_command()`'ı üzerinden geçer (Bandit B603 merkezileştirmesi).

**Özellikler:**
- `build_command(...)` — launch seçimlerinden çalıştırılacak komut listesini kurar.
- `launcher_child_env()` — alt sürece aktarılacak ortam değişkenlerini hazırlar.
- `format_cmd(cmd)` — komutu insan-okunur log/onay metnine çevirir.
- `stream_pipe(...)`, `run_with_streaming(...)` — alt süreç stdout/stderr'ini
  gerçek zamanlı terminale akıtır.
