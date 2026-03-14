# 3.2 `main.py` — Akıllı Başlatıcı (225 satır)

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
- Web varsayılanları: Host `0.0.0.0`, Port `7860`

## Analiz Derinliği Notu

Bu doküman **satır satır teknik çözümleme** yerine hızlı referans niteliği taşır.
Kapsamı; temel fonksiyon özeti, akış, argüman örnekleri ve varsayılan davranışların kısa belgelenmesidir.

**Mimari Not:** `DummyConfig` fallback sınıfı ile `config.py` olmadan da çalışır.
