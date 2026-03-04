# config.py Teknik Notu

`config.py`, Sidar projesinin merkezi yapılandırma modülüdür. Uygulama başlarken önce devreye girer; ortam değişkenleri, loglama, donanım tespiti ve çalışma parametrelerini tek noktadan yönetir.

## 1) Temel Görevleri

### 1.1 Ortam değişkenlerini yüklemek
- Proje kökü (`BASE_DIR`) ve `.env` yolu (`ENV_PATH`) belirlenir.
- `.env` dosyası varsa `load_dotenv(...)` ile yüklenir, yoksa varsayılanlara düşülür.
- Bu akış, ayarların merkezi olarak dışarıdan yönetilmesini sağlar.

### 1.2 Güvenli tip dönüşümleri
- `get_bool_env`, `get_int_env`, `get_float_env`, `get_list_env` yardımcıları ile env değerleri güvenli biçimde parse edilir.
- Hatalı değer geldiğinde exception patlatmak yerine varsayılana dönülür.

### 1.3 Merkezi log altyapısı kurmak
- `logging.basicConfig(...)` ile hem stdout hem de döner dosya logu (`RotatingFileHandler`) birlikte kurulur.
- Log boyutu (`LOG_MAX_BYTES`) ve yedek sayısı (`LOG_BACKUP_COUNT`) env ile yönetilir.

### 1.4 Donanım (GPU/CPU/WSL2) tespiti
- `_is_wsl2()` ile WSL2 koşulu kontrol edilir.
- `check_hardware()` içinde CUDA varlığı, GPU adı/sayısı, CUDA sürümü, CPU çekirdek sayısı ve opsiyonel NVML sürücü bilgisi toplanır.
- `USE_GPU=false` ise GPU yolu erken kapatılır.
- GPU varsa `torch.cuda.set_per_process_memory_fraction(...)` ile VRAM kullanım yüzdesi sınırlandırılır.

### 1.5 Çalışma öncesi doğrulama ve özet
- `initialize_directories()` ile `temp/`, `logs/`, `data/` dizinleri garanti edilir.
- `validate_critical_settings()` ile kritik ayarlar doğrulanır:
  - Gemini modunda API key,
  - Fernet anahtar formatı ve `cryptography` varlığı,
  - Ollama endpoint erişilebilirliği.
- `get_system_info()` ve `print_config_summary()` ile çalışır sistem özeti üretilir.

---

## 2) Config Sınıfı: Neleri Merkezileştirir?

`Config` sınıfı, projenin parametre deposudur. Başlıca kümeler:

- Genel: `PROJECT_NAME`, `VERSION`, `DEBUG_MODE`
- Dizinler: `BASE_DIR`, `TEMP_DIR`, `LOGS_DIR`, `DATA_DIR`, `MEMORY_FILE`
- AI/LLM: `AI_PROVIDER`, `GEMINI_*`, `OLLAMA_*`, `CODING_MODEL`, `TEXT_MODEL`
- Erişim: `ACCESS_LEVEL`
- GitHub: `GITHUB_TOKEN`, `GITHUB_REPO`
- GPU: `USE_GPU`, `GPU_*`, `CUDA_VERSION`, `DRIVER_VERSION`, `GPU_MEMORY_FRACTION`
- ReAct: `MAX_REACT_STEPS`, `REACT_TIMEOUT`
- Web arama: `SEARCH_ENGINE`, `TAVILY_API_KEY`, `GOOGLE_SEARCH_*`, timeout/limitler
- RAG: `RAG_DIR`, `RAG_TOP_K`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_FILE_THRESHOLD`
- Docker sandbox: `DOCKER_PYTHON_IMAGE`, `DOCKER_EXEC_TIMEOUT`
- Bellek şifreleme: `MEMORY_ENCRYPTION_KEY`
- Web sunucu: `WEB_HOST`, `WEB_PORT`

---

## 3) Hangi Dosyalarla Bağlantılı Çalışır?

## 3.1 Girdi aldığı kaynaklar
- `.env` / `.env.example`: ham ayar sözleşmesi ve değer kaynağı.

## 3.2 Doğrudan tüketiciler
- `main.py`
  - CLI override (`--level`, `--provider`, `--model`) sonrası `cfg` değerlerini günceller.
- `web_server.py`
  - CORS ve web başlatma (`WEB_HOST`, `WEB_PORT`) dahil servis davranışında `cfg` kullanır.
- `agent/sidar_agent.py`
  - Güvenlik seviyesi, modeller, memory, RAG, GitHub, Docker sandbox parametrelerini `cfg` üzerinden alır.
- `tests/test_sidar.py`
  - `Config` ve `HARDWARE` import ederek doğrulama testleri yapar.

## 3.3 Dolaylı tüketiciler
- `agent/sidar_agent.py` içinden yaratılan manager/core bileşenleri (`CodeManager`, `DocumentStore`, `LLMClient`, `ConversationMemory`) kendi çalışma ayarlarını bu config akışından alır.

---

## 4) Sağlanan Değerlendirmelerle Karşılaştırma (Doğrulama Notu)

Kullanıcıdan gelen iki ayrı değerlendirme metnindeki ana iddialar tek tek kontrol edildi:

- ✅ Merkezi yapılandırma/omurga rolü: **doğru**
- ✅ `.env` yükleme + helper parse fonksiyonları: **doğru**
- ✅ Rotating log altyapısı (10MB, 5 backup varsayılanı): **doğru**
- ✅ WSL2/GPU/CUDA tespiti ve VRAM fraksiyonu: **doğru**
- ✅ Config sınıfında AI, RAG, Docker, Web, GitHub, güvenlik/erişim ayarlarının toplanması: **doğru**
- ✅ Fernet anahtar doğrulaması ve kritik ayar validasyonu: **doğru**
- ✅ `main.py`, `web_server.py`, `agent/sidar_agent.py`, testlerle entegrasyon: **doğru**

Ek not:
- Test dosyasında güncel `test_` fonksiyon sayısı 64’tür; daha eski raporlardaki 48 sayısı tarihsel kalmış olabilir.

---

## 5) Kısa Sonuç

`config.py`, Sidar’da yalnızca bir ayar dosyası değil; başlatma davranışı, güvenlik kontrolü, çalışma profili ve operasyonel görünürlük (logging/system info) için ortak karar noktasıdır. Kod tabanının büyük bölümüne doğrudan etki eder, bu yüzden yapılan her değişiklikte `.env.example` ve ilgili tüketici modüller birlikte gözden geçirilmelidir.