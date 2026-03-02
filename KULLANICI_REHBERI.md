# SİDAR — Kullanıcı Rehberi

**Sürüm:** v2.6.0 · **Son güncelleme:** 2026-03-01

> SİDAR, ReAct (Reason + Act) mimarisi üzerine kurulu, Türkçe dilli, tam asenkron bir yazılım mühendisi AI asistanıdır. Hem tarayıcı tabanlı web arayüzünden hem de terminal (CLI) üzerinden kullanılabilir.

---

## İçindekiler

1. [Kurulum](#1-kurulum)
2. [Yapılandırma (.env)](#2-yapılandırma-env)
3. [Başlatma](#3-başlatma)
4. [Web Arayüzü Kullanımı](#4-web-arayüzü-kullanımı)
5. [Terminal (CLI) Kullanımı](#5-terminal-cli-kullanımı)
6. [Komutlar ve Araçlar](#6-komutlar-ve-araçlar)
7. [Çoklu Oturum (Session) Yönetimi](#7-çoklu-oturum-session-yönetimi)
8. [Erişim Seviyeleri (OpenClaw)](#8-erişim-seviyeleri-openclaw)
9. [Web Arama](#9-web-arama)
10. [Paket Bilgi Araçları](#10-paket-bilgi-araçları)
11. [Belge Deposu (RAG)](#11-belge-deposu-rag)
12. [GitHub Entegrasyonu](#12-github-entegrasyonu)
13. [Kod Çalıştırma (Docker REPL)](#13-kod-çalıştırma-docker-repl)
14. [GPU Desteği](#14-gpu-desteği)
15. [Docker ile Kullanım](#15-docker-ile-kullanım)
16. [Log ve Hata Yönetimi](#16-log-ve-hata-yönetimi)
17. [Sık Sorulan Sorular](#17-sık-sorulan-sorular)

---

## 1. Kurulum

### 1.1 Otomatik Kurulum (Ubuntu / WSL2 — Önerilen)

```bash
chmod +x install_sidar.sh
./install_sidar.sh
```

Betik sırasıyla şunları yapar:
1. Sistem paketlerini günceller (`curl`, `git`, `build-essential`, `ffmpeg` vb.)
2. Google Chrome kurar
3. Miniconda indirir ve kurar
4. Ollama indirir ve kurar
5. Projeyi GitHub'dan klonlar (varsa günceller)
6. `sidar-ai` adlı Conda ortamını `environment.yml`'den oluşturur
7. Varsayılan modelleri indirir: `nomic-embed-text`, `qwen2.5-coder:7b`, `gemma2:9b`

Kurulum bittikten sonra **terminali kapatıp yeniden açın**.

### 1.2 Manuel Kurulum

```bash
# 1. Projeyi klonlayın
git clone https://github.com/niluferbagevi-gif/sidar_project
cd sidar_project

# 2. Conda ortamını oluşturun
conda env create -f environment.yml

# 3. Ortamı etkinleştirin
conda activate sidar-ai

# 4. .env dosyasını oluşturun
cp .env.example .env
```

---

## 2. Yapılandırma (.env)

Proje kökündeki `.env` dosyası tüm ayarları barındırır. `.env.example` dosyasını kopyalayarak başlayın:

```bash
cp .env.example .env
```

### 2.1 Zorunlu Ayarlar

| Değişken | Açıklama | Varsayılan |
|---|---|---|
| `AI_PROVIDER` | `ollama` (yerel) veya `gemini` (bulut) | `ollama` |
| `OLLAMA_URL` | Ollama API adresi | `http://localhost:11434/api` |
| `CODING_MODEL` | Kod yazma için kullanılacak model | `qwen2.5-coder:7b` |
| `ACCESS_LEVEL` | Erişim seviyesi (`restricted`/`sandbox`/`full`) | `sandbox` |

### 2.2 Opsiyonel Ayarlar

**Google Gemini (bulut LLM):**
```env
AI_PROVIDER=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash
```

**GitHub Entegrasyonu:**
```env
GITHUB_TOKEN=ghp_...
GITHUB_REPO=kullanici/depo-adi
```
> Token oluşturmak için: GitHub → Settings → Developer Settings → Personal Access Tokens
> Gerekli izinler: `repo` (özel depolar) veya `public_repo` (genel depolar)

**Web Arama:**
```env
SEARCH_ENGINE=auto         # auto | duckduckgo | tavily | google
TAVILY_API_KEY=tvly-...
GOOGLE_SEARCH_API_KEY=...
GOOGLE_SEARCH_CX=...
```
> `auto` modunda: Tavily → Google → DuckDuckGo sıralamasıyla denenir.
> Hiç API anahtarı yoksa DuckDuckGo ücretsiz olarak çalışır.

**GPU:**
```env
USE_GPU=true
GPU_DEVICE=0
GPU_MEMORY_FRACTION=0.8    # 0.1 – 1.0 aralığında
GPU_MIXED_PRECISION=true   # VRAM tasarrufu için (RTX 20xx ve üzeri)
```

**Bellek ve Performans:**
```env
MAX_MEMORY_TURNS=20        # Konuşma geçmişinde tutulacak tur sayısı
MAX_REACT_STEPS=10         # ReAct döngüsü maksimum adım sayısı
OLLAMA_TIMEOUT=60          # API zaman aşımı (WSL2 için 60 önerilir)
```

**Loglama:**
```env
LOG_LEVEL=INFO             # DEBUG | INFO | WARNING | ERROR
LOG_FILE=logs/sidar_system.log
LOG_MAX_BYTES=10485760     # 10 MB
LOG_BACKUP_COUNT=5
```

**HuggingFace (Model Önbelleği):**
```env
HF_TOKEN=hf_...            # Opsiyonel — özel modeller için
HF_HUB_OFFLINE=1           # İlk kurulumdan sonra 1 yapın (daha hızlı başlangıç)
```

---

## 3. Başlatma

### 3.1 Web Arayüzü (Önerilen)

```bash
conda activate sidar-ai
python web_server.py
```

Tarayıcıda açın: `http://localhost:7860`

**Seçenekler:**
```bash
python web_server.py --host 0.0.0.0 --port 7860   # Ağdaki tüm cihazlardan erişim
python web_server.py --level full                   # Erişim seviyesini geçici değiştir
python web_server.py --provider gemini              # Gemini ile başlat
python web_server.py --log debug                    # Debug log seviyesi
```

### 3.2 Terminal (CLI)

```bash
conda activate sidar-ai
python main.py
```

**Seçenekler:**
```bash
python main.py --status                  # Sistem durumunu göster ve çık
python main.py -c "fastapi'yi anlat"     # Tek komut çalıştır ve çık
python main.py --level sandbox           # Erişim seviyesini geçici değiştir
python main.py --provider gemini         # Gemini ile başlat
python main.py --model llama3.2:8b      # Farklı Ollama modeli kullan
python main.py --log DEBUG               # Debug log seviyesi
```

### 3.3 Ollama'yı Başlatma

SİDAR'ı başlatmadan önce Ollama'nın çalışıyor olması gerekir:

```bash
ollama serve          # Arka planda çalıştır
# veya
ollama serve &        # Arka plana at
```

Mevcut modelleri listele:
```bash
ollama list
```

---

## 4. Web Arayüzü Kullanımı

### 4.1 Arayüz Bölümleri

```
┌─────────────────────────────────────────────────────────┐
│ [☰]  SİDAR v2.6.0  [Sandbox] [Model] [Durum] [MD][JSON]│  ← Üst çubuk
├───────────────┬─────────────────────────────────────────┤
│               │                                         │
│  Oturum       │          Sohbet Alanı                   │
│  Geçmişi      │                                         │
│               │   Sidar > Merhaba! Nasıl yardımcı...   │
│  + Yeni       │                                         │
│  Sohbet       │                                         │
│               │                                         │
│  📝 Oturum 1  │                                         │
│  📝 Oturum 2  │─────────────────────────────────────────│
│               │  [📎] Mesajınızı yazın...    [Gönder ▶] │
└───────────────┴─────────────────────────────────────────┘
```

### 4.2 Klavye Kısayolları

| Kısayol | İşlev |
|---|---|
| `Ctrl + Enter` | Mesaj gönder |
| `Ctrl + K` | Yeni sohbet başlat |
| `Ctrl + L` | Aktif sohbet belleğini temizle |
| `Ctrl + T` | Koyu/Açık tema değiştir |
| `Esc` | Yanıt akışını durdur (AbortController) |

### 4.3 Araç Bildirimleri (Tool Badge)

SİDAR bir araç çağırdığında sohbet alanında renkli badge gösterilir:

| Badge | Anlamı |
|---|---|
| `[WEB ARAMA]` | DuckDuckGo / Tavily / Google araması yapılıyor |
| `[KOD ÇALIŞTIR]` | Docker sandbox'ta Python kodu çalıştırılıyor |
| `[DOSYA OKU]` | Yerel dosya okunuyor |
| `[DOSYA YAZ]` | Dosya diske yazılıyor |
| `[GİTHUB]` | GitHub API'ye istek yapılıyor |
| `[PYPI]` | PyPI paket bilgisi sorgulanıyor |
| `[RAG ARAMA]` | Belge deposunda arama yapılıyor |

### 4.4 Oturum Dışa Aktarma

Üst çubukta `MD` ve `JSON` butonlarıyla aktif sohbeti indirin:
- **MD:** Markdown formatında, paylaşılabilir
- **JSON:** Ham veri, programatik işlem için

### 4.5 Dosya Ekleme

Mesaj kutusundaki `📎` simgesine tıklayarak dosya ekleyin:
- Desteklenen formatlar: `.py`, `.txt`, `.md`, `.json`, `.yaml`, `.csv`, `.html`, `.js`, `.ts`, vb.
- Maksimum boyut: **200 KB**

### 4.6 Dal Değiştirme (Git Branch)

Üst çubukta model/dal seçici ile aktif Git dalını değiştirebilirsiniz. Seçim gerçek `git checkout` komutu çalıştırır.

### 4.7 Mobil Kullanım

768px altında üst çubukta `☰` (hamburger) menüsü görünür. Buna tıklayarak oturum kenar çubuğunu açıp kapayabilirsiniz. Sidebar dışına tıklamak otomatik kapatır.

---

## 5. Terminal (CLI) Kullanımı

### 5.1 Dahili Komutlar

| Komut | İşlev |
|---|---|
| `.help` | Komut listesini göster |
| `.status` | Sistem durumunu göster (AI sağlayıcı, GPU, GitHub, web arama) |
| `.clear` | Aktif konuşma belleğini temizle |
| `.health` | Detaylı donanım raporu (CPU, RAM, GPU, sıcaklık) |
| `.gpu` | GPU VRAM'i optimize et ve Python GC çalıştır |
| `.github` | GitHub bağlantı durumunu göster |
| `.level` | Mevcut erişim seviyesini göster |
| `.web` | Web arama motor durumunu göster |
| `.docs` | Belge deposunu listele |
| `.audit` | Proje kod denetimini çalıştır |
| `.exit` / `.q` | SİDAR'dan çık |

### 5.2 Kısa Komutlar (Doğal Dil)

Aşağıdaki ifadeler LLM'e iletilmeden doğrudan işlenir (daha hızlı):

```
web'de ara: python asyncio tutorial
pypi: fastapi
npm: react
github releases: tiangolo/fastapi
docs ara: ChromaDB embedding
belge ekle https://docs.example.com/api
stackoverflow: python asyncio event loop
```

---

## 6. Komutlar ve Araçlar

SİDAR'ın LLM tabanlı ReAct döngüsünde kullanabileceği **25 araç** mevcuttur:

### 6.1 Dosya İşlemleri

| Araç | Kullanım | Örnek |
|---|---|---|
| `list_dir` | Dizin içeriğini listele | "src/ klasörünü listele" |
| `read_file` | Dosya içeriğini oku | "main.py dosyasını oku" |
| `write_file` | Dosya oluştur/üzerine yaz | "Şu kodu app.py'ye kaydet" |
| `patch_file` | Dosyanın belirli satırını değiştir | "Bu fonksiyonu düzelt" |
| `audit` | Proje geneli kod denetimi | "Projeyi denetle" |

> `write_file` tüm dosyayı **ezer**. Küçük değişiklikler için `patch_file` tercih edin.

### 6.2 Kod Çalıştırma

| Araç | Kullanım |
|---|---|
| `execute_code` | Docker sandbox'ta Python kodu çalıştır |

```
# Örnek kullanımlar:
"Bu algoritmayı test et"
"Fibonacci serisini yazdır"
"requests kütüphanesi kurulu mu?"
```

### 6.3 Sistem Araçları

| Araç | Kullanım |
|---|---|
| `health` | OS, CPU, RAM, GPU sıcaklık ve kullanım raporu |
| `gpu_optimize` | VRAM temizle + Python GC çalıştır |

### 6.4 GitHub Araçları

| Araç | Kullanım | Örnek |
|---|---|---|
| `github_info` | Depo istatistikleri | "Bu repoyu anlat" |
| `github_commits` | Son commitler | "Son 5 commit neydi?" |
| `github_read` | Uzak depodan dosya oku | "README'yi oku" |

### 6.5 Web ve Araştırma

| Araç | Kullanım |
|---|---|
| `web_search` | Genel web araması |
| `fetch_url` | URL içeriğini çek ve oku |
| `search_docs` | Kütüphane dokümantasyonu ara |
| `search_stackoverflow` | Stack Overflow araması |

### 6.6 Paket Bilgisi

| Araç | Kullanım | Örnek |
|---|---|---|
| `pypi` | PyPI paket bilgisi | "fastapi paketini araştır" |
| `pypi_compare` | Sürüm karşılaştır | "fastapi 0.110 güncel mi?" |
| `npm` | npm paket bilgisi | "react paketini kontrol et" |
| `gh_releases` | GitHub release listesi | "pytorch'un release'leri" |
| `gh_latest` | En güncel release | "numpy'nin son sürümü nedir?" |

### 6.7 Belge Deposu (RAG)

| Araç | Kullanım |
|---|---|
| `docs_search` | Depodaki belgeler içinde ara |
| `docs_add` | URL'den belge ekle |
| `docs_list` | Mevcut belgeleri listele |
| `docs_delete` | Belge sil |

---

## 7. Çoklu Oturum (Session) Yönetimi

SİDAR her sohbeti ayrı bir oturum olarak saklar. Oturumlar `data/sessions/` klasöründe UUID isimli JSON dosyaları olarak kaydedilir.

### 7.1 Web Arayüzünde

- **Yeni sohbet:** Sol kenar çubuğunda `+ Yeni Sohbet` butonu veya `Ctrl+K`
- **Oturum değiştir:** Kenar çubuğundaki oturum adına tıkla
- **Oturum sil:** Oturum üzerinde çöp kutusu simgesi
- **Oturum arama:** Kenar çubuğu üstündeki arama kutusu
- **Başlık:** İlk mesajın ilk 30 karakterinden otomatik üretilir

### 7.2 Bellek Yönetimi

- Her oturum en fazla `MAX_MEMORY_TURNS × 2` mesaj tutar (varsayılan: 40 mesaj)
- Mesaj sayısı eşiğin %80'ine veya ~6000 tahmini token'a ulaşınca konuşma özetlenir ve arşivlenir
- Özetlenen konuşmalar belge deposuna (RAG) otomatik eklenir

### 7.3 Karantina Mekanizması

Bozuk bir JSON oturum dosyası tespit edildiğinde:
- Dosya `.json.broken` uzantısıyla yeniden adlandırılır
- Log'a `ERROR` ve `WARNING` yazılır
- Diğer oturumlar etkilenmez

---

## 8. Erişim Seviyeleri (OpenClaw)

SİDAR üç katmanlı erişim kontrol sistemi kullanır:

| Seviye | Okuma | Yazma | Kod Çalıştırma |
|---|---|---|---|
| `restricted` | ✅ Tüm dosyalar | ❌ | ❌ |
| `sandbox` | ✅ Tüm dosyalar | ✅ Yalnızca `/temp/` | ✅ Docker sandbox |
| `full` | ✅ Tüm dosyalar | ✅ Her yere | ✅ Docker sandbox |

**`.env`'den ayarlama:**
```env
ACCESS_LEVEL=sandbox
```

**Başlatırken geçici override:**
```bash
python main.py --level full
python web_server.py --level restricted
```

**Mevcut seviyeyi kontrol etme:**
```
.level          # CLI'da
# veya
"erişim seviyem nedir?"   # SİDAR'a sor
```

> **Öneri:** Günlük kullanımda `sandbox` seviyesi yeterlidir. `full` yalnızca proje geneli büyük değişiklikler için kullanın.

---

## 9. Web Arama

### 9.1 Motor Seçimi

`SEARCH_ENGINE` değişkeni ile kontrol edilir:

| Değer | Davranış |
|---|---|
| `auto` | Tavily → Google → DuckDuckGo sıralamasıyla dener |
| `duckduckgo` | Yalnızca DuckDuckGo (ücretsiz, API gerektirmez) |
| `tavily` | Tavily'yi dener, başarısız olursa fallback |
| `google` | Yalnızca Google Custom Search |

### 9.2 Motor Özellikleri

| Motor | Ücretsiz? | site: filtresi | Hız |
|---|---|---|---|
| DuckDuckGo | ✅ | Kısmi destek | Orta |
| Tavily | Kota ile | ✅ | Hızlı |
| Google | Kota ile | ✅ | Hızlı |

### 9.3 Tavily 401/403 Durumu

API anahtarı geçersizse Tavily oturum boyunca devre dışı bırakılır ve otomatik olarak Google/DuckDuckGo'ya geçilir. Log'da `ERROR` mesajı görülür.

---

## 10. Paket Bilgi Araçları

### 10.1 PyPI

```
pypi: numpy                  # Paket bilgisi
pypi_compare: numpy|1.26.0   # Sürüm güncel mi?
```

### 10.2 npm

```
npm: react                   # Paket bilgisi, son sürüm
```

### 10.3 GitHub Releases

```
github releases: tiangolo/fastapi    # Tüm release'ler
github latest: pytorch/pytorch       # En güncel
```

> PEP 440 uyumlu sürüm sıralama: `1.0.0` > `1.0.0rc1` > `1.0.0b2` > `1.0.0a1` doğru sıralanır.

---

## 11. Belge Deposu (RAG)

### 11.1 Nasıl Çalışır?

SİDAR, eklenen belgeleri vektör arama (ChromaDB + sentence-transformers) ve anahtar kelime araması (BM25) ile hibrit olarak sorgular. GPU aktifse embedding modeli CUDA üzerinde çalışır.

### 11.2 Belge Ekleme

**Web arayüzünden:**
```
belge ekle https://docs.python.org/3/library/asyncio.html
```

**CLI'dan:**
```
belge ekle https://fastapi.tiangolo.com/tutorial/
```

SİDAR URL'yi çeker, metni temizler, parçalara (chunk) böler ve depoya ekler.

### 11.3 Belge Sorgulama

```
docs ara: asyncio event loop nasıl çalışır
```

### 11.4 Depoyu Listeleme ve Silme

```
.docs                         # CLI'da listele
"belgeleri listele"            # Serbest metin
"<doc_id> belgesini sil"       # ID ile sil
```

### 11.5 Chunk Ayarları (.env)

```env
RAG_CHUNK_SIZE=1000      # Parça boyutu (karakter)
RAG_CHUNK_OVERLAP=200    # Örtüşme miktarı (karakter)
RAG_TOP_K=3              # Arama sonucu sayısı
RAG_DIR=data/rag         # Depolama dizini
```

---

## 12. GitHub Entegrasyonu

### 12.1 Kurulum

`.env` dosyasına ekleyin:
```env
GITHUB_TOKEN=ghp_...
GITHUB_REPO=kullanici/depo-adi
```

### 12.2 Özellikler

```
"bu reponun bilgilerini göster"     # github_info
"son 10 commit neydi?"              # github_commits
"README.md dosyasını oku"           # github_read (uzaktan)
```

### 12.3 Depo Değiştirme

**Web arayüzünden:** Üst çubuktaki repo seçicisinden

**Sohbet yoluyla:**
```
"depoyu fastapi/fastapi olarak değiştir"
```

### 12.4 Güvenlik

GitHub'dan okunan dosyalar uzantıya göre filtrelenir:
- **İzinli uzantılar:** `.py`, `.md`, `.json`, `.yaml`, `.txt`, `.js`, `.ts`, `.sh` vb.
- **İzinli uzantısız dosyalar:** `Makefile`, `Dockerfile`, `LICENSE`, `README` vb.
- Diğer tüm dosyalar (özellikle binary) reddedilir.

---

## 13. Kod Çalıştırma (Docker REPL)

### 13.1 Gereksinim

Docker'ın çalışıyor olması gerekir:

```bash
# Ubuntu/WSL2:
sudo service docker start
# veya:
dockerd &

# macOS:
# Docker Desktop uygulamasını başlatın

# Doğrulama:
docker ps
```

### 13.2 Sandbox Özellikleri

| Özellik | Değer |
|---|---|
| İmaj | `python:3.11-alpine` (yapılandırılabilir) |
| Ağ erişimi | ❌ Devre dışı (`network_disabled=True`) |
| RAM limiti | 128 MB |
| CPU limiti | %50 |
| Zaman aşımı | 10 saniye |
| Container temizliği | Otomatik (çalışma sonrası) |

### 13.3 Kullanım

```
"1'den 100'e kadar asal sayıları bul"
"Bu fonksiyonu test et: def fib(n): ..."
"numpy ile matris çarpımı yap"
```

### 13.4 Docker İmajını Değiştirme

```env
DOCKER_PYTHON_IMAGE=python:3.11-slim   # .env'de
```

### 13.5 Docker Yoksa

Docker bulunamazsa SİDAR kullanıcıya açıklayıcı bir mesaj gösterir ve nasıl başlatılacağını yönlendirir.

---

## 14. GPU Desteği

### 14.1 Aktif Etme

```env
USE_GPU=true
GPU_DEVICE=0                   # Hangi GPU (0-indexed)
GPU_MEMORY_FRACTION=0.8        # VRAM'in %80'ini kullan
GPU_MIXED_PRECISION=true       # FP16 (RTX 20xx ve üzeri önerilir)
```

### 14.2 GPU Ne İçin Kullanılır?

- **Embedding modeli:** `sentence-transformers/all-MiniLM-L6-v2` — RAG belgelerini vektöre dönüştürür
- **Ollama:** GPU katman sayısı otomatik ayarlanır (`num_gpu=-1`)

### 14.3 WSL2 Notları

- `pynvml` GPU sıcaklık/kullanım bilgisi WSL2'de kısıtlı olabilir — graceful fallback uygulanır
- NVIDIA sürücüsü Windows tarafında kurulu olmalı; WSL2 içinde ayrıca kurmaya gerek yok
- `nvidia-smi` WSL2'de çalışıyorsa GPU kurulumu doğrudur

### 14.4 GPU Durumunu Kontrol Etme

```bash
# CLI:
.health
# veya:
.gpu

# Web arayüzünden /status endpoint'i:
curl http://localhost:7860/status
```

### 14.5 GPU Yoksa (CPU Modu)

`USE_GPU=false` ile sorunsuz CPU modunda çalışır. RAG embedding biraz daha yavaş olur ancak tamamen işlevseldir.

---

## 15. Docker ile Kullanım

### 15.1 Mevcut Servisler

| Servis | Açıklama | Port |
|---|---|---|
| `sidar-ai` | CLI modu, CPU | — |
| `sidar-gpu` | CLI modu, GPU | — |
| `sidar-web` | Web arayüzü, CPU | 7860 |
| `sidar-web-gpu` | Web arayüzü, GPU | 7861 |

### 15.2 Başlatma

```bash
# CPU — Web arayüzü:
docker compose up sidar-web

# GPU — Web arayüzü:
docker compose up sidar-web-gpu

# CPU — CLI:
docker compose up sidar-ai

# GPU — CLI:
docker compose up sidar-gpu

# Arka planda çalıştır:
docker compose up -d sidar-web
```

### 15.3 Manuel Docker Build

```bash
# CPU build:
docker build -t sidar-ai .

# GPU build (CUDA 12.4):
docker build \
  --build-arg BASE_IMAGE=nvidia/cuda:12.4.1-runtime-ubuntu22.04 \
  --build-arg GPU_ENABLED=true \
  --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124 \
  -t sidar-ai-gpu .
```

### 15.4 Veri Kalıcılığı

Docker servisleri şu dizinleri host'a bağlar:

| Container Yolu | Host Yolu |
|---|---|
| `/app/data` | `./data` |
| `/app/logs` | `./logs` |
| `/app/temp` | `./temp` |
| `/app/.env` | `./.env` |

---

## 16. Log ve Hata Yönetimi

### 16.1 Log Dosyası

```bash
tail -f logs/sidar_system.log          # Anlık takip
grep "ERROR" logs/sidar_system.log    # Hataları filtrele
grep "WARNING" logs/sidar_system.log  # Uyarıları filtrele
```

### 16.2 Debug Modu

```bash
python main.py --log DEBUG
python web_server.py --log debug
```

`.env`'den kalıcı olarak:
```env
LOG_LEVEL=DEBUG
```

### 16.3 Yaygın Sorunlar

| Sorun | Olası Neden | Çözüm |
|---|---|---|
| `Ollama'ya bağlanılamadı` | Ollama çalışmıyor | `ollama serve` çalıştırın |
| `GPU görünmüyor` | WSL2 sürücü sorunu | `nvidia-smi` çalıştırın; Docker Desktop GPU entegrasyonunu etkinleştirin |
| `Docker sandbox devre dışı` | Docker çalışmıyor | `sudo service docker start` |
| `GitHub: Bağlı değil` | Token eksik/hatalı | `.env`'e `GITHUB_TOKEN` ekleyin |
| `Tavily hata 401/403` | API anahtarı geçersiz | Tavily dashboard'dan yeni anahtar alın; DuckDuckGo'ya fallback otomatik |
| `Bellek arşivleniyor` | Konuşma çok uzadı | Normaldir; otomatik özetleme çalışır |
| Yanıt çok yavaş | WSL2 I/O gecikmesi | `.env`'de `OLLAMA_TIMEOUT=120` yapın |
| Bozuk oturum dosyası | Dosya bozulmuş | `.json.broken` olarak karantinaya alınır; diğerleri etkilenmez |

---

## 17. Sık Sorulan Sorular

**S: Hangi Ollama modelleri SİDAR ile çalışır?**
> `ollama list` komutuyla kurulu modelleri görün. Varsayılan `qwen2.5-coder:7b`'dir. `python main.py --model llama3.2:8b` ile değiştirebilirsiniz. Yeni bir modeli deneyin: `ollama pull <model-adı>`

**S: SİDAR aynı anda birden fazla kullanıcıyla kullanılabilir mi?**
> Web sunucusu tek ajan singleton kullanır. Eş zamanlı kullanımda yanıtlar sıralı işlenir. Çok kullanıcılı senaryolar için ayrı instance başlatın.

**S: Konuşma geçmişim nereye kaydediliyor?**
> `data/sessions/` klasöründe UUID isimli `.json` dosyaları olarak. Her oturum ayrı dosyada saklanır.

**S: HuggingFace token olmadan RAG çalışır mı?**
> Evet. `all-MiniLM-L6-v2` modeli ücretsiz ve token gerektirmez. `HF_TOKEN` yalnızca özel/kısıtlı modeller için gereklidir.

**S: `HF_HUB_OFFLINE=1` ne işe yarar?**
> İlk kurulumda modeli indirdikten sonra `1` yapın. Her açılışta HuggingFace'e internet kontrolü yapmaz, yerel önbellekten yükler — başlangıç ~1 dakika daha hızlı olur.

**S: Gemini ile Ollama arasındaki fark nedir?**
> Ollama yerel modeller çalıştırır (internet bağlantısı gerekmez, tam gizlilik). Gemini Google'ın bulut API'sidir (API anahtarı ve internet gerekli, genellikle daha yetenekli).

**S: Rate limiting limitleri nelerdir?**
> `/chat` endpoint'i: 20 istek/dakika/IP. Diğer işlemler (oturum oluştur/sil): 60 istek/dakika/IP. Limit aşılırsa `HTTP 429` döner.

**S: Bir hata raporu nasıl gönderebilirim?**
> GitHub Issues: `https://github.com/niluferbagevi-gif/sidar_project/issues`

---

*Bu rehber `data/sessions/`, `core/`, `agent/`, `managers/`, `web_server.py`, `main.py`, `config.py`, `Dockerfile`, `docker-compose.yml`, `environment.yml`, `.env.example` ve `install_sidar.sh` dosyaları satır satır incelenerek oluşturulmuştur.*

*Son güncelleme: 2026-03-01 — SİDAR v2.6.0* 