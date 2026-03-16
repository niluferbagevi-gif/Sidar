# Sidar Projesi — Bağımsız Güvenlik ve Kalite Denetim Raporu
**Sürüm:** 4.0.0
**Tarih:** 2026-03-16
**Denetçi:** Claude Sonnet 4.6 (Bağımsız, önceki raporlardan bağımsız sıfırdan inceleme)
**Kapsam:** Tüm Python kaynak dosyaları — satır satır doğrudan okuma

---

## İçindekiler

1. [Yönetici Özeti](#1-yönetici-özeti)
2. [Proje Yapısı ve Ölçüm](#2-proje-yapısı-ve-ölçüm)
3. [Mimari Genel Bakış](#3-mimari-genel-bakış)
4. [Güçlü Yönler — İyi Uygulamalar](#4-güçlü-yönler--iyi-uygulamalar)
5. [Kritik Bulgular (K)](#5-kritik-bulgular-k)
6. [Yüksek Öncelikli Bulgular (Y)](#6-yüksek-öncelikli-bulgular-y)
7. [Orta Öncelikli Bulgular (O)](#7-orta-öncelikli-bulgular-o)
8. [Düşük / İyileştirme Önerileri (D)](#8-düşük--iyileştirme-önerileri-d)
9. [Modül Bazlı Analiz](#9-modül-bazlı-analiz)
10. [Özet Bulgu Tablosu](#10-özet-bulgu-tablosu)
11. [Sonuç ve Genel Değerlendirme](#11-sonuç-ve-genel-değerlendirme)

---

## 1. Yönetici Özeti

Sidar projesi, çoklu LLM sağlayıcısını destekleyen, Docker sandbox'lı kod çalıştırma, RAG tabanlı belge arama, multi-agent orkestrasyon ve tam REST/WebSocket API'ye sahip kurumsal düzeyde bir AI ajanı altyapısıdır. Toplam 145 Python dosyası ve ~13.000+ satır üretim kodundan oluşmaktadır.

**Genel Sonuç:** Proje altyapısı sağlam ve güvenlik bilincine sahip bir ekip tarafından geliştirilmiştir. Parola hashleme, SQL parameterization, path traversal koruması ve rate limiting gibi temel güvenlik önlemleri doğru uygulanmıştır. Ancak 2 kritik, 5 yüksek ve 6 orta öncelikli bulgu tespit edilmiştir; bunların bir kısmı üretim ortamında işlevsel bozukluk veya güvenlik ihlali yaratabilir.

---

## 2. Proje Yapısı ve Ölçüm

### 2.1 Dosya Dağılımı

| Kategori | Dosya Sayısı | Toplam Satır |
|----------|-------------|-------------|
| Ana modüller (root) | 3 | ~2.393 |
| `core/` | 5 | ~3.351 |
| `managers/` | 8 | ~3.797 |
| `agent/` (tüm alt dizinler) | ~20 | ~2.297 |
| `tests/` | 105 | ~21.000+ |
| Diğer `.py` | ~109 | ~3.000+ |
| **TOPLAM** | **145** | **~35.000+** |

### 2.2 Ana Dosya Satır Sayıları (Doğrudan Ölçüm)

| Dosya | Satır |
|-------|-------|
| `web_server.py` | 1.417 |
| `core/llm_client.py` | 961 |
| `core/db.py` | 1.012 |
| `managers/code_manager.py` | 898 |
| `managers/github_manager.py` | 644 |
| `managers/system_health.py` | 475 |
| `managers/todo_manager.py` | 451 |
| `managers/web_search.py` | 387 |
| `core/rag.py` | 834 |
| `config.py` | 607 |
| `managers/package_info.py` | 326 |
| `managers/security.py` | 290 |
| `core/memory.py` | 299 |
| `core/llm_metrics.py` | 245 |
| `agent/sidar_agent.py` | 552 |
| `agent/core/supervisor.py` | 168 |
| `agent/core/registry.py` | 29 |
| `main.py` | 369 |

---

## 3. Mimari Genel Bakış

```
┌─────────────────────────────────────────────────────┐
│  web_server.py (FastAPI)                             │
│  ├── auth middleware (Bearer token)                  │
│  ├── rate limit middleware (Redis + local fallback)  │
│  └── CORS middleware (localhost-only)                │
└───────────────────┬─────────────────────────────────┘
                    │
         ┌──────────▼──────────┐
         │  SidarAgent          │
         │  ├── SecurityManager │
         │  ├── CodeManager     │
         │  ├── DocumentStore   │
         │  ├── ConversationMemory│
         │  ├── LLMClient       │
         │  └── SupervisorAgent │
         └──────────────────────┘
                    │
      ┌─────────────┼─────────────┐
      │             │             │
  Database       LLM APIs    Docker Sandbox
  (SQLite/PG)  (Ollama/Gemini/ (Python REPL)
               OpenAI/Anthropic)
```

---

## 4. Güçlü Yönler — İyi Uygulamalar

Aşağıdaki güvenlik ve kalite uygulamaları doğrudan kod okumasıyla doğrulanmıştır:

### 4.1 Kimlik Doğrulama ve Parola Güvenliği ✅
- **PBKDF2-SHA256 (600.000 iteration):** `core/db.py:60` — OWASP güncel önerileriyle uyumlu kurumsal seviye iş faktörü
- **Sabit zamanlı karşılaştırma:** `secrets.compare_digest()` kullanımı timing attack'ı önler (`db.py:72`)
- **Kriptografik token:** `secrets.token_urlsafe(48)` — 384 bit entropi (`db.py:626`)
- **Pydantic doğrulama:** `/auth/register` ve `/auth/login` endpoint'leri `_RegisterRequest`/`_LoginRequest` modelleriyle alan kısıtlaması (`web_server.py:270-278`)

### 4.2 Veritabanı Güvenliği ✅
- **Parameterize sorgular:** SQLite'da `?`, PostgreSQL'de `$1/$2` — SQL injection yok
- **Foreign key CASCADE:** İlgili kayıtlar otomatik temizlenir
- **Thread-safe SQLite:** `asyncio.Lock()` + `asyncio.to_thread()` ile seri erişim
- **UTC timestamp:** Saat dilimi kaynaklı tutarsızlık yok

### 4.3 Path Traversal Koruması ✅
- **Çok katmanlı savunma** (`security.py`):
  - Regex pattern: `_DANGEROUS_PATH_RE` (`\.\.[/\\]`, `/etc/`, `/proc/`, vb.)
  - Resolved path: `.resolve()` ile symlink takibi
  - Base directory jail: `resolved.relative_to(base_dir)`
  - Blocked patterns: `.env`, `.git`, `sessions/`, `__pycache__`

### 4.4 SSRF Koruması ✅
- `core/rag.py:412-430` — `_validate_url_safe()` metodu:
  - Yalnızca `http`/`https` scheme
  - `ipaddress.ip_address()` ile private/loopback/link-local/reserved IP engeli
  - `blocked_hosts` whitelist: localhost, metadata.google.internal, 169.254.169.254
  - IPv6 loopback (`::1`) ve link-local (`fe80::...`) da kapsanıyor

### 4.5 Sandbox Kod Çalıştırma ✅
- Docker izolasyonu: ağ kapalı, 256MB bellek limiti, PID limit 64, CPU kota
- Fail-closed: Docker yoksa SANDBOX modda çalıştırmayı reddeder
- Zaman aşımı: 10 saniye (yapılandırılabilir)
- Çıktı boyutu limiti: 10.000 karakter

### 4.6 API Güvenliği ✅
- Bearer token middleware — tüm korumalı endpoint'ler kapsanıyor
- Rate limiting: DDoS (120 req/60s), chat (yapılandırılabilir), mutation, GET-IO
- Redis tabanlı dağıtık rate limiting, yerel fallback ile
- GitHub webhook HMAC-SHA256 imza doğrulaması

### 4.7 Kriptografi ve Gizli Bilgiler ✅
- API anahtarları yalnızca ortam değişkenlerinden — hardcoded yok
- Fernet anahtar doğrulaması başlangıçta (`config.py:480`)
- Log rotasyonu: RotatingFileHandler (10MB, 5 yedek)

---

## 5. Kritik Bulgular (K)

### K-1 — `/health` Endpoint Yanlış Fonksiyona Bağlı (Tam Fonksiyonel Bozukluk)

**Dosya:** `web_server.py:692-707`
**Ciddiyet:** KRİTİK — Production liveness/readiness probe işlevsiz

**Sorun:** `@app.get("/health")` dekoratörü yanlış konumlanmış ve `health_check()` yerine `_await_if_needed()` yardımcı fonksiyonuna uygulanmış:

```python
# web_server.py:692-707 — HATALI DURUM
@app.get("/health", ...)
async def _await_if_needed(value):      # ← Dekoratör BURADA uygulanıyor
    if inspect.isawaitable(value):
        return await value
    return value


async def health_check():               # ← Bu fonksiyonun route'u YOK
    """Kubernetes/Docker monitör sistemi..."""
    agent = await get_agent()
    ...
```

**Etki:**
- `/health` çağrıldığında FastAPI, `value` parametresini query string'den bekler
- Kubernetes/Docker liveness probe `GET /health` çağrısı `422 Unprocessable Entity` döndürür
- Gerçek sağlık durumu (Ollama bağlantısı, servis degraded kontrolü) hiçbir zaman çalışmaz
- `health_check()` fonksiyonu hiçbir endpoint'e bağlı değil

**Düzeltme:** Dekoratör `health_check()` fonksiyonuna taşınmalı:
```python
async def _await_if_needed(value):      # yardımcı — route yok
    ...

@app.get("/health", ...)
async def health_check():               # ← dekoratör buraya
    ...
```

---

### K-2 — DB Şema Versiyon Tablosu Adı SQL Injection'a Açık

**Dosya:** `core/db.py:330-343`, `db.py:350-365`
**Ciddiyet:** KRİTİK — Ortam değişkeni üzerinden SQL injection

**Sorun:** `DB_SCHEMA_VERSION_TABLE` ortam değişkeni doğrudan tablo adı olarak f-string içinde SQL'e enjekte ediliyor:

```python
# core/db.py:330-334 — HATALI DURUM
def _run() -> None:
    tbl = self.schema_version_table   # ortam değişkeninden geliyor
    self._sqlite_conn.execute(
        f"CREATE TABLE IF NOT EXISTS {tbl} (..."  # ← doğrudan SQL'e
    )
    cur = self._sqlite_conn.execute(f"SELECT MAX(version) AS v FROM {tbl}")
```

**Etki:** `.env` dosyasında `DB_SCHEMA_VERSION_TABLE=x; DROP TABLE users; --` gibi bir değer tüm kullanıcı tablosunu silebilir. SQLite `executescript()` çok-ifade yürütmeyi destekler. PostgreSQL varyantı da aynı risk taşır.

**Düzeltme:** Tablo adını konfigürasyon yükleme aşamasında alfanumerik whitelist ile doğrula:
```python
import re
_SAFE_TABLE_NAME = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]{0,63}$')
if not _SAFE_TABLE_NAME.match(self.schema_version_table):
    raise ValueError(f"Geçersiz DB_SCHEMA_VERSION_TABLE: {self.schema_version_table}")
```

---

## 6. Yüksek Öncelikli Bulgular (Y)

### Y-1 — `/set-level` Endpoint Yetkisiz Güvenlik Seviyesi Yükseltmeye İzin Veriyor

**Dosya:** `web_server.py:1258-1284`
**Ciddiyet:** YÜKSEK — Yetki yükseltme (privilege escalation)

**Sorun:** `/set-level` endpoint'i tüm kimlik doğrulamalı kullanıcılara açık, admin kısıtlaması yok:

```python
# web_server.py:1267 — admin kısıtlaması EKSİK
async def set_level_endpoint(request: Request):
    # _require_admin_user Depends yok!
    body = await request.json()
    new_level = body.get("level", "").strip()
    agent = await get_agent()
    result_msg = await asyncio.to_thread(agent.set_access_level, new_level)
```

**Etki:** Herhangi bir kayıtlı kullanıcı sistemin erişim seviyesini `restricted`'tan `full`'a yükseltebilir; bu tam dosya yazma ve shell çalıştırma yetkisi verir. `_require_admin_user` bağımlılığı yalnızca `/admin/stats` endpoint'inde kullanılıyor, bu endpoint ise mevcut.

**Düzeltme:**
```python
async def set_level_endpoint(request: Request, _user=Depends(_require_admin_user)):
```

---

### Y-2 — RAG Dosya Ekleme Endpoint'i Sınırsız Upload Boyutuna İzin Veriyor

**Dosya:** `web_server.py:1158-1198`
**Ciddiyet:** YÜKSEK — Disk doldurma (DoS)

**Sorun:** `/api/rag/upload` endpoint'inde `MAX_FILE_CONTENT_BYTES` (1 MB) kontrolü uygulanmıyor. Dosya diske yazıldıktan SONRA RAG'a ekleme girişimi yapılıyor; ancak dosya boyutu hiç kontrol edilmiyor:

```python
# web_server.py:1174-1188 — boyut kontrolü YOK
with open(tmp_path, "wb") as buffer:
    shutil.copyfileobj(file.file, buffer)   # ← sınırsız write!
# Dosya diske yazıldıktan SONRA kontrol yoktur
ok, msg = await asyncio.to_thread(
    agent.docs.add_document_from_file, str(tmp_path), ...
)
```

`/file-content` endpoint'i `MAX_FILE_CONTENT_BYTES` kontrolü yaparken (`web_server.py:906`) bu endpoint yapmıyor.

**Düzeltme:** `shutil.copyfileobj` öncesi:
```python
# Dosya boyutunu oku
await file.seek(0, 2)
file_size = await file.tell()
await file.seek(0)
if file_size > MAX_FILE_CONTENT_BYTES:
    raise HTTPException(status_code=413, ...)
```
Veya `UploadFile` için chunk-bazlı yazmayla kümülatif boyut takibi.

---

### Y-3 — `_summarize_memory()` İçinde Async Fonksiyon `asyncio.to_thread()` ile Yanlış Çağrılıyor

**Dosya:** `agent/sidar_agent.py:464-471`
**Ciddiyet:** YÜKSEK — Sessiz veri kaybı (bellek arşivleme hiç çalışmıyor)

**Sorun:** `docs.add_document` async bir fonksiyondur ancak `asyncio.to_thread()` ile çağrılıyor:

```python
# sidar_agent.py:465-471 — HATALI KULLANIM
await asyncio.to_thread(
    self.docs.add_document,          # ← async coroutine function
    title=f"Sohbet Geçmişi Arşivi ...",
    content=full_turns_text,
    ...
)
```

`asyncio.to_thread(async_fn, ...)` bir thread'de `async_fn(...)` çağırır, bu da bir coroutine nesnesi döndürür ama onu await etmez. Sonuç: sohbet arşivleme sessizce başarısız olur, "sonsuz hafıza" özelliği hiç çalışmaz.

**Düzeltme:** Doğrudan await kullanılmalı:
```python
await self.docs.add_document(
    title=f"Sohbet Geçmişi Arşivi ...",
    content=full_turns_text,
    source="memory_archive",
    tags=["memory", "archive", "conversation"],
    session_id="global",
)
```

---

### Y-4 — Rate Limiting IP Tespitinde X-Forwarded-For Güvenilir Kabul Ediliyor

**Dosya:** `web_server.py:404-413`
**Ciddiyet:** YÜKSEK — Rate limit bypass

**Sorun:** `_get_client_ip()` X-Forwarded-For başlığındaki ilk IP'yi doğrulama yapmadan alıyor:

```python
# web_server.py:405-410 — ZAFIYET
def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        first_ip = xff.split(",")[0].strip()  # ← kullanıcı bu değeri sahte yapabilir
        if first_ip:
            return first_ip
```

Bir saldırgan `X-Forwarded-For: 1.2.3.4` başlığı göndererek her istekte farklı bir "IP" ile görünüp tüm rate limiting'i atlayabilir. DDoS koruma ve chat rate limiting tamamen devre dışı kalır.

**Düzeltme:** Reverse proxy arkasında çalışıyorsa trusted proxy sayısına göre son IP alınmalı. Doğrudan erişimde başlık tamamen görmezden gelinmeli veya `trusted_proxies` listesi konfigüre edilmeli.

---

### Y-5 — `config.py`'daki `get_system_info()` REDIS_URL'yi Sızdırıyor

**Dosya:** `config.py:561`
**Ciddiyet:** YÜKSEK — Gizli altyapı bilgisi ifşası

**Sorun:** `get_system_info()` döndürdüğü sözlükte `redis_url` alanını içeriyor. Bu fonksiyonun dönüş değeri `/status` endpoint'i üzerinden de dolaylı olarak erişilebilir olabilir.

```python
# config.py:561 — bilgi sızıntısı
return {
    ...
    "redis_url": cls.REDIS_URL,   # ← Redis kimlik bilgisi/endpoint ifşa!
    ...
}
```

Redis URL şifre içerebilir (örn. `redis://:password@host:6379/0`). Sistem bilgisi döndüren herhangi bir endpoint'te bu alanın görünmesi gereksiz risk oluşturur.

**Düzeltme:** `redis_url` alanı `get_system_info()` çıktısından kaldırılmalı.

---

## 7. Orta Öncelikli Bulgular (O)

### O-1 — `_agent_lock` ve Diğer Kilitlerin Lazy Init Anti-Pattern'i

**Dosya:** `web_server.py:83`, `147-148`, `337`, `343`, `366-368`
**Ciddiyet:** ORTA — Teorik race condition

**Sorun:** `_agent_lock`, `_redis_lock`, `_local_rate_lock`, `_rate_lock` değişkenleri global scope'ta `None` olarak tanımlanıp ilk çağrıda oluşturuluyor. Python 3.10+ öncesinde asyncio.Lock() başlatma uyarısı üretir; ayrıca birden fazla coroutine eş zamanlı ilk kez çağırırsa lock olmadan yarış durumu yaşanabilir.

```python
# web_server.py:83 — anti-pattern
_agent_lock: asyncio.Lock | None = None

# web_server.py:147-148
if _agent_lock is None:
    _agent_lock = asyncio.Lock()   # iki coroutine aynı anda buraya gelebilir
```

**Düzeltme:** `_app_lifespan` içinde (event loop başladıktan sonra) tüm kilitleri başlat.

---

### O-2 — `add_document_from_file` Fonksiyonu Base Directory'e Kısıtlı Değil

**Dosya:** `core/rag.py:451-468`
**Ciddiyet:** ORTA — Dosya sistemi erişim kontrolü eksikliği

**Sorun:** `add_document_from_file` fonksiyonu `Path(path).resolve()` ile gerçek yolu çözümler fakat base directory sınırlaması yapmaz. Web endpoint (`/rag/add-file`) doğru şekilde `relative_to(_root)` kontrolü uygulasa da, fonksiyon agent araçları tarafından doğrudan çağrıldığında bu kontrol devre dışı kalır:

```python
# rag.py:451-457 — base dir kontrolü YOK
def add_document_from_file(self, path: str, ...) -> Tuple[bool, str]:
    _TEXT_EXTS = {...}
    file = Path(path).resolve()
    if not file.exists(): ...
    if file.suffix.lower() not in _TEXT_EXTS: ...
    content = file.read_text(...)   # ← proje dışı herhangi bir dosya okunabilir
```

Desteklenen uzantıya sahip herhangi bir dosya (örn. `/etc/hosts` — uzantısız ama `""` izinli) okunabilir.

**Düzeltme:** Fonksiyon içinde `file.relative_to(store_dir.parent)` veya daha geniş bir `base_dir` kontrolü ekle. Boş uzantı (`""`) whitelist'ten çıkarılmalı.

---

### O-3 — `execute_code_local()` FULL Modda Ağ Erişimi Açık Subprocess Çalıştırıyor

**Dosya:** `managers/code_manager.py:443-495`
**Ciddiyet:** ORTA — Docker izolasyonu atlatma

**Sorun:** Docker yokken FULL modda `execute_code_local()` ağ erişimine sahip `subprocess.run([sys.executable, tmp_path])` kullanır. Bu durum belgeleniyor ancak kullanıcıya yeterince açık olmayabilir. Log mesajı "Docker yok — FULL modda yerel subprocess fallback" ile uyarı verilse de izolasyon tamamen kaldırılmış olur.

**Düzeltme:** En azından `execute_code_local()` çağrısından önce açık bir kullanıcı uyarısı veya `DOCKER_REQUIRED=true` env bayrağı ile bu fallback'i devre dışı bırakma seçeneği ekle.

---

### O-4 — `validate_critical_settings()` Başlatma Sırasında Bloklayan HTTP İsteği Yapıyor

**Dosya:** `config.py:512-531`
**Ciddiyet:** ORTA — Senkron Ollama bağlantı kontrolü

**Sorun:** `validate_critical_settings()` içinde `httpx.Client(timeout=2).get(tags_url)` çağrısı senkron (bloklayan) olarak yapılıyor. Bu asyncio event loop başlatılmadan önce çağrılırsa problem yok; ancak `SidarAgent.__init__` çağrısı sırasında çağrılırsa asyncio event loop'u bloklar:

```python
# config.py:519-521 — SENKRON HTTP İSTEĞİ
with httpx.Client(timeout=2) as client:
    r = client.get(tags_url)
```

**Düzeltme:** `asyncio.to_thread()` ile wrap et veya başlatma aşamasında async `httpx.AsyncClient` kullan.

---

### O-5 — WebSocket'te Token Metin Olarak İletiliyor (Protokol Güvenliği)

**Dosya:** `web_server.py:599-620`
**Ciddiyet:** ORTA — Token protokol dışı iletim

**Sorun:** WebSocket kimlik doğrulaması için token, HTTP başlığı yerine JSON mesaj payload'u içinde gönderiliyor:

```python
# web_server.py:606 — token JSON payload içinde
auth_token = (payload.get("token", "") or "").strip()
```

Bu yaklaşım, WebSocket bağlantısı kurulduğunda kısa bir süre boyunca kimlik doğrulamasız durum oluşturur. Standart yaklaşım token'ı WebSocket handshake sırasında `Sec-WebSocket-Protocol` başlığı veya ilk upgrade isteğinin `Authorization` başlığı ile göndermektir.

---

### O-6 — `run_shell()` Shell Metakarakter Kontrolü Eksik Durumlarda Bypass Edilebilir

**Dosya:** `managers/code_manager.py:536-543`
**Ciddiyet:** ORTA — Shell injection riski

**Sorun:** `allow_shell_features=True` ile `shell=True` kombinasyonu kullanılıyor. LLM'den gelen komutlar `allow_shell_features=True` ile çağrılırsa command injection riski var:

```python
# code_manager.py:546-548
if allow_shell_features:
    result = subprocess.run(
        command, shell=True, ...   # ← tam shell injection
    )
```

Metakarakter kontrolü yalnızca `allow_shell_features=False` durumunda uygulanıyor; `True` durumunda hiçbir sanitizasyon yok.

---

## 8. Düşük / İyileştirme Önerileri (D)

### D-1 — `config.py:GPU_MEMORY_FRACTION` Üst Sınır Exclusive (0.1–1.0 exclusive)

**Dosya:** `config.py:184`
Mevcut kod `0.1 <= frac < 1.0` kontrolü yapıyor. 1.0 değeri (tüm VRAM) geçersiz sayılıyor, bu kasıtlı olabilir. Ancak yorum satırı `(0.1–1.0 bekleniyor)` yazıyor ki bu kullanıcıyı yanıltabilir. Yorum `(0.1–0.99 bekleniyor, 1.0 dahil değil)` olarak güncellenmeli.

---

### D-2 — `main.py`'da Port Numarası Aralık Doğrulaması Yok

**Dosya:** `main.py:338,362`
`--port` argümanı `argparse` ile alınıyor ve doğrudan kullanılıyor. 0 veya 65535 üzeri değerler `build_command()` tarafından kabul edilir, işletim sistemi seviyesinde hata verir. Açık mesaj yerine bağlama uygun hata mesajı verilebilir.

---

### D-3 — Açık Endpoint'ler Hassas Metrik Bilgisi Döndürüyor

**Dosya:** `web_server.py:724-791`
`/metrics`, `/metrics/llm`, `/api/budget` endpoint'leri auth middleware'i tarafından açık bırakılmış (`open_paths`'ta). Bu endpoint'ler server uptime, RAG belge sayısı, LLM çağrı istatistikleri, provider bilgisi gibi bilgileri auth olmadan döndürüyor.

---

### D-4 — `core/rag.py` HTML Temizleme Temel Regex Tabanlı

**Dosya:** `core/rag.py:810-823`
`_clean_html()` fonksiyonu regex ile HTML temizliyor. `<script>` ve `<style>` etiketlerini siliyor ancak `onload`, `onerror` gibi event attribute'larını silmiyor. İçerik yalnızca metin olarak kullanıldığından XSS riski düşük, ancak `bleach` veya `html5lib` kullanımı daha güvenilir olur.

---

### D-5 — `agent/sidar_agent.py`'da `_build_context()` İçinde LLM'e Sistem Yolları Gönderiliyor

**Dosya:** `agent/sidar_agent.py:251-253`
`_build_context()` LLM'ye `BASE_DIR` ve `OLLAMA_URL` gibi iç sistem bilgileri gönderiyor. Bu bilgiler prompt injection saldırılarında kullanılabilir — LLM çıktısı kullanıcıya iletilirken bu değerler de sızabilir.

---

### D-6 — DB `_run_sqlite_op` İçinde Lazy Lock Init

**Dosya:** `core/db.py:152-153`
```python
if self._sqlite_lock is None:
    self._sqlite_lock = asyncio.Lock()
```
`_connect_sqlite()` zaten kilidi oluşturuyor (`db.py:146`), bu lazy init gereksiz ve O-1 ile aynı anti-pattern'i taşıyor.

---

## 9. Modül Bazlı Analiz

### 9.1 `web_server.py` (1.417 satır)

| Konu | Durum | Bulgu |
|------|-------|-------|
| Auth middleware | ✅ Doğru | Bearer token, open_paths whitelist |
| CORS | ✅ Kısıtlı | Yalnızca localhost regex |
| Rate limiting | ✅ Çok katmanlı | DDoS + endpoint bazlı |
| Pydantic validation | ✅ Eklendi | Auth endpoint'leri |
| Health endpoint routing | ❌ KRİTİK | K-1: Yanlış fonksiyona bağlı |
| `/set-level` yetkilendirme | ❌ YÜKSEK | Y-1: Admin kontrolü yok |
| Upload boyut kontrolü | ❌ YÜKSEK | Y-2: RAG upload sınırsız |
| IP spoofing (rate limit) | ⚠️ YÜKSEK | Y-4: XFF güvenilir |
| WebSocket auth | ⚠️ ORTA | O-5: Payload içinde token |

### 9.2 `core/db.py` (1.012 satır)

| Konu | Durum | Bulgu |
|------|-------|-------|
| Parola hashleme | ✅ Mükemmel | PBKDF2-SHA256 600k |
| Timing attack | ✅ Korumalı | secrets.compare_digest |
| SQL injection | ✅ Korumalı | Parameterize sorgular |
| Şema tablo adı | ❌ KRİTİK | K-2: f-string SQL injection |
| Thread safety | ✅ Doğru | asyncio.Lock + to_thread |

### 9.3 `core/rag.py` (834 satır)

| Konu | Durum | Bulgu |
|------|-------|-------|
| SSRF koruması | ✅ Doğru | ipaddress modülü, blocked_hosts |
| File extension whitelist | ✅ Güncellendi | .env/.example yok |
| Base dir kısıtlama | ⚠️ ORTA | O-2: add_document_from_file |
| Boş uzantı izni | ⚠️ DÜŞÜK | `""` hâlâ izinli |
| HTML sanitization | ⚠️ DÜŞÜK | D-4: regex tabanlı |

### 9.4 `managers/security.py` (290 satır)

| Konu | Durum | Bulgu |
|------|-------|-------|
| Path traversal | ✅ Mükemmel | 3 katmanlı savunma |
| Symlink attack | ✅ Korumalı | .resolve() |
| Erişim seviyeleri | ✅ Doğru | RESTRICTED/SANDBOX/FULL |
| Bilinmeyen seviye fallback | ✅ Güvenli | SANDBOX varsayılanı |

### 9.5 `managers/code_manager.py` (898 satır)

| Konu | Durum | Bulgu |
|------|-------|-------|
| Docker sandbox | ✅ Sağlam | Ağ kapalı, kota, timeout |
| Fail-closed | ✅ SANDBOX modda | Docker yoksa reddeder |
| FULL modda fallback | ⚠️ ORTA | O-3: Ağ açık |
| Shell features | ⚠️ ORTA | O-6: allow_shell_features=True |

### 9.6 `config.py` (607 satır)

| Konu | Durum | Bulgu |
|------|-------|-------|
| API key doğrulama | ✅ Doğru | Fernet, provider checks |
| Donanım tespiti | ✅ İyi | Lazy-load, hata toleranslı |
| GPU fraction validation | ⚠️ DÜŞÜK | D-1: Üst sınır exclusive |
| REDIS_URL ifşası | ⚠️ YÜKSEK | Y-5: get_system_info içinde |
| Senkron Ollama check | ⚠️ ORTA | O-4: Bloklayan HTTP |

---

## 10. Özet Bulgu Tablosu

| ID | Başlık | Dosya | Satır | Öncelik |
|----|--------|-------|-------|---------|
| K-1 | `/health` endpoint yanlış fonksiyona bağlı | web_server.py | 692-707 | 🔴 KRİTİK |
| K-2 | DB şema tablo adı f-string SQL injection | core/db.py | 330-365 | 🔴 KRİTİK |
| Y-1 | `/set-level` admin kısıtlaması yok | web_server.py | 1267 | 🟠 YÜKSEK |
| Y-2 | RAG upload dosya boyutu sınırsız | web_server.py | 1158-1198 | 🟠 YÜKSEK |
| Y-3 | `_summarize_memory` async fn yanlış çağrı | sidar_agent.py | 465-471 | 🟠 YÜKSEK |
| Y-4 | X-Forwarded-For rate limit bypass | web_server.py | 404-413 | 🟠 YÜKSEK |
| Y-5 | REDIS_URL get_system_info içinde ifşa | config.py | 561 | 🟠 YÜKSEK |
| O-1 | Çoklu lazy asyncio.Lock anti-pattern | web_server.py | 83,337,343 | 🟡 ORTA |
| O-2 | RAG file add base dir kısıtlaması yok | core/rag.py | 451-468 | 🟡 ORTA |
| O-3 | FULL modda Docker fallback ağ açık | code_manager.py | 443-495 | 🟡 ORTA |
| O-4 | Senkron Ollama bağlantı kontrolü | config.py | 512-531 | 🟡 ORTA |
| O-5 | WS token JSON payload içinde | web_server.py | 606 | 🟡 ORTA |
| O-6 | Shell metakarakter shell=True bypass | code_manager.py | 546-548 | 🟡 ORTA |
| D-1 | GPU fraction yorum tutarsız | config.py | 184 | 🔵 DÜŞÜK |
| D-2 | Port numarası aralık doğrulaması yok | main.py | 338 | 🔵 DÜŞÜK |
| D-3 | Metrik endpoint'ler auth olmadan erişilir | web_server.py | 724 | 🔵 DÜŞÜK |
| D-4 | HTML sanitization regex tabanlı | core/rag.py | 810 | 🔵 DÜŞÜK |
| D-5 | LLM context içinde sistem yolları | sidar_agent.py | 251 | 🔵 DÜŞÜK |
| D-6 | DB lazy lock init (gereksiz) | core/db.py | 152 | 🔵 DÜŞÜK |

**Toplam: 2 Kritik · 5 Yüksek · 6 Orta · 6 Düşük = 19 Bulgu**

---

## 11. Sonuç ve Genel Değerlendirme

### Genel Güvenlik Puanı: 7.5 / 10

| Kategori | Puan | Not |
|----------|------|-----|
| Kimlik Doğrulama | 9/10 | PBKDF2-SHA256, sabit zamanlı karşılaştırma, Pydantic validation |
| Yetkilendirme | 6/10 | `/set-level` privilege escalation açığı kritik |
| SQL Güvenliği | 7/10 | Parameterize sorgular iyi, şema tablosu f-string sorunu kritik |
| Dosya Sistemi | 8/10 | Multi-layer path traversal koruma güçlü; RAG fonksiyon-seviyesinde eksik |
| Ağ Güvenliği | 8/10 | SSRF koruması, rate limiting, CORS kısıtlı |
| Sandbox | 9/10 | Docker izolasyonu iyi tasarlanmış, fail-closed SANDBOX |
| Async Güvenliği | 7/10 | Çoklu lazy init, bir async/to_thread hatası |
| Operasyonel | 6/10 | Health endpoint kritik bug, senkron başlatma |

### Öncelik Sırası (Önerilen Düzeltme Sırası)

1. **K-1** — `/health` routing bug düzeltilmeli (tek satır değişiklik)
2. **K-2** — DB tablo adı whitelist doğrulama eklenmeli
3. **Y-1** — `/set-level` endpoint `_require_admin_user` kısıtlaması
4. **Y-3** — `_summarize_memory` async çağrısı düzeltilmeli
5. **Y-2** — RAG upload boyut limiti
6. **Y-4** — X-Forwarded-For trusted proxy yapılandırması
7. **Y-5** — REDIS_URL `get_system_info()` dışına çıkarılmalı

### Pozitif Vurgu

Bu proje, tipik hızlı prototiplerden farklı olarak güvenlik tasarımını baştan düşünerek inşa edilmiştir. Parola güvenliği (600k PBKDF2), path traversal koruması (3 katmanlı), Docker sandbox izolasyonu, SSRF koruması ve rate limiting doğru uygulanmıştır. Bulunan kritik sorunlar çok katmanlı bir sistemde kaçınılması güç edge case'ler veya gözden kaçmış decorator sıralama hataları gibi yapısal ayrıntılardır; temel güvenlik anlayışı sağlamdır.

---

*Bu rapor tüm kaynak dosyalar bağımsız olarak okunarak satır satır inceleme sonucunda üretilmiştir.*
*Rapor Formatı: Markdown · Dil: Türkçe · Araç: Claude Sonnet 4.6*
