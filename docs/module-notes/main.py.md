# 3.2 `main.py` — Akıllı Başlatıcı (225 satır)

- **Kaynak dosya:** `main.py`
- **Not dosyası:** `docs/module-notes/main.py.md`
- **Amaç:** Bu not dosyası, rapordaki **3.2 main.py — Akıllı Başlatıcı** bölüm içeriğinin taşınmış sürümünü içerir.
- **Durum:** İncelendi ve rapordan modül-notlarına taşındı.

---

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Sidar'ı başlatmak için etkileşimli sihirbaz veya `--quick` hızlı mod sağlar.

**Temel Fonksiyonlar:**

| Fonksiyon | Açıklama |
|-----------|----------|
| `print_banner()` | ANSI renkli ASCII art banner |
| `ask_choice(prompt, options, default_key)` | Güvenli menü seçimi (geçersiz giriş döngüsü) |
| `ask_text(prompt, default)` | Metin girişi (Enter = varsayılan) |
| `confirm(prompt, default_yes)` | Y/n onay istemi |
| `preflight(provider)` | `.env` varlığı, Python sürümü, Ollama/Gemini/OpenAI/Anthropic erişim kontrolü |
| `build_command(mode, provider, level, log, extra_args)` | `cli.py` veya `web_server.py` komutu oluşturur |
| `_stream_pipe(pipe, file_obj, prefix, color, mirror)` | Thread'de pipe akışını bellek dostu okur |
| `_run_with_streaming(cmd, child_log_path)` | Çocuk süreç stdout/stderr canlı yayınlar; opsiyonel dosya logu |
| `execute_command(cmd, capture_output, child_log_path)` | `subprocess.run` veya streaming ile çalıştırır |
| `run_wizard()` | 4 adımlı etkileşimli menü |

**`--quick` Mod Argümanları:**

```bash
python main.py --quick web --host 0.0.0.0 --port 7860
python main.py --quick cli --provider gemini --level sandbox
python main.py --quick web --capture-output --child-log logs/child.log
```

**Mimari Not:** `DummyConfig` fallback sınıfı ile `config.py` olmadan da çalışır.
