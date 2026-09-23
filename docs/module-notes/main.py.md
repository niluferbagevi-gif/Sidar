# `main.py` — Akıllı Başlatıcı (848 satır)

**Amaç:** Sidar'ı başlatmak için etkileşimli sihirbaz veya `--quick` hızlı mod sağlar.

**İsimlendirme notu:** `main.py` ajan REPL'i *değildir* — yalnızca preflight/sihirbaz
akışını çalıştırıp sonunda `cli.py`'yi (gerçek REPL giriş noktası) veya
`web_server.py`'yi alt süreçte başlatır. `cli.py`, ismi tarihsel olarak
`main.py`'den `cli.py`'ye taşınmış eski/asıl giriş noktasıdır; bugünkü kökteki
`main.py` sonradan eklenen, tamamen farklı bir launcher modülüdür. Bkz.
`docs/module-notes/cli.py.md`.

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

## `launcher/` altına taşınan mantık (2026-09, 1232 → 848 satır)

`main.py`'de aynı adlı ince sarmalayıcılar kaldı; testlerin `main` üzerinde patch
ettiği isimler (`confirm`, `ask_choice`, `cfg`, `MAX_AUTOFIX_RETRIES`,
`_run_doctor_auto_fix_command` vb.) çağrı anında çözülüp parametre olarak geçirilir.

| `main.py` | Yeni konum |
|---|---|
| `_launcher_session_lock`, `_save_launcher_session`, `_load_launcher_session` | `launcher/session.py` |
| `_parse_doctor_env_source_file`, `_reload_doctor_env_source_definitions`, `_reload_database_env_from_loaded_dotenv_chain` | `launcher/env_reload.py` |
| `_run_doctor_auto_fix_command`, `_run_doctor_auto_fix`, `_revalidate_doctor_check_after_auto_fix` | `launcher/doctor.py` |
| `main()` argparse tanımı ve `--port` doğrulaması | `launcher/cli_args.py` |
| `preflight()` API anahtarı ve Ollama kontrolleri | `launcher/preflight.py` |
| `run_wizard()` seçenek tabloları ve varsayılanlar | `launcher/wizard.py` |

`main.py`'de bilinçli olarak kalanlar: `cfg`/`config_module` ve Doctor durum
global'leri, `_reload_config_environment` (global `cfg`'yi yeniden atar) ve
sihirbazın `ask_*` çağrıları.

## `run_wizard()` 4 Adımlı Etkileşimli Menü

Parametresiz kullanımda (`python main.py`) sihirbaz aşağıdaki sıralı menüyü çalıştırır:

1. **Arayüz seçimi**
   - Web Arayüzü Sunucusu (FastAPI + UI)
   - CLI Terminal Arayüzü
2. **AI sağlayıcı seçimi**
   - Ollama (Yerel LLM)
   - Gemini (Bulut LLM)
   - OpenAI (Bulut LLM)
   - Anthropic Claude (Bulut LLM)
3. **Güvenlik/Yetki seviyesi seçimi**
   - Full
   - Sandbox
   - Restricted
4. **Log seviyesi seçimi**
   - `info`, `debug`, `warning`

Ardından seçime bağlı ek sorular gelebilir:
- **Web modu** için `host` ve `port`
- **CLI + Ollama** için `model`

Son aşamada `Sidar'ı başlatmak istiyor musunuz? [Y/n]` onayı alınır.

## Çalışma Akışı (Genel Mantık)

1. **Konfigürasyon yükleme (fallback):** Önce `config.py` içinden `Config` yüklenir; başarısız olursa `DummyConfig` devreye girer.
2. **Argparse ayrıştırma:** CLI argümanları okunur; `--quick` varsa sihirbaz atlanır.
3. **Çalıştırma yolu seçimi:**
   - `--quick` yoksa `run_wizard()` ile etkileşimli seçim akışı
   - `--quick` varsa argüman + varsayılan birleştirme
4. **Ön kontroller (`preflight`):** Python sürümü, `.env`, sağlayıcı anahtarları ve Ollama erişimi doğrulaması.
5. **Komut inşası (`build_command`):** `cli.py` veya `web_server.py` için nihai komut listesi oluşturma.
6. **Alt süreçte çalıştırma (`execute_command`):** `subprocess` ile başlatma; gerekirse streaming yakalama ve `--child-log` dosya akışı.

## `--quick` Mod Argümanları

```bash
python main.py --quick web --host 0.0.0.0 --port 7860
python main.py --quick cli --provider gemini --level sandbox
python main.py --quick web --capture-output --child-log logs/child.log
python main.py --quick cli --provider ollama --model qwen2.5-coder:7b --log debug
```

## Varsayılan Değerler ve Ekstra Parametreler

- `--log`: `info` (varsayılan), `debug`, `warning`
- `--model`: Ollama için varsayılan model `qwen2.5-coder:7b`
- Web varsayılanları: Port `7860`; Host **`127.0.0.1`** (yalnız loopback — dış erişim
  `--host`/`WEB_HOST` ile bilinçli olarak açılır; `python main.py --quick web --host 0.0.0.0 ...`
  örnekleri bu bilinçli override'ı gösterir, varsayılanı değil)

## Analiz Derinliği Notu

Bu doküman **satır satır teknik çözümleme** yerine hızlı referans niteliği taşır.
Kapsamı; temel fonksiyon özeti, akış, argüman örnekleri ve varsayılan davranışların kısa belgelenmesidir.

**Mimari Not:** `DummyConfig` fallback sınıfı ile `config.py` olmadan da çalışır.