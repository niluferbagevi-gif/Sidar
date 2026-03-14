# `main.py` Modül Notları (Güncel)

Bu doküman, projenin giriş başlatıcısı olan `main.py` dosyasının **sorumluluğunu**, **çalışma akışını** ve **bağımlılıklarını** özetler.

## 1) Ne işe yarar?

`main.py`, Sidar için bir **launcher/orchestrator** görevi görür:

- Etkileşimli sihirbaz (wizard) ile kullanıcıdan mod/sağlayıcı/erişim/log seçimleri alır.
- `--quick` parametresi ile sihirbazı atlayıp doğrudan hızlı başlatma yapar.
- Seçimlere göre hedef scripti belirleyip alt süreçte çalıştırır:
  - `cli.py` (CLI modu)
  - `web_server.py` (Web modu)
- Çalıştırma öncesinde temel `preflight` kontrollerini yapar.
- İsteğe bağlı olarak alt süreç stdout/stderr çıktısını canlı akıtır ve dosyaya kaydeder.

## 2) Çalışma akışı

1. `config.py` içinden `Config` yüklenmeye çalışılır.
2. `config.py` yoksa `DummyConfig` ile güvenli varsayılanlara düşülür.
3. Kullanıcı:
   - sihirbaz modunda (`python main.py`) etkileşimli seçim yapar, veya
   - hızlı modda (`python main.py --quick ...`) argümanlarla ilerler.
4. `preflight(provider)` çağrısı ile:
   - Python sürümü,
   - `.env` varlığı,
   - provider API anahtarları,
   - Ollama ağ erişimi (mümkünse `httpx` ile)
   kontrol edilir.
5. `build_command(...)` ile çalıştırılacak komut inşa edilir.
6. `execute_command(...)` ile alt süreç başlatılır.

## 3) Girdi argümanları

`main.py` şu ana argümanları destekler:

- `--quick {cli,web}`
- `--provider {ollama,gemini,openai,anthropic}`
- `--level {restricted,sandbox,full}`
- `--model` (özellikle `cli + ollama` senaryosunda)
- `--host`, `--port` (web için)
- `--log` (`info`, `debug`, `warning`)
- `--capture-output`
- `--child-log <dosya>`

## 4) Hangi dosyalara/servislere ihtiyaç duyar?

### Doğrudan dosyalar

- `main.py` (başlatıcı)
- `cli.py` (CLI hedefi)
- `web_server.py` (Web hedefi)
- `config.py` (opsiyonel ama önerilir)
- `.env` (opsiyonel, ortam değişkenleri için)

### Çalışma zamanı koşulları

- Python 3.10+ önerilir.
- `provider=ollama` ise yerel Ollama servisinin erişilebilir olması beklenir.
- Bulut sağlayıcılarda (`gemini/openai/anthropic`) ilgili API key ortamının tanımlı olması beklenir.

## 5) Davranış notları

- `--quick` yoksa her zaman etkileşimli sihirbaz açılır.
- `cli + ollama` kombinasyonunda model parametresi komuta eklenir.
- `web` modunda host/port komuta eklenir.
- `--capture-output` veya `--child-log` verildiğinde çıktı akışı thread'lerle satır satır işlenir.
- Alt süreç hata kodu launcher tarafından kullanıcıya raporlanır.

## 6) Çalıştırma örnekleri

### Etkileşimli sihirbaz

```bash
python main.py
```

### Hızlı web başlatma

```bash
python main.py --quick web --provider ollama --level full --host 0.0.0.0 --port 7860
```

### Hızlı CLI başlatma (Ollama modeli ile)

```bash
python main.py --quick cli --provider ollama --level sandbox --model qwen2.5-coder:7b
```

### Çıktı yakalama + dosyaya yazma

```bash
python main.py --quick web --capture-output --child-log logs/child.log
```

## 7) Güncelleme kontrol listesi (maintainer checklist)

`main.py` güncellendiğinde bu dokümanda aşağıdakileri eşzamanlı güncelleyin:

- [ ] Yeni/çıkarılan CLI argümanları
- [ ] Yeni provider veya erişim seviyesi seçenekleri
- [ ] `preflight` kontrol adımlarındaki değişiklikler
- [ ] Hedef script seçimi (`cli.py` / `web_server.py`) veya komut üretim mantığı
- [ ] Loglama/capture davranışındaki değişiklikler
- [ ] Çalıştırma örnekleri
