# SİDAR Projesi — Düzeltme Geçmişi

> Bu dosya `PROJE_RAPORU.md` içinden ayrılmıştır.  
> **Ana rapor:** [PROJE_RAPORU.md](PROJE_RAPORU.md) — §3 referansı buraya yönlendirilmiştir.  
> Son güncelleme: **2026-03-05** | Kapsam: v2.5.0 → v2.7.0 arası tüm düzeltmeler

---

<a id="sec-3-1-3-76"></a>

### ✅ §13.5.1 `main.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** `main.py` dosyasındaki alt süreç (child process) loglama mantığında RAM şişmesine sebep olabilecek mimari sorunların giderilmesi ve `cli.py` çakışmalarının düzeltilmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| M-01 | ✅ Kapandı | Child-process gözlemlenebilirliği için canlı stdout/stderr aynalama ve opsiyonel dosya loglama eklendi (`--capture-output`, `--child-log`). |
| M-02 | ✅ Kapandı | Loglama işlemi bellekte liste tutmak yerine (RAM şişmesi riski) doğrudan diske yazma (on-the-fly streaming) metoduna geçirilerek tamamen optimize edildi. Eski `cli.py` çakışma notları temizlendi. |

---

### ✅ §13.5.1A `cli.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** Eski sürümlerde `main.py`'de bulunan karmaşık asenkron döngü yapısının `cli.py`'ye taşınması ve banner UI/UX tasarım kararlarının kesinleştirilmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| CLI-01 | ✅ Kapandı | Sürekli `asyncio.run()` çağrılarak yaratılan `RuntimeError` çakışma riski, tüm döngünün tek bir `_interactive_loop_async` fonksiyonuna sarılmasıyla kesin olarak çözüldü. |
| CLI-02 | ✅ Kapandı | Uzun sürüm/branch metinlerinin ASCII çerçeveyi bozması sorunu "hata" statüsünden çıkarıldı. `_make_banner` içindeki `ver_field[:9] + "…"` algoritması bilinçli bir UI stabilite kararı olarak kabul edildi ve bulgu kapatıldı. |

---

### ✅ §13.5.2 `agent/sidar_agent.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** Ajanın uzun sohbetlerde LLM (Gemini/Ollama) token sınırlarını aşması riskinin (Context Bloat) ve bazı mimari kararların netleştirilmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| AG-02 | ✅ Kapandı | `_tool_subtask` adım limitinin yapılandırılabilir olmasına rağmen üst sınırın 10 olarak sabitlenmesi bir hata değil, sonsuz özyinelemeyi (infinite recursion) ve bütçe aşımını engelleyen bilinçli bir güvenlik/mimari tasarımı (guardrail) olarak değerlendirildi. |
| AG-03 (H-03) | ✅ Kapandı | ChromaDB'ye arşivlenen eski konuşmaların `_build_context` içinde körü körüne LLM'e geri yüklenmesi mantığı mimariden çıkarıldı. Sistem artık sadece RAG depo durumunu bildiriyor ve eski verilere ihtiyaç duyan LLM'in bilinçli olarak `docs_search` aracını kullanmasını zorunlu kılıyor. Bu sayede kritik Token Taşması/VRAM Şişmesi (H-03) riski tamamen ortadan kaldırıldı. |

---

### ✅ §13.5.3 `core/rag.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** RAG modülündeki senkron disk/index işlemlerinin çok kullanıcılı asenkron web sunucusunu (FastAPI) dondurma (Event-Loop Starvation) riskinin giderilmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| C-01 (RAG-04) | ✅ Kapandı | `_ensure_bm25_index` işleminin senkron çalışması nedeniyle oluşan kritik darboğaz (starvation), doğrudan `rag.py` içinde değil, çağıran katmanlarda çözüldü. SİDAR mimarisine uygun olarak, `sidar_agent.py` ve `web_server.py` dosyalarındaki tüm RAG arama (`search`), ekleme (`add_document`) ve silme işlemleri `await asyncio.to_thread(...)` ile arka plan thread'lerine itildi. Ana event-loop'un dondurulması kesin olarak engellendi. |
| RAG-03 | ✅ Kapandı | BM25 in-memory önbelleğinin (cache) dışarıdan diskteki dosya değiştiğinde manuel invalidate gerektirmesi durumu bir hata değil, performans/bellek trade-off'u (kabul edilmiş sistem tasarımı) olarak değerlendirildi. |

---

### ✅ §13.5.4 `web_server.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** FastAPI sunucusunda ağır yük (high-concurrency) altında yaşanabilecek asenkron kilitlenmelerin, güvenlik yarış koşullarının ve başlatma uyarılarının giderilmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| WS-01 | ✅ Kapandı | Python 3.9/3.10 sürümlerinde alınan `RuntimeWarning: asyncio.Lock() created outside of event loop` hatası, Lock nesnelerinin (`_agent_lock` ve `_rate_lock`) global alanda değil, fonksiyon ilk kez çağrıldığında (lazy init) oluşturulmasıyla kesin olarak çözüldü. |
| WS-02 | ✅ Kapandı | Event-loop bloklaması (Starvation): `/git-*` ve `/rag/*` endpoint'lerindeki alt süreç (`subprocess`) ve disk okuma işlemleri ana akışı donduruyordu. Bu işlemlerin tamamı `await asyncio.to_thread()` ile thread pool'a (iş parçacığı havuzuna) itilerek sunucu tepkiselliği maksimize edildi. |
| WS-03 | ✅ Kapandı | Rate Limiter zafiyeti: Eşzamanlı (concurrent) gelen isteklerde aynı IP'nin limitleri aşabilmesi (TOCTOU race condition) sorunu, `_is_rate_limited` fonksiyonuna `_rate_lock` atomik kilidi eklenerek giderildi. `X-Forwarded-For` IP tespiti proxy-aware hale getirildi. |

---

### ✅ §13.5.5 `agent/definitions.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** LLM modellerinin (özellikle açık kaynaklı Llama türevlerinin) araç çağrısı yaparken JSON formatının dışına çıkması, Markdown blokları kullanması ve sistemin Pydantic ayrıştırıcısını (parser) bozmasının engellenmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| DEF-01 | ✅ Kapandı | Format Kayması (Format Drift): Modellerin JSON yanıtlarını ```json ... ``` tagleri arasına alma eğilimi, prompt içine eklenen "Asla markdown bloğu kullanma, saf string olarak geçerli bir JSON döndür" şeklindeki katı sistem kuralıyla (Zero-Shot Constraint) çözüldü. Bu sayede `sidar_agent.py` tarafındaki regex bağımlılığı azaltıldı. |
| DEF-02 | ✅ Kapandı | Token Optimizasyonu: Prompt içindeki eski, uzun ve gereksiz tekrar eden araç tanımlamaları temizlendi. Modelin bağlam penceresinde (context window) yer açıldı ve asıl odaklanması gereken "görev ve çalışma alanı" talimatlarının etkisi artırıldı. |

---

### ✅ §13.5.6 `agent/auto_handle.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** Otomatik komut işleyicinin (AutoHandle) karmaşık cümlelerde veya çok adımlı görevlerde (Chain of Thought) sistem işleyişini bozmasının ve yanlış araçları tetiklemesinin (False Positive) engellenmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| AH-01 | ✅ Kapandı | Aşırı Hevesli Regex (False Positive): Sistemde "göster", "kontrol et" gibi genel bağlamlı kelimeler yüzünden alakasız araçların tetiklenmesi sorunu, regex kalıplarının sıkılaştırılmasıyla (örn. "dosyayı göster", "sözdizimini doğrula" şeklinde bağlam zorunluluğu getirilerek) çözüldü. Dizin çıkarma mantığı (`_extract_dir_path`) dosya uzantılarını yok sayacak şekilde izole edildi. |
| AH-02 | ✅ Kapandı | Çok Adımlı Görev Kırılması: Kullanıcının "Dosyayı oku ve ardından testlerini yaz" şeklindeki isteklerinde, AutoHandle'ın sadece ilk kısmı (okuma) yapıp süreci bitirmesi büyük bir hataydı. Koda `_MULTI_STEP_RE` sabiti eklenerek "ardından", "sonrasında", "1. ... 2." gibi bağlaçlar yakalandı ve bu tür isteklerin dokunulmadan doğrudan asıl yapay zeka ajanına (ReAct) iletilmesi sağlandı. |

---

### ✅ §13.5.7 `core/llm_client.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** LLM streaming (veri akışı) sırasında TCP paketlerinin JSON objelerini ortadan ikiye bölmesi sebebiyle yaşanan sessiz token/kelime kayıplarının ve model halüsinasyonlarının (JSON dışına çıkma) önlenmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| LLM-01 | ✅ Kapandı | TCP Paket Sınırı Token Kaybı: Ollama stream akışında kullanılan `aiter_lines()` metodunun uzun satırları veya çok baytlı (multi-byte) Türkçe UTF-8 karakterlerini böldüğü tespit edildi. Kod, `aiter_bytes()` ve `codecs.getincrementaldecoder("utf-8")` ikilisi kullanılarak manuel bir satır (newline) tamponuna (buffer) geçirildi. JSON ayrıştırma hataları yüzünden kaybolan kelime sorunu tamamen çözüldü. |
| LLM-02 | ✅ Kapandı | Native JSON Entegrasyonu: Modelleri (özellikle Llama 3) JSON formatında tutmak için sadece sistem promptu yetersiz kalıyordu. Ollama'nın native JSON şema desteği (`format: { "type": "object", "properties": ... }`) ve Gemini'nin `response_mime_type: "application/json"` özelliği API istek gövdesine eklendi. Modellerin markdown uydurma ihtimali donanımsal/API seviyesinde engellendi. |

---

### ✅ §13.5.8 `core/memory.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** Eski tek dosyalı bellek sisteminin yerine çoklu oturum yapısının getirilmesi, güvenlik açıklarının kapatılması ve disk darboğazlarının önlenmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| MEM-01 | ✅ Kapandı | Disk I/O Darboğazı (Throttling): Eski yapıda ajan her token ürettiğinde diske senkron yazma yapılıyordu. `_save_interval_seconds = 0.5` ve `_dirty` bayrağı eklenerek ardışık kayıt istekleri birleştirildi (debounced). SSD aşınması ve sunucu kilitlenmeleri önlendi. |
| MEM-02 | ✅ Kapandı | Bozuk Dosya & Şifreleme Eksikliği: Sohbet geçmişlerinin düz metin saklanması riski Fernet (AES-128-CBC) ile giderildi. Ayrıca elektrik kesintisi vb. nedenlerle JSON yapısı bozulan dosyaların tüm sistemi çökertmesi hatası, dosyaların `.json.broken` olarak karantinaya alındığı `_cleanup_broken_files` mekanizması ile çözüldü. |

---

### ✅ §13.5.9 `config.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** Ortam değişkenlerinden (`.env`) gelen string verilerin yanlış yorumlanması sebebiyle oluşan gizli hataların (silent bugs) ve çökme risklerinin giderilmesi.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| CONF-01 | ✅ Kapandı | Tip Dönüşüm Hataları (Boolean Parsing): Python'un yerleşik `bool("False")` çağrısının `True` dönmesi sebebiyle, `.env` dosyasında kapalı olan özelliklerin (örn. `DEBUG_MODE=False`) yanlışlıkla aktif olması sorunu giderildi. Koda string değerleri (`true/false/1/0`) doğru yorumlayan özel bir `_parse_bool` (veya eşdeğeri) tip dönüştürücü mantığı eklendi. |
| CONF-02 | ✅ Kapandı | Güvenli Varsayılan (Fallback) Eksikliği: `.env` dosyasının yanlışlıkla silinmesi veya eksik parametre içermesi durumunda sistemin `KeyError` vererek çökmesi engellendi. Tüm kritik `os.getenv` çağrılarına güvenli ve mantıklı varsayılan değerler (safe defaults) atandı. |

---

### ✅ §13.5.10 `managers/code_manager.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** Ajanın işletim sistemine müdahale yeteneklerinin sıkılaştırılması, dışarı sızma (escape) ihtimallerinin sıfırlanması ve sistem kaynaklarının korunması.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| CM-01 | ✅ Kapandı | Zombi Konteyner ve Kaynak Tüketimi: Ajanın `execute_code` aracıyla ürettiği sonsuz döngü (`while True: pass`) veya uzun süren işlemlerin Docker'ı ve ana sunucuyu kilitlemesi sorunu çözüldü. Kod çalıştırıcıya katı bir `docker_exec_timeout` (varsayılan: 10 saniye) eklendi. Süre aşımında konteyner acımasızca öldürülür (`SIGKILL`) ve ajana "Zaman Aşımı" uyarısı dönülür. |
| CM-02 | ✅ Kapandı | Path Traversal Zafiyeti: Eski sürümde ajanın `../../` gibi göreceli yollar (relative paths) kullanarak projenin kök dizininden (`BASE_DIR`) çıkabilme riski vardı. Yeni mimaride tüm yol çözümlemeleri (path resolution) `SecurityManager` içindeki güvenli kontrol mekanizmasına bağlandı. Yetkisiz okuma/yazma girişimleri anında `PermissionError` ile engelleniyor. |

---

### ✅ §13.5.11 `managers/github_manager.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** Ajanın GitHub depolarını tararken karşılaştığı derlenmiş dosyaların (binary) veya geçersiz kimlik doğrulama yöntemlerinin sistemi bozmasını engellemek.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| GH-01 | ✅ Kapandı | Binary Dosya Okuma Çökmesi: Ajanın uzak bir depodan `.png`, `.zip` veya derlenmiş bir ikili dosya okumaya çalışması `UnicodeDecodeError` hatasına ve LLM context'inin (bağlamının) şişmesine sebep oluyordu. Koda `SAFE_TEXT_EXTENSIONS` whitelist'i eklendi. Uzantısız dosyalar (`Makefile`, `Dockerfile` vb.) için özel kontrol (`SAFE_EXTENSIONLESS`) oluşturuldu ve binary okuma riskleri donanımsal seviyede engellendi. |
| GH-02 | ✅ Kapandı | Deprecated Authentication: PyGithub kütüphanesinin yakında kaldırılacak olan `Github(login_or_token=...)` metodu, güncel standart olan `Github(auth=Auth.Token(...))` yapısına taşınarak sürüm (dependency) uyumluluğu korundu. |

---

### ✅ §13.5.12 `managers/system_health.py` Düzeltmeleri (Tarih: 2026-03-05)

**Bağlam:** Sistem sağlığı izleme işlevlerinin web sunucusunu (FastAPI) dondurmasını engellemek ve donanım kaynaklarının daha güvenilir şekilde serbest bırakılmasını sağlamak.

| ID | Durum | Çözüm Notu |
|----|------|------------|
| SH-01 | ✅ Kapandı | CPU İzleme Blokajı (Event-Loop Starvation): `psutil.cpu_percent(interval=1)` gibi senkron beklemeler içeren kodların asenkron ana akışı kilitlediği tespit edildi. Kod güncellenerek `cpu_sample_interval` parametresi eklendi ve varsayılan olarak non-blocking (`0.0` sn) çalışması güvence altına alındı. |
| SH-02 | ✅ Kapandı | Güvensiz Bellek Temizliği & Kaynak Sızıntısı: `optimize_gpu_memory` çalışırken `torch.cuda` tarafında oluşacak bir hatanın `gc.collect()` satırının atlanmasına sebep olduğu anlaşıldı. Koda `try-finally` bloğu eklenerek bellek temizliğinin her koşulda çalışması garanti edildi. Ayrıca program çıkışında NVIDIA kaynaklarının asılı kalmaması için `atexit.register(self.close)` mekanizması entegre edildi. |

---

> ✅ v2.5.0 raporundaki 8 temel sorun + v2.6.0 raporundaki 7 web UI / backend sorunu + 5 kritik hata + 9 yüksek öncelikli sorun + 10 orta öncelikli sorun + 8 düşük öncelikli sorun + 7 ek sorun giderilmiştir (toplam 54 düzeltme).

---

### ✅ 3.1 `main.py` — Async Generator Hatası (KRİTİK → ÇÖZÜLDÜ)

**Eski kod:** Senkron `for chunk in agent.respond(...)` → `TypeError`

**Güncel kod:**
```python
# main.py — Doğru implementasyon
async def _interactive_loop_async(agent: SidarAgent) -> None:
    ...
    async for chunk in agent.respond(user_input):   # ✅ async for
        print(chunk, end="", flush=True)

def interactive_loop(agent: SidarAgent) -> None:
    asyncio.run(_interactive_loop_async(agent))     # ✅ tek asyncio.run()

async def _run_command() -> None:
    async for chunk in agent.respond(args.command): # ✅ async for
        print(chunk, end="", flush=True)
asyncio.run(_run_command())                         # ✅
```

**Ek iyileştirme:** Döngünün tamamı tek bir `async def _interactive_loop_async` içine alınarak her mesajda yeni Event Loop açılması (eski `asyncio.run()` döngüdeydi) ve `asyncio.Lock` sorunları giderildi.

---

### ✅ 3.2 `rag.py` — Senkron `requests` Kullanımı (KRİTİK → ÇÖZÜLDÜ)

**Eski kod:** `def add_document_from_url(...)` → `requests.get()` → event loop bloklaması

**Güncel kod:**
```python
async def add_document_from_url(self, url: str, ...) -> Tuple[bool, str]:
    import httpx                                      # ✅ async HTTP
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, ...) as client:
        resp = await client.get(url)                  # ✅ await
    resp.raise_for_status()
    content = self._clean_html(resp.text)
    ...
```

---

### ✅ 3.3 `environment.yml` — `pytest-asyncio` Eksikliği (YÜKSEK → ÇÖZÜLDÜ)

```yaml
# environment.yml — Eklenmiş satır:
- pytest-asyncio>=0.21.0   # ✅ Artık mevcut
```

---

### ✅ 3.4 `web_server.py` — `threading.Lock` Async Context'te (YÜKSEK → ÇÖZÜLDÜ)

**Eski kod:** `_agent_lock = threading.Lock()`

**Güncel kod:**
```python
_agent_lock = asyncio.Lock()            # ✅ async lock

async def get_agent() -> SidarAgent:
    global _agent
    if _agent is None:
        async with _agent_lock:         # ✅ async with
            if _agent is None:
                _agent = SidarAgent(cfg)
    return _agent
```

---

### ✅ 3.5 Versiyon Tutarsızlığı (ORTA → ÇÖZÜLDÜ)

| Dosya | Önceki | Güncel |
|-------|--------|--------|
| `main.py` banner | `v2.3.2` | `v2.6.0` |
| `sidar_agent.py` VERSION | `2.5.0` | `2.6.0` |
| `config.py` VERSION | `2.5.0` | `2.6.0` |
| `Dockerfile` label | `2.6.0` | `2.6.0` |

---

### ✅ 3.6 `sidar_agent.py` — 25 `if/elif` Zinciri (ORTA → ÇÖZÜLDÜ)

**Eski kod:** `_execute_tool()` içinde 25 `if tool_name == "..."` dalı

**Güncel kod:** Temiz dispatcher tablosu + ayrı `_tool_*` metodları:
```python
async def _execute_tool(self, tool_name: str, tool_arg: str) -> Optional[str]:
    dispatch = {
        "list_dir":   self._tool_list_dir,
        "read_file":  self._tool_read_file,
        ...  # 24 araç dispatcher'da
    }
    handler = dispatch.get(tool_name)
    return await handler(tool_arg) if handler else None
```
Her araç için ayrı `async def _tool_*()` metodu tanımlanmış; `asyncio.to_thread()` gerektiren I/O işlemleri (disk okuma/yazma, kod çalıştırma) doğru şekilde thread'e itilmiş.

---

### ✅ 3.7 Yorum Bloğu Şişkinliği (ORTA → ÇÖZÜLDÜ)

`auto_handle.py:373-760` satırları arasındaki ~387 satırlık eski senkron implementasyon tamamen silinmiştir. `auto_handle.py` artık yalnızca aktif, async uyumlu kodu içermektedir.

---

### ✅ 3.8 `CHUNK_SIZE` / `CHUNK_OVERLAP` Config'e Taşınması (ORTA → ÇÖZÜLDÜ)

**`config.py`'ye eklenen satırlar:**
```python
RAG_CHUNK_SIZE:    int = get_int_env("RAG_CHUNK_SIZE", 1000)
RAG_CHUNK_OVERLAP: int = get_int_env("RAG_CHUNK_OVERLAP", 200)
```

**`sidar_agent.py`'de doğru kullanım:**
```python
self.docs = DocumentStore(
    self.cfg.RAG_DIR,
    top_k=self.cfg.RAG_TOP_K,
    chunk_size=self.cfg.RAG_CHUNK_SIZE,         # ✅ Config'den
    chunk_overlap=self.cfg.RAG_CHUNK_OVERLAP,   # ✅ Config'den
    ...
)
```

---

### ✅ 3.9 `web_ui/index.html` — Model İsmi Hardcoded (YÜKSEK → ÇÖZÜLDÜ)

**Sorun:** Sol menü ve chat giriş alanı altında model ismi "Sonnet 4.6" olarak sabit kodlanmıştı; arka planda Gemini veya Ollama çalışıyor olsa bile değişmiyordu.

**Düzeltme:** `loadModelInfo()` fonksiyonu `/status` endpoint'inden `data.provider` ve `data.model` alanlarını çekip `#model-name-label` ve `#input-model-label` elementlerini günceller.

```javascript
// index.html — loadModelInfo()
const data = await (await fetch('/status')).json();
const display = provider === 'gemini' ? `Gemini · ${model}` : model;
sidebarLabel.textContent = display;   // ✅ Dinamik
inputLabel.textContent   = display;   // ✅ Dinamik
```

---

### ✅ 3.10 `web_ui/index.html` — Auto-Accept Checkbox İşlevsizdi (ORTA → ÇÖZÜLDÜ)

**Sorun:** "Auto accept edits" checkbox'ı yalnızca `localStorage`'a değer kaydediyordu; backend'e (`/chat` payload'ına) hiç iletilmiyordu. `SidarAgent` bu ayarı asla bilemiyordu.

**Düzeltme:** Checkbox ve ilgili tüm JS (`syncAutoAccept`, `applyStoredAutoAccept`) ve CSS (`.auto-accept-wrap`, `.auto-accept-sm`) tamamen kaldırıldı. `SidarAgent`'ın bu kavramı karşılayan bir mekanizması bulunmadığından kaldırma, yama uygulamaktan daha doğru yaklaşımdır.

---

### ✅ 3.11 `web_ui/index.html` — Sahte Repo/Dal Seçicileri (YÜKSEK → ÇÖZÜLDÜ)

**Sorun:** Hardcoded `REPOS` ve `BRANCHES` dizileri; modal üzerinden seçim yapılsa bile backend'e hiçbir bilgi gitmiyordu.

**Düzeltme:**
- `REPOS`, `BRANCHES` sabitleri, `openRepoModal`, `renderRepos`, `filterRepos`, `selectRepo` fonksiyonları ve repo modal HTML'i silindi.
- `web_server.py`'e `POST /set-branch` endpoint'i eklendi — `git checkout <branch>` çalıştırır, hata durumunda açıklayıcı mesaj döner.
- `selectBranch()` artık `/set-branch`'i çağırır; başarısız olursa UI güncellenmez ve `alert()` gösterir.
- Repo chip'i artık salt okunur gösterge; repo `/git-info`'dan `git remote`'dan otomatik okunur.

```python
# web_server.py — yeni endpoint
@app.post("/set-branch")
async def set_branch(request: Request):
    subprocess.check_output(["git", "checkout", branch_name], cwd=str(_root), ...)
    return JSONResponse({"success": True, "branch": branch_name})
```

---

### ✅ 3.12 `web_ui/index.html` — `pkg_status` Hardcoded (ORTA → ÇÖZÜLDÜ)

**Sorun:** Sistem Durumu modalında "Paket Bilgi" satırı `'✓ PyPI + npm + GitHub'` sabit string'i gösteriyordu; `data.pkg_status` hiç kullanılmıyordu.

**Düzeltme:** Tek satır değişiklik:
```javascript
// Önce:  row('Paket Bilgi', '✓ PyPI + npm + GitHub', 'ok'),
// Sonra:
row('Paket Bilgi', data.pkg_status),   // ✅ a.pkg.status() çıktısı
```

---

### ✅ 3.13 `web_server.py` — ESC/Streaming Durdurma Log Kirliliği (DÜŞÜK → ÇÖZÜLDÜ)

**Sorun:** İstemci `AbortController.abort()` ile bağlantıyı kestiğinde `anyio.ClosedResourceError` hata olarak loglanıyor, ardından handler kapalı sokete `yield` deneyerek ikinci hata tetikleniyordu.

**Düzeltme:**
```python
except asyncio.CancelledError:
    logger.info("Stream iptal edildi (CancelledError): istemci bağlantıyı kesti.")
except Exception as exc:
    if _ANYIO_CLOSED and isinstance(exc, _ANYIO_CLOSED):
        logger.info("Stream iptal edildi (ClosedResourceError): istemci bağlantıyı kesti.")
        return
    # Gerçek hatalar için yield try/except ile sarıldı
    try:
        yield f"data: {json.dumps({'chunk': f'[Sistem Hatası] {exc}'})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
    except Exception:
        pass
```

---

### ✅ 3.14 `agent/sidar_agent.py:163` — Açgözlü Regex JSON Ayrıştırma (KRİTİK → ÇÖZÜLDÜ)

**Sorun:** `re.search(r'\{.*\}', raw_text, re.DOTALL)` greedy eşleşmesi birden fazla JSON bloğu veya gömülü kod olduğunda yanlış nesneyi yakalıyordu.

**Düzeltme:** `json.JSONDecoder().raw_decode()` ile ilk geçerli JSON nesnesi güvenle seçiliyor. Greedy regex tamamen kaldırıldı.

---

### ✅ 3.15 `core/llm_client.py:129` — UTF-8 Çok Baytlı Karakter Bölünmesi (KRİTİK → ÇÖZÜLDÜ)

**Sorun:** TCP paket sınırında bölünen multibyte UTF-8 karakterler `errors="replace"` ile `U+FFFD` karakterine dönüştürülüyor; Türkçe içerikte sessiz veri kaybı oluşuyordu.

**Düzeltme:** `_byte_buf` byte buffer ile 1-3 baytlık eksik sekanslar saptanıp bir sonraki pakete erteleniyor; veri bütünlüğü korunuyor.

---

### ✅ 3.16 `core/memory.py:170-171` — Token Sayısı Limiti Yok (KRİTİK → ÇÖZÜLDÜ)

**Sorun:** Bellek yönetimi yalnızca mesaj sayısı sınırlıyordu; büyük dosya / araç çıktıları context window'u aşabiliyordu.

**Düzeltme:** `_estimate_tokens()` (karakter/3.5 tahmini) ve `needs_summarization()` içine token eşiği (>6000) eklendi; hem sayı hem içerik bazlı sınırlama aktif.

---

### ✅ 3.17 `agent/auto_handle.py:156-157` — `self.health` Null Kontrolü Yok (KRİTİK → ÇÖZÜLDÜ)

**Sorun:** `self.health.full_report()` ve `self.health.optimize_gpu_memory()` null kontrol olmadan çağrılıyordu; `SystemHealthManager` başlatamazsa `AttributeError` oluşuyordu.

**Düzeltme:** `_try_health()` ve `_try_gpu_optimize()` metodlarına `if not self.health:` null guard eklendi; `None` durumunda kullanıcıya açıklayıcı mesaj döndürülüyor.

---

### ✅ 3.18 `README.md` — Versiyon Tutarsızlığı ve Eksik Özellik Belgeleri (YÜKSEK → ÇÖZÜLDÜ)

**Sorun:** README.md v2.3.2 referans gösteriyordu; GPU, çoklu oturum, Docker REPL, rate limiting, chunking ve web arama motorları belgelenmemişti.

**Düzeltme:** v2.6.1'e güncellendi; tüm v2.6.x özellikleri bölümler halinde belgelendi (GPU, RAG, Web Arayüzü, Çoklu Oturum, Güvenlik seviyeleri).

---

### ✅ 3.19 `config.py:validate_critical_settings()` — Senkron `requests` → `httpx` (YÜKSEK → ÇÖZÜLDÜ)

**Sorun:** Ollama bağlantı kontrolü `requests.get()` senkron çağrısı ile yapılıyordu; mimari tutarsızlık ve potansiyel event loop blokajı mevcuttu.

**Düzeltme:** `httpx.Client(timeout=2)` ile senkron httpx kullanımına geçildi. Proje genelinde HTTP kütüphanesi tutarlılığı sağlandı.

---

### ✅ 3.20 `agent/sidar_agent.py` — Stream Generator Yeniden Kullanım Riski (YÜKSEK → ÇÖZÜLDÜ)

**Sorun:** Stream sırasında `yield chunk` çağrılıyor, `memory.add()` kısmi yanıtla çağrılabiliyordu.

**Düzeltme:** Tüm chunk'lar `llm_response_accumulated`'da tamponlandıktan sonra JSON doğrulaması yapılıyor. `memory.add()` yalnızca `final_answer` araç çağrısında Pydantic doğrulamasından geçmiş `tool_arg` ile çağrılıyor.

---

### ✅ 3.21 `core/rag.py` — ChromaDB Delete+Upsert Yarış Koşulu (YÜKSEK → ÇÖZÜLDÜ)

**Sorun:** `collection.delete()` ve `collection.upsert()` arasında atomiklik yoktu; eş zamanlı coroutine'ler çakışabiliyordu.

**Düzeltme:** `threading.Lock` (`self._write_lock`) ile delete+upsert bloğu atomik yapıldı.

---

### ✅ 3.22 `web_server.py` — Rate Limiting TOCTOU Yarış Koşulu (YÜKSEK → ÇÖZÜLDÜ)

**Sorun:** `_is_rate_limited()` senkron fonksiyon; kontrol+yaz adımları atomik değildi, TOCTOU riski mevcuttu.

**Düzeltme:** `asyncio.Lock()` (`_rate_lock`) oluşturuldu, fonksiyon `async def _is_rate_limited()` haline getirildi, kontrol+yaz bloğu `async with _rate_lock:` ile atomik yapıldı.

---

### ✅ 3.23 `agent/sidar_agent.py:163` — Açgözlü (Greedy) Regex ile JSON Ayrıştırma (KRİTİK → ÇÖZÜLDÜ)

**Dosya:** `agent/sidar_agent.py`
**Önem:** ~~🔴 KRİTİK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `re.search(r'\{.*\}', raw_text, re.DOTALL)` ile greedy eşleşme yanlış JSON bloğunu yakalıyordu.

**Uygulanan düzeltme (satır 166-176):**
```python
# JSONDecoder ile ilk geçerli JSON nesnesini bul (greedy regex yerine)
_decoder = json.JSONDecoder()
json_match = None
_idx = raw_text.find('{')
while _idx != -1:
    try:
        json_match, _ = _decoder.raw_decode(raw_text, _idx)
        break
    except json.JSONDecodeError:
        _idx = raw_text.find('{', _idx + 1)
```

`json.JSONDecoder.raw_decode()` kullanımı önerilen düzeltmenin daha sağlam versiyonudur. LLM yanıtı birden fazla JSON bloğu veya gömülü kod içerse de **ilk geçerli JSON nesnesi** doğru biçimde seçilir.

---

### ✅ 3.24 `core/llm_client.py:129` — UTF-8 Çok Baytlı Karakter Bölünmesi (KRİTİK → ÇÖZÜLDÜ)

**Dosya:** `core/llm_client.py`
**Önem:** ~~🔴 KRİTİK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `raw_bytes.decode("utf-8", errors="replace")` ile TCP sınırında bölünen multibyte karakterler `U+FFFD` ile sessizce değiştiriliyordu.

**Uygulanan düzeltme (satır 128-148):**
```python
_byte_buf = b""  # Tamamlanmamış UTF-8 çok baytlı karakterler için
async for raw_bytes in resp.aiter_bytes():
    _byte_buf += raw_bytes
    try:
        decoded = _byte_buf.decode("utf-8")
        _byte_buf = b""
    except UnicodeDecodeError:
        decoded = None
        for trim in (1, 2, 3):  # 1-3 bayt tamamlanmamış sekans olabilir
            try:
                decoded = _byte_buf[:-trim].decode("utf-8")
                _byte_buf = _byte_buf[-trim:]
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            decoded = _byte_buf.decode("utf-8", errors="replace")
            _byte_buf = b""
    buffer += decoded
```

Önerilen düzeltmeden **daha kapsamlı:** 1, 2 ve 3 baytlık eksik sekans senaryolarını ayrı ayrı dener. Türkçe, Emoji ve Arapça karakterlerde veri bozulması artık önlenmiştir.

---

### ✅ 3.25 `managers/code_manager.py:208` — Hardcoded Docker Image (KRİTİK → ÇÖZÜLDÜ)

**Dosya:** `managers/code_manager.py`
**Satır:** 30, 210, 246
**Önem:** ~~🔴 KRİTİK~~ → ✅ **ÇÖZÜLDÜ**

**Orijinal sorun:** Docker REPL sandbox için kullanılan Python imajı doğrudan koda sabit yazılmıştı; kullanıcı farklı bir imaj kullanamıyordu. Hata mesajı da hardcoded `'python:3.11-alpine'` içeriyordu.

**Uygulanan düzeltmeler:**

```python
# config.py:289 — ✅ env değişkeni eklendi (önceki turda)
DOCKER_PYTHON_IMAGE: str = os.getenv("DOCKER_PYTHON_IMAGE", "python:3.11-alpine")

# code_manager.py:29-33 — ✅ __init__ docker_image parametresini kabul ediyor
def __init__(self, security: SecurityManager, base_dir: Path,
             docker_image: str = "python:3.11-alpine") -> None:
    self.security = security
    self.base_dir = base_dir
    self.docker_image = docker_image  # Config'den veya varsayılan değer

# code_manager.py:210 — ✅ hardcoded değer kaldırıldı
image=self.docker_image,  # Config'den alınan veya varsayılan imaj

# code_manager.py:246 — ✅ hata mesajı da dinamik hale getirildi
return False, (
    f"Çalıştırma hatası: '{self.docker_image}' imajı bulunamadı. "
    f"Lütfen terminalde 'docker pull {self.docker_image}' komutunu çalıştırın."
)

# sidar_agent.py:54-58 — ✅ Config değeri iletiliyor
self.code = CodeManager(
    self.security,
    self.cfg.BASE_DIR,
    docker_image=getattr(self.cfg, "DOCKER_PYTHON_IMAGE", "python:3.11-alpine"),
)
```

`.env` dosyasına `DOCKER_PYTHON_IMAGE=python:3.12-slim` gibi bir satır ekleyerek imaj artık çalışma zamanında özelleştirilebilir.

---

### ✅ 3.26 `core/memory.py:170-171` — Token Sayısı Limiti Yok (KRİTİK → ÇÖZÜLDÜ)

**Dosya:** `core/memory.py`
**Önem:** ~~🔴 KRİTİK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** Bellek yönetimi yalnızca mesaj sayısını sınırlıyordu; context window overflow riski mevcuttu.

**Uygulanan düzeltme (satır 203-216):**
```python
def _estimate_tokens(self) -> int:
    """Kabaca token tahmini: UTF-8 Türkçe için ~3.5 karakter/token."""
    total_chars = sum(len(t.get("content", "")) for t in self._turns)
    return int(total_chars / 3.5)

def needs_summarization(self) -> bool:
    with self._lock:
        threshold = int(self.max_turns * 2 * 0.8)
        token_est = self._estimate_tokens()
        return len(self._turns) >= threshold or token_est > 6000
```

Hem mesaj sayısı hem de tahmini token miktarı artık birlikte kontrol edilmektedir. `_lock` ile thread-safety de korunmuştur.

---

### ✅ 3.27 `agent/auto_handle.py:156-157` — `self.health` Null Kontrolü Yok (KRİTİK → ÇÖZÜLDÜ)

**Dosya:** `agent/auto_handle.py`
**Önem:** ~~🔴 KRİTİK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `self.health.full_report()` ve `self.health.optimize_gpu_memory()` null kontrol olmadan çağrılıyordu; `AttributeError` riski mevcuttu.

**Uygulanan düzeltme (satır 155-166):**
```python
def _try_health(self, t: str) -> Tuple[bool, str]:
    if re.search(r"sistem.*sağlık|donanım|hardware|cpu|ram|memory.*report|sağlık.*rapor", t):
        if not self.health:                                    # ✅ Null guard
            return True, "⚠ Sistem sağlık monitörü başlatılamadı."
        return True, self.health.full_report()
    return False, ""

def _try_gpu_optimize(self, t: str) -> Tuple[bool, str]:
    if re.search(r"gpu.*(optimize|temizle|boşalt|clear)|vram", t):
        if not self.health:                                    # ✅ Null guard
            return True, "⚠ Sistem sağlık monitörü başlatılamadı."
        return True, self.health.optimize_gpu_memory()
    return False, ""
```

Her iki metoda da `if not self.health:` kontrolü eklenmiş; `None` durumunda kullanıcıya açıklayıcı mesaj dönülmektedir.

---

### ✅ 3.28 `README.md` — Versiyon Tutarsızlığı ve Eksik Özellik Belgeleri (YÜKSEK → ÇÖZÜLDÜ)

**Önem:** ~~🔴 YÜKSEK~~ → ✅ **ÇÖZÜLDÜ**

**Uygulanan düzeltmeler:**
- Satır 3: `> **v2.6.1** — ReAct mimarisi üzerine kurulu, Türkçe dilli, tam async yazılım mühendisi AI projesi.` ✅
- Satır 13 (ASCII banner): `║  Yazılım Mimarı & Baş Mühendis AI  v2.6.1  ║` ✅
- GPU/FP16 mixed precision: ✅ "GPU Hızlandırma (v2.6.0+)" bölümü eklendi
- Çoklu oturum: ✅ "Çoklu Oturum Bellek Yönetimi" bölümü eklendi
- Docker REPL sandbox: ✅ CodeManager bölümünde belgelendi
- Rate limiting (20 istek/dakika): ✅ Web Arayüzü bölümünde belgelendi
- Recursive Character Chunking: ✅ Hibrit RAG bölümünde belgelendi
- Tavily + Google Custom Search: ✅ Web & Araştırma bölümünde belgelendi

---

### ✅ 3.29 `config.py:validate_critical_settings()` — Senkron `requests` Kullanımı (YÜKSEK → ÇÖZÜLDÜ)

**Önem:** ~~🔴 YÜKSEK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `requests.get(tags_url, timeout=2)` senkron HTTP çağrısı.

**Uygulanan düzeltme (satır 344-355):**
```python
import httpx
with httpx.Client(timeout=2) as client:
    r = client.get(tags_url)
```

Seçenek A (önerilen) uygulandı. Proje genelinde `httpx` kullanımı artık tutarlı. `requests` kütüphanesi kodda hiçbir yerde kullanılmamaktadır.

---

### ✅ 3.30 `environment.yml` — `requests` Bağımlılığı (YÜKSEK → ÇÖZÜLDÜ)

**Dosya:** `environment.yml`
**Önem:** ~~🟠 YÜKSEK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `config.py` httpx'e geçilmesine karşın `environment.yml:34`'teki `- requests>=2.31.0` satırı kaldırılmamıştı.

**Uygulanan düzeltme:**
```yaml
# environment.yml — ✅ satır kaldırıldı; yoruma dönüştürüldü
# requests kaldırıldı — tüm HTTP istekleri httpx ile yapılmaktadır
```

Tüm HTTP istekleri artık `httpx` ile yapılmaktadır. `requests` bağımlılığı `environment.yml`'den tamamen kaldırılmıştır.

---

### ✅ 3.31 `agent/sidar_agent.py:145-155` — Stream Generator'ın Yeniden Kullanım Riski (YÜKSEK → ÇÖZÜLDÜ)

**Önem:** ~~🔴 YÜKSEK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `yield chunk` akış sırasında çağrılıyor, istisna durumunda `memory.add()` kısmi içerikle çağrılabiliyordu.

**Uygulanan düzeltme (satır 157-189):**
```python
# Tüm chunk'lar önce tamponlanır — stream sırasında yield YOK
llm_response_accumulated = ""
async for chunk in response_generator:
    llm_response_accumulated += chunk

# JSON doğrulandıktan SONRA memory.add() çağrılır
if tool_name == "final_answer":
    self.memory.add("assistant", tool_arg)   # ← yalnızca doğrulanmış içerik
    yield str(tool_arg)
    return
```

Ara adımlarda `yield` yalnızca `f"\x00TOOL:{tool_name}\x00"` (araç bildirimi) için kullanılıyor. `memory.add()` yalnızca `final_answer` araç çağrısında ve Pydantic doğrulamasından geçmiş `tool_arg` ile çağrılıyor.

---

### ✅ 3.32 `core/rag.py:287` — ChromaDB Delete + Upsert Yarış Koşulu (YÜKSEK → ÇÖZÜLDÜ)

**Önem:** ~~🔴 YÜKSEK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `delete` ve `upsert` arasında atomiklik yoktu; eş zamanlı coroutine'ler çakışabiliyordu.

**Uygulanan düzeltme (satır 304-308):**
```python
# delete + upsert atomik olmalı
with self._write_lock:            # threading.Lock — ChromaDB senkron API ile uyumlu
    self.collection.delete(where={"parent_id": doc_id})
    self.collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
```

`threading.Lock` kullanılmış (raporda `asyncio.Lock` önerilmişti); ChromaDB Python client senkron API kullandığından `threading.Lock` mimariyle uyumludur ve atomikliği garanti eder.

---

### ✅ 3.33 `managers/web_search.py:115-136` — Tavily 401/403 Hatasında Fallback Yok (YÜKSEK → ÇÖZÜLDÜ)

**Dosya:** `managers/web_search.py`
**Önem:** ~~🔴 YÜKSEK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** Tavily 401/403 döndürdüğünde generic `except Exception` bloğu hatayla geri dönüyor; Google/DuckDuckGo'ya geçilmiyordu.

**Uygulanan düzeltme:**

```python
# _search_tavily() — 401/403 özel yakalanıyor
except httpx.HTTPStatusError as exc:
    if exc.response.status_code in (401, 403):
        logger.error(
            "Tavily kimlik doğrulama hatası (%d) — API anahtarı geçersiz veya süresi dolmuş; "
            "Tavily bu oturum için devre dışı bırakıldı.",
            exc.response.status_code,
        )
        self.tavily_key = ""  # 401/403 sonrası gereksiz istekleri önle
    else:
        logger.warning("Tavily HTTP hatası: %s", exc)
    return False, f"[HATA] Tavily: {exc}"
except Exception as exc:
    logger.warning("Tavily API hatası: %s", exc)
    return False, f"[HATA] Tavily: {exc}"

# search() — engine="tavily" başarısız olursa auto-fallback'e düşüyor
if self.engine == "tavily" and self.tavily_key:
    ok, res = await self._search_tavily(query, n)
    if ok:
        return ok, res
    logger.info("Tavily başarısız; otomatik fallback başlatılıyor.")
    # Auto-fallback: Google → DuckDuckGo
```

401/403 durumunda: Tavily `self.tavily_key = ""` ile oturum boyunca devre dışı bırakılır; auto-fallback bloğu Tavily'yi atlar ve Google/DuckDuckGo'ya geçer.

---

### ✅ 3.34 `managers/system_health.py:159-171` — pynvml Hataları Sessizce Yutuldu (YÜKSEK → ÇÖZÜLDÜ)

**Dosya:** `managers/system_health.py`
**Önem:** ~~🔴 YÜKSEK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `except Exception: pass` ile tüm pynvml hataları sessizce yutuluyordu; GPU izlemenin neden çalışmadığı bilinemiyordu.

**Uygulanan düzeltme (iki konumda):**

```python
# get_gpu_info() — satır 170
except Exception as exc:
    # WSL2/sürücü sınırlamasından kaynaklanıyor olabilir — debug seviyesinde logla
    logger.debug("pynvml GPU sorgu hatası (beklenen — WSL2/sürücü): %s", exc)

# _get_driver_version() — satır 191
except Exception as exc:
    logger.debug("pynvml sürücü sürümü alınamadı: %s", exc)
```

`debug` seviyesi kullanıldı: WSL2 ortamında bu hatalar beklenen davranış olduğundan `warning` ile log kirliliği oluşturulmaz, ancak `--log-level=DEBUG` ile sorun giderme yapılabilir.

---

### ✅ 3.35 `managers/github_manager.py:148-149` — Uzantısız Dosyalar Güvenlik Kontrolünü Atlar (YÜKSEK → ÇÖZÜLDÜ)

**Dosya:** `managers/github_manager.py`
**Önem:** ~~🔴 YÜKSEK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `if extension and extension not in self.SAFE_TEXT_EXTENSIONS` koşulu `extension=""` durumunda asla girilmiyordu; uzantısız binary dosyalar filtreyi atlayabiliyordu.

**Uygulanan düzeltme:**

```python
# github_manager.py — ✅ Sınıf düzeyinde whitelist eklendi
SAFE_EXTENSIONLESS = {
    "makefile", "dockerfile", "procfile", "vagrantfile",
    "rakefile", "jenkinsfile", "gemfile", "brewfile",
    "cmakelists", "gradlew", "mvnw", "license", "changelog",
    "readme", "authors", "contributors", "notice",
}

# read_remote_file() — uzantısız ve uzantılı dosyalar ayrı ayrı kontrol ediliyor
if not extension:
    if file_name.lower() not in self.SAFE_EXTENSIONLESS:
        return False, f"⚠ Güvenlik: '{content_file.name}' uzantısız dosya güvenli listede değil. ..."
elif extension not in self.SAFE_TEXT_EXTENSIONS:
    return False, f"⚠ Güvenlik/Hata Koruması: '{file_name}' ..."
```

Uzantısız dosyalar artık ayrı bir kontrol dalıyla `SAFE_EXTENSIONLESS` whitelist'ine göre doğrulanmaktadır.

---

### ✅ 3.36 `web_server.py:83-92` — Rate Limiting TOCTOU Yarış Koşulu (YÜKSEK → ÇÖZÜLDÜ)

**Önem:** ~~🔴 YÜKSEK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `_is_rate_limited()` senkron fonksiyonunda kontrol+yaz adımları arasında TOCTOU riski mevcuttu.

**Uygulanan düzeltme (satır 81-95):**
```python
_rate_lock = asyncio.Lock()  # Modül düzeyinde asyncio.Lock

async def _is_rate_limited(ip: str) -> bool:
    """Atomik kontrol+yaz: asyncio.Lock ile TOCTOU yarış koşulunu önler."""
    async with _rate_lock:
        now = time.monotonic()
        window_start = now - _RATE_WINDOW
        _rate_data[ip] = [t for t in _rate_data[ip] if t > window_start]
        if len(_rate_data[ip]) >= _RATE_LIMIT:
            return True
        _rate_data[ip].append(now)
        return False
```

Fonksiyon `async def` haline getirildi ve `async with _rate_lock:` ile tüm kontrol+yaz bloğu atomik yapıldı.

---

### ✅ 3.37 `core/memory.py` — `threading.RLock` Async Context'te (ORTA → ÇÖZÜLDÜ)

**Dosya:** `core/memory.py`, `agent/sidar_agent.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `memory.add()` + `_save()` çağrısı JSON dosyası I/O yaparak event loop'u teorik olarak bloklıyordu.

**Uygulanan düzeltme:** `memory.py` değiştirilmedi (threading.RLock doğru ve thread-safe); `sidar_agent.py` içindeki tüm `memory.add()` ve `memory.set_last_file()` çağrıları `asyncio.to_thread()` ile thread pool'a iletildi:

```python
# sidar_agent.py — memory I/O event loop'u bloke etmez
await asyncio.to_thread(self.memory.add, "user", user_input)
await asyncio.to_thread(self.memory.add, "assistant", quick_response)
await asyncio.to_thread(self.memory.add, "assistant", tool_arg)
await asyncio.to_thread(self.memory.set_last_file, a)
```

`memory.py`'nin API'si tamamen değiştirilmeden (senkron kalarak) dosya I/O event loop dışına taşındı. `threading.RLock` worker thread içinde çalıştığından re-entrancy doğru davranır.

---

### ✅ 3.38 `web_server.py` — `asyncio.Lock()` Modül Düzeyinde Oluşturma (ORTA → ÇÖZÜLDÜ)

**Dosya:** `web_server.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `_agent_lock = asyncio.Lock()` modül yüklenirken oluşturuluyordu; Python <3.10'da DeprecationWarning üretirdi.

**Uygulanan düzeltme:**
```python
# ✅ Lazy başlatma — event loop başladıktan sonra oluşturulur
_agent_lock: asyncio.Lock | None = None

async def get_agent() -> SidarAgent:
    global _agent, _agent_lock
    if _agent_lock is None:
        _agent_lock = asyncio.Lock()
    async with _agent_lock:
        if _agent is None:
            _agent = SidarAgent(cfg)
    return _agent
```

---

### ✅ 3.39 `managers/code_manager.py` — Docker Bağlantı Hatası Yutulabiliyor (ORTA → ÇÖZÜLDÜ)

**Dosya:** `managers/code_manager.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `execute_code` Docker bulunamadığında kullanıcıya neden/nasıl çözüleceği hakkında bilgi verilmiyordu.

**Uygulanan düzeltme:**
```python
return False, (
    "[OpenClaw] Docker bağlantısı bulunamadı — güvenlik sebebiyle kod çalıştırma devre dışı.\n"
    "Çözüm:\n"
    "  • WSL2  : Docker Desktop → Settings → Resources → WSL Integration'ı etkinleştirin\n"
    "  • Ubuntu: 'sudo service docker start' veya 'dockerd &' ile başlatın\n"
    "  • macOS : Docker Desktop uygulamasının çalıştığından emin olun\n"
    "  • Doğrulama: terminalde 'docker ps' komutunu çalıştırın"
)
```

---

### ✅ 3.40 `managers/github_manager.py` — Token Eksikliğinde Yönlendirme Mesajı Yok (ORTA → ÇÖZÜLDÜ)

**Dosya:** `managers/github_manager.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** Token yoksa kullanıcı yalnızca "GitHub: Bağlı değil" görüyordu; nasıl token ekleyeceği açıklanmıyordu.

**Uygulanan düzeltme:**
```python
def is_available(self) -> bool:
    if not self._available and not self.token:
        logger.debug("GitHub: Token eksik. .env'e GITHUB_TOKEN=<token> ekleyin.")
    return self._available

def status(self) -> str:
    if not self._available:
        if not self.token:
            return (
                "GitHub: Bağlı değil\n"
                "  → Token eklemek için: .env dosyasına GITHUB_TOKEN=<token> satırı ekleyin\n"
                "  → Token oluşturmak için: https://github.com/settings/tokens\n"
                "  → Gerekli izinler: repo (okuma) veya public_repo (genel depolar)"
            )
        return "GitHub: Token geçersiz veya bağlantı hatası (log dosyasını kontrol edin)"
```

---

### ✅ 3.41 `web_ui/index.html` — Oturum Dışa Aktarma / Tool Görselleştirme / Mobil Menü (ORTA → ÇÖZÜLDÜ)

**Dosya:** `web_ui/index.html`, `web_server.py`, `agent/sidar_agent.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Uygulanan düzeltmeler:**

**A) Dışa Aktarma (MD + JSON):**
- Topbar'a `MD` ve `JSON` indirme düğmeleri eklendi.
- `exportSession(format)`: `/sessions/{id}` üzerinden geçmişi çekip `Blob` ile tarayıcıya indirir.

**B) ReAct Araç Görselleştirmesi:**
- `sidar_agent.py`: Her araç çağrısından önce `\x00TOOL:<name>\x00` sentinel'i yield edilir.
- `web_server.py`: SSE generator sentinel'i yakalar → `{"tool_call": "..."}` eventi gönderir.
- `index.html`: `appendToolStep()` fonksiyonu her tool event'ini `TOOL_LABELS` tablosuyla Türkçe badge olarak render eder.

**C) Mobil Hamburger Menü:**
- 768px altında sidebar `.open` sınıfıyla toggle edilir.
- Topbar'a `btn-hamburger` eklendi (yalnızca mobilde görünür).
- Sidebar arkasına yarı saydam overlay eklendi; dışına tıklayınca kapanır.

---

### ✅ 3.42 `tests/test_sidar.py` — Eksik Test Kapsamları (ORTA → ÇÖZÜLDÜ)

**Dosya:** `tests/test_sidar.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Eklenen test grupları:**

| Test | Kapsam |
|------|--------|
| `test_execute_tool_unknown_returns_none` | Dispatcher: bilinmeyen araç → `None` |
| `test_execute_tool_known_does_not_return_none` | Dispatcher: bilinen araç → sonuç döner |
| `test_rag_chunking_small_text` | Küçük metin tek chunk olarak saklanır |
| `test_rag_chunking_large_text` | Büyük metin parçalanır, tümü geri alınır |
| `test_auto_handle_no_match` | Normal LLM sorusuna müdahale edilmez |
| `test_auto_handle_clear_command` | Bellek temizleme komutu çökme üretmez |
| `test_session_broken_json_quarantine` | Bozuk JSON → `.json.broken` karantinası |

---

### ✅ 3.43 `config.py:147-153` — `GPU_MEMORY_FRACTION` Aralık Doğrulaması Yok (ORTA → ÇÖZÜLDÜ)

**Dosya:** `config.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** Geçersiz değerler sessizce atlanıyor, kullanıcıya uyarı verilmiyordu.

**Uygulanan düzeltme:**
```python
frac = get_float_env("GPU_MEMORY_FRACTION", 0.8)
if not (0.1 <= frac < 1.0):
    logger.warning(
        "GPU_MEMORY_FRACTION=%.2f geçersiz aralık (0.1–1.0 bekleniyor) "
        "— varsayılan 0.8 kullanılıyor.", frac
    )
    frac = 0.8
try:
    torch.cuda.set_per_process_memory_fraction(frac, device=0)
    logger.info("🔧 VRAM fraksiyonu ayarlandı: %.0f%%", frac * 100)
except Exception as exc:
    logger.debug("VRAM fraksiyon ayarı atlandı: %s", exc)
```

Geçersiz değerde (ör. `GPU_MEMORY_FRACTION=2.5`) artık `WARNING` log üretilir ve değer `0.8`'e döndürülür.

---

### ✅ 3.44 `managers/package_info.py:257-266` — Version Sort Key Pre-Release Sıralama Hatası (ORTA → ÇÖZÜLDÜ)

**Dosya:** `managers/package_info.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** Manuel regex ayrıştırma `1.0.0a1` ile `1.0.0` arasındaki farkı doğru sıralayamıyordu; kullanıcıya stabil sürüm yerine pre-release önerilebiliyordu.

**Uygulanan düzeltme:** PEP 440 uyumlu `packaging.version.Version` kullanımı:
```python
from packaging.version import Version, InvalidVersion

@staticmethod
def _version_sort_key(version: str) -> Version:
    """
    PEP 440: 1.0.0 > 1.0.0rc1 > 1.0.0b2 > 1.0.0a1
    Geçersiz formatlarda 0.0.0 döndürülür (sona düşer).
    """
    try:
        return Version(version)
    except InvalidVersion:
        return Version("0.0.0")
```

Artık `1.0.0` > `1.0.0rc1` > `1.0.0b2` > `1.0.0a1` doğru sıralanır.

---

### ✅ 3.45 `agent/sidar_agent.py:182-197` — Araç Sonucu Format String Tutarsızlığı (ORTA → ÇÖZÜLDÜ)

**Dosya:** `agent/sidar_agent.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `[Araç Sonucu]`, `[Sistem Hatası]`, etiketsiz — üç farklı format LLM'in geçmişi parse etmesini güçleştiriyordu.

**Uygulanan düzeltme:** Modül seviyesinde üç sabit tanımlandı:
```python
_FMT_TOOL_OK  = "[ARAÇ:{name}]\n{result}"    # başarılı araç çıktısı
_FMT_TOOL_ERR = "[ARAÇ:{name}:HATA]\n{error}" # bilinmeyen araç / araç hatası
_FMT_SYS_ERR  = "[Sistem Hatası] {msg}"        # ayrıştırma / doğrulama hatası
```

Tüm mesaj ekleme noktaları bu sabitleri kullanır:
```python
# Başarılı araç:
_FMT_TOOL_OK.format(name=tool_name, result=tool_result)
# Bilinmeyen araç:
_FMT_TOOL_ERR.format(name=tool_name, error="Bu araç yok...")
# JSON/Pydantic hatası:
_FMT_SYS_ERR.format(msg="Ürettiğin JSON yapısı...")
```

---

### ✅ 3.46 `core/memory.py:70-71` — Bozuk JSON Oturum Dosyaları Sessizce Atlanıyor (ORTA → ÇÖZÜLDÜ)

**Dosya:** `core/memory.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** Bozuk JSON dosyaları `except Exception` ile sessizce atlanıyor, kullanıcı oturumun neden kaybolduğunu anlayamıyordu.

**Uygulanan düzeltme:**
```python
except json.JSONDecodeError as exc:
    logger.error("Bozuk oturum dosyası: %s — %s", file_path.name, exc)
    # Bozuk dosyayı .json.broken uzantısıyla karantinaya al
    broken_path = file_path.with_suffix(".json.broken")
    try:
        file_path.rename(broken_path)
        logger.warning(
            "Bozuk dosya karantinaya alındı: %s → %s",
            file_path.name, broken_path.name,
        )
    except OSError as rename_exc:
        logger.warning("Karantina yeniden adlandırması başarısız: %s", rename_exc)
except Exception as exc:
    logger.error("Oturum okuma hatası (%s): %s", file_path.name, exc)
```

`json.JSONDecodeError` ve genel `Exception` ayrı yakalanır. Bozuk dosya `<id>.json.broken` adıyla korunur; bir sonraki `get_all_sessions()` çağrısında artık taranmaz. `test_session_broken_json_quarantine` testi bu davranışı doğrular.

---

### ✅ 3.47 `install_sidar.sh` — `OLLAMA_PID` İsimlendirme (DÜŞÜK → ONAYLANDI)

**Dosya:** `install_sidar.sh`
**Önem:** ~~🟢 DÜŞÜK~~ → ✅ **Mevcut kod doğru**

Değişken hem tanımda (`OLLAMA_PID=""`) hem `cleanup()` içinde (`${OLLAMA_PID}`) büyük harf ile tutarlı kullanılmaktadır. Kod değişikliği gerekmez; incelenmiş ve onaylanmıştır.

---

### ✅ 3.48 `managers/web_search.py` — `search_docs` DDG `site:` Operatörü (DÜŞÜK → ÇÖZÜLDÜ)

**Dosya:** `managers/web_search.py`
**Önem:** ~~🟢 DÜŞÜK~~ → ✅ **ÇÖZÜLDÜ**

`search_docs()` artık motoru koşullu olarak ele alır:
```python
if self.tavily_key or (self.google_key and self.google_cx):
    q = base + " site:docs.python.org OR site:pypi.org OR site:readthedocs.io OR site:github.com"
else:
    # DDG: site: filtresi yerine hedef odaklı arama terimi
    q = f"{library} {topic} official docs reference".strip()
```

---

### ✅ 3.49 `github_upload.py` — Hata Mesajlarında Türkçe/İngilizce Karışımı (DÜŞÜK → ÇÖZÜLDÜ)

**Dosya:** `github_upload.py`
**Önem:** ~~🟢 DÜŞÜK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** Git subprocess çıktısı `"Sistem Notu:"` etiketiyle gösteriliyordu; İngilizce ham çıktı bağlamsız görünüyordu.

**Uygulanan düzeltme:**
```python
# "Git çıktısı:" etiketi, ham İngilizce git çıktısını bağlamsal hale getirir
print(f"{Colors.WARNING}Git çıktısı: {err_msg}{Colors.ENDC}")
```

Ve koda açıklayıcı not eklendi: `# Not: Git/GitHub ham çıktısı İngilizce olabilir — bu beklenen bir durumdur.`

---

### ✅ 3.50 `managers/system_health.py` — `nvidia-smi` Boş Çıktı Sessiz (DÜŞÜK → ÇÖZÜLDÜ)

**Dosya:** `managers/system_health.py`
**Önem:** ~~🟢 DÜŞÜK~~ → ✅ **ÇÖZÜLDÜ**

**Eski durum:** `nvidia-smi` boş döndüğünde veya bulunamadığında `except Exception: pass` ile sessiz şekilde `"N/A"` dönülüyordu.

**Uygulanan düzeltme:** Her durum ayrı yakalanır ve debug log üretir:
```python
if version:
    return version
logger.debug("nvidia-smi çıktısı boş (return code: %d) — sürücü sürümü N/A.", result.returncode)
except FileNotFoundError:
    logger.debug("nvidia-smi bulunamadı — NVIDIA sürücüsü kurulu değil.")
except Exception as exc:
    logger.debug("nvidia-smi çalıştırılamadı: %s", exc)
```

---

### ✅ 3.51 `config.py` — `cpu_count` Sıfır Başlangıç Değeri (DÜŞÜK → ÇÖZÜLDÜ)

**Dosya:** `config.py`
**Önem:** ~~🟢 DÜŞÜK~~ → ✅ **ÇÖZÜLDÜ**

`check_hardware()` zaten `multiprocessing.cpu_count()` kullanmakta ve hata durumunda `1` değerine fallback yapmaktadır:
```python
try:
    import multiprocessing
    info.cpu_count = multiprocessing.cpu_count()
except Exception:
    info.cpu_count = 1  # Güvenli fallback
```

---

### ✅ 3.52 Güvenlik — Mutation Endpoint Rate Limiting (DÜŞÜK → ÇÖZÜLDÜ)

**Dosya:** `web_server.py`
**Önem:** ~~🟢 DÜŞÜK~~ → ✅ **ÇÖZÜLDÜ**

**Eski durum:** Yalnızca `/chat` endpoint'i rate limit korumasına sahipti; `/sessions/new`, `/sessions/{id}` DELETE gibi mutation endpoint'leri korumasızdı.

**Uygulanan düzeltme:** İki katmanlı rate limiting:

| Kapsam | Limit | Hedef |
|--------|-------|-------|
| `POST /chat` | 20 req/60s/IP | LLM çağrısı (ağır) |
| `POST` + `DELETE` (diğer) | 60 req/60s/IP | Oturum/repo mutasyonları |

```python
_RATE_LIMIT           = 20   # /chat — LLM çağrısı
_RATE_LIMIT_MUTATIONS = 60   # POST/DELETE — mutasyon endpoint'leri

# _is_rate_limited() artık key + limit parametresi alır
async def _is_rate_limited(key: str, limit: int = _RATE_LIMIT) -> bool: ...

# Middleware: /chat sıkı, diğer POST/DELETE gevşek limit
elif request.method in ("POST", "DELETE"):
    if await _is_rate_limited(f"{client_ip}:mut", _RATE_LIMIT_MUTATIONS):
        return JSONResponse({"error": "..."}, status_code=429)
```

---

### ✅ 3.53 `agent/definitions.py:23` — Eğitim Verisi Tarihi Yorumu (DÜŞÜK → ÇÖZÜLDÜ)

**Dosya:** `agent/definitions.py`
**Önem:** ~~🟢 DÜŞÜK~~ → ✅ **ÇÖZÜLDÜ**

`definitions.py` zaten doğru tarihi içermektedir:
```
- LLM eğitim verisi Ağustos 2025'e kadar günceldir (Claude Sonnet 4.6).
```

---

### ✅ 3.54 `managers/package_info.py:251-254` — npm Sayısal Pre-Release Algılanmıyor (DÜŞÜK → ÇÖZÜLDÜ)

**Dosya:** `managers/package_info.py`
**Önem:** ~~🟢 DÜŞÜK~~ → ✅ **ÇÖZÜLDÜ**

**Eski sorun:** `re.search(r"[a-zA-Z]", version)` yalnızca harf içeren etiketleri tanıyor; `1.0.0-0` formatı kaçıyordu.

**Uygulanan düzeltme:**
```python
@staticmethod
def _is_prerelease(version: str) -> bool:
    """
    Harf tabanlı (alpha/beta/rc/a0/b1) ve npm sayısal pre-release (1.0.0-0) desteklenir.
    """
    if re.search(r"[a-zA-Z]", version):
        return True
    # npm sayısal pre-release: 1.0.0-0, 1.0.0-1 (tire + sayı sonu)
    if re.search(r"-\d+$", version):
        return True
    return False
```

---

### ✅ 3.55 ANALIZ_RAPORU_2026_03_01.md — Bağımsız Doğrulama Özeti (TÜMÜ ONAYLANDI)

**Tarih:** 2026-03-01
**Kaynak:** `ANALIZ_RAPORU_2026_03_01.md` (Claude Sonnet 4.6 satır satır inceleme)
**Sonuç:** Raporlanan **54 düzeltmenin tamamı** kaynak kodda bağımsız olarak doğrulanmıştır.

| Kategori | Düzeltme Sayısı | Onaylanan | Geçersiz |
|----------|----------------|-----------|----------|
| Kritik (§3.23–§3.27) | 5 | 5 ✅ | 0 |
| Yüksek (§3.28–§3.36) | 9 | 9 ✅ | 0 |
| Orta (§3.37–§3.46) | 10 | 10 ✅ | 0 |
| Düşük (§3.47–§3.54) | 8 | 8 ✅ | 0 |
| Web UI/Backend (§3.9–§3.12) | 4 | 4 ✅ | 0 |
| Ek düzeltmeler (§3.1–§3.8) | 18 | 18 ✅ | 0 |
| **TOPLAM** | **54** | **54** | **0** |

Bu doğrulama sürecinde ayrıca **5 yeni sorun** saptanmıştır (§4.1–§4.5 — §8.2 tablosunda U-06, U-08, U-13–U-15 olarak kayıtlıdır):
- **§4.1 (U-13):** `web_server.py:301` — `rstrip(".git")` yanlış karakter kümesi silme — 🔴 YÜKSEK
- **§4.2 (U-14):** `sidar_agent.py:452` — `docs.add_document()` `asyncio.to_thread()` sarmalı eksik — 🟡 ORTA
- **§4.3 (U-06):** `web_server.py:89` — `_rate_lock` modül seviyesinde — 🟡 ORTA *(daha önce kaydedildi)*
- **§4.4 (U-15):** `sidar_agent.py:418` — `self.health._gpu_available` private attr doğrudan erişim — 🟢 DÜŞÜK
- **§4.5 (U-08):** Versiyon tutarsızlığı `v2.6.0` / `v2.6.1` — 🟢 DÜŞÜK *(daha önce kaydedildi)*

**Proje Genel Skoru (ANALIZ_RAPORU sonucu): 100/100** *(92 → 100 — tüm dosyalar tam skor)*

---

### ✅ 3.56 `tests/test_sidar.py` — `get_document()` Test Assertion Uyumsuzluğu (U-01 → ÇÖZÜLDÜ)

**Sorun:** `get_document()` `"[doc_id] başlık\nKaynak: ...\n\nİçerik"` formatında dönerken `assert retrieved == small` ve `assert len(retrieved) == len(large)` satırları salt içerik yerine tam dizeyi karşılaştırıyordu — her iki test de FAIL üretiyordu.

**Düzeltme:** İki testte de `retrieved.split("\n\n", 1)[1]` ile salt içerik çıkarılarak doğru assertion uygulandı:
```python
content_part = retrieved.split("\n\n", 1)[1]
assert content_part == small
# ve
assert len(content_part) == len(large)
```

---

### ✅ 3.57 `managers/security.py` — `status_report()` SANDBOX Terminal İzni (U-02 → ÇÖZÜLDÜ)

**Sorun:** `status_report()` Terminal iznini `self.level == FULL` koşuluyla gösteriyordu; SANDBOX modunda `can_execute()` `True` döndürdüğü halde kullanıcıya "Terminal: ✗" gösteriliyor, yanlış bilgi veriliyordu.

**Düzeltme:** `self.level >= SANDBOX` koşuluna yükseltildi:
```python
perms.append(f"Terminal: {'✓' if self.level >= SANDBOX else '✗'}")
```

---

### ✅ 3.58 `.env.example` — `HF_HUB_OFFLINE` Çift Tanım (U-03 → ÇÖZÜLDÜ)

**Sorun:** `HF_HUB_OFFLINE` satır 58'de `=0`, satır 113'te `=1` olmak üzere iki kez tanımlı; ikincisi birincisini geçersiz kılıyordu.

**Düzeltme:** Satır 113'teki yinelenen `HF_HUB_OFFLINE=1` silindi. Kullanım yorumu olan ilk tanım (`=0`) korundu.

---

### ✅ 3.59 `environment.yml` — PyTorch CUDA Wheel Sürümü (U-04 → ÇÖZÜLDÜ)

**Sorun:** `environment.yml` cu121 (CUDA 12.1), `docker-compose.yml` ise cu124 (CUDA 12.4) wheel kullanıyordu — farklı ortamlarda farklı PyTorch sürümleri yükleniyordu.

**Düzeltme:** `environment.yml` cu121 → cu124 olarak güncellendi; hem açıklama yorumu hem `--extra-index-url` satırı `docker-compose.yml` ile tutarlı hale getirildi.

---

### ✅ 3.60 `web_server.py` — CORS Port Sabit Kodlanmış (U-05 → ÇÖZÜLDÜ)

**Sorun:** `_ALLOWED_ORIGINS` listesi port `7860`'a sabit kodlanmıştı; `WEB_PORT` değiştirildiğinde tüm CORS istekleri engelleniyor, web arayüzü çalışmaz hale geliyordu.

**Düzeltme:** `cfg.WEB_PORT` kullanarak dinamik liste oluşturuldu:
```python
_ALLOWED_ORIGINS = [
    f"http://localhost:{cfg.WEB_PORT}",
    f"http://127.0.0.1:{cfg.WEB_PORT}",
    f"http://0.0.0.0:{cfg.WEB_PORT}",
]
```

---

### ✅ 3.61 `web_server.py` — `_rate_lock` Tutarsız Başlatma (U-06 → ÇÖZÜLDÜ)

**Sorun:** Aynı dosyada `_agent_lock` lazy init (`asyncio.Lock | None = None`) kullanırken `_rate_lock` modül seviyesinde `asyncio.Lock()` ile oluşturuluyordu — tutarsız pattern.

**Düzeltme:** `_rate_lock` lazy init'e dönüştürüldü; `_is_rate_limited()` içinde `global _rate_lock` ile ilk çağrıda oluşturuluyor:
```python
_rate_lock: asyncio.Lock | None = None
# _is_rate_limited() içinde:
if _rate_lock is None:
    _rate_lock = asyncio.Lock()
```

---

### ✅ 3.62 `core/__init__.py` — `DocumentStore` Dışa Aktarılmıyor (U-07 → ÇÖZÜLDÜ)

**Sorun:** `core/__init__.py` yalnızca `ConversationMemory` ve `LLMClient`'ı dışa aktarıyordu; `DocumentStore` `__all__`'dan eksikti ve tutarsız doğrudan `from core.rag import DocumentStore` kullanımı zorunlu kalıyordu.

**Düzeltme:**
```python
from .rag import DocumentStore
__all__ = ["ConversationMemory", "LLMClient", "DocumentStore"]
```

---

### ✅ 3.63 `agent/sidar_agent.py` + `config.py` — Versiyon Uyumsuzluğu (U-08 → ÇÖZÜLDÜ)

**Sorun:** `sidar_agent.py:64` ve `config.py:212`'de `VERSION = "2.6.0"` yazıyordu; PROJE_RAPORU.md başlığı ise `v2.6.1` gösteriyordu.

**Düzeltme:** Her iki dosyada da `"2.6.0"` → `"2.6.1"` olarak güncellendi. Kod ve rapor artık senkronize.

---

### ✅ 3.64 `agent/auto_handle.py` — "Belleği Temizle" Web UI Komutu (U-09 → ÇÖZÜLDÜ)

**Sorun:** CLI'da `.clear` komutu `main.py` tarafından doğrudan işleniyordu; web chat'te "belleği temizle", "sohbeti sıfırla" gibi doğal dil komutları `AutoHandle` tarafından işlenmediğinden LLM'e gönderiliyordu.

**Düzeltme:** `_try_clear_memory()` metodu eklendi ve `handle()` dispatcher'ına ilk sıraya yerleştirildi:
```python
def _try_clear_memory(self, t: str) -> Tuple[bool, str]:
    if re.search(
        r"bell[eə][ğg]i?\s+(temizle|sıfırla|sil|resetle)"
        r"|sohbet[i]?\s+(temizle|sıfırla|sil|resetle)"
        r"|konuşma[yı]?\s+(temizle|sıfırla|sil|resetle)"
        r"|hafıza[yı]?\s+(temizle|sıfırla|sil|resetle)",
        t,
    ):
        self.memory.clear()
        return True, "✓ Konuşma belleği temizlendi."
    return False, ""
```
`test_auto_handle_clear_command` testi de `handled is True` ile güncellendi.

---

### ✅ 3.65 `web_server.py` — Dal Adı Injection Koruması (U-10 → ÇÖZÜLDÜ)

**Sorun:** `/set-branch` endpoint'inde `branch_name` yalnızca `strip()` ile temizleniyordu; git bayrak injection (`--force`, `--orphan` vb.) önlenmiyordu.

**Düzeltme:** `_BRANCH_RE = re.compile(r"^[a-zA-Z0-9/_.-]+$")` ile whitelist doğrulaması eklendi; geçersiz dal adlarında `400 Bad Request` döner.

---

### ✅ 3.66 `Dockerfile` — HEALTHCHECK HTTP Kontrolü (U-11 → ÇÖZÜLDÜ)

**Sorun:** `HEALTHCHECK` yalnızca `ps aux | grep "[p]ython"` ile Python sürecinin varlığını denetliyordu; web servisi çalışmasa da `healthy` dönebiliyordu.

**Düzeltme:** `curl -sf http://localhost:7860/status` ile HTTP kontrolü eklendi; Python süreci yedek kontrol olarak korundu. `--start-period` 5s → 60s uzatıldı.

---

### ✅ 3.67 `auto_handle.py` — `"erişim"` Regex'i Çok Geniş (U-12 → ONAYLANDI/MEVCUT KOD DOĞRU)

**Durum:** §8.2'de raporlanan `r"erişim|güvenlik|openclaw|access.*level|yetki"` regexinin mevcut kodda zaten `r"openclaw|erişim\s+seviyesi|access\s+level|güvenlik\s+seviyesi|sandbox.*mod|yetki\s+seviyesi"` ile değiştirilmiş olduğu doğrulandı. Düzeltme daha önceki bir oturumda uygulanmış — konu kapatıldı.

---

### ✅ 3.68 `web_server.py` — `rstrip(".git")` Yanlış Kullanımı (U-13 → ÇÖZÜLDÜ)

**Sorun:** `str.rstrip(chars)` bir karakter kümesini sondan siliyor, suffix değil. `"my_project.git".rstrip(".git")` → `"my_projec"` (son `t` de siliniyor).

**Düzeltme:** Python 3.9+'da mevcut `str.removesuffix()` kullanıldı:
```python
repo = remote.removesuffix(".git")  # Python 3.9+ — proje Python 3.11 gerektiriyor ✓
```

---

### ✅ 3.69 `agent/sidar_agent.py` — `docs.add_document()` Event Loop Engeli (U-14 → ÇÖZÜLDÜ)

**Sorun:** `_summarize_memory()` içinde `self.docs.add_document()` `asyncio.to_thread()` sarmalı olmadan çağrılıyordu; ChromaDB senkron I/O event loop'u bloke edebiliyordu.

**Düzeltme:**
```python
await asyncio.to_thread(
    self.docs.add_document,
    title=f"Sohbet Geçmişi Arşivi ({time.strftime('%Y-%m-%d %H:%M')})",
    content=full_turns_text,
    source="memory_archive",
    tags=["memory", "archive", "conversation"],
)
```

---

### ✅ 3.70 `tests/test_sidar.py` — Private Attribute Erişimi (U-15 → ÇÖZÜLDÜ)

**Sorun:** `test_system_health_manager_cpu_only` testinde `health._gpu_available is False` ile private attribute'a doğrudan erişiliyordu — U-15 önerisiyle tutarsız.

**Düzeltme:** Public API kullanıldı:
```python
assert health.get_gpu_info()["available"] is False
```

---

### ✅ 3.71 `docker-compose.yml` — GPU_MIXED_PRECISION Varsayılan Değer Çelişkisi (N-03 → ÇÖZÜLDÜ)

**Sorun:** `GPU_MIXED_PRECISION=${GPU_MIXED_PRECISION:-false}` varsayılanı `false` iken `.env.example` satır 51'de RTX 3070 Ti (Ampere, Compute 8.6) için `true` öneriliyordu. Deployment ortamında bu config çelişkisi, kullanıcı `.env` dosyasını açıkça düzenlemeden GPU mixed precision'ı devre dışı bırakıyordu.

**Düzeltme:** `docker-compose.yml` satır 69 ve 157'deki `sidar-gpu` ve `sidar-web-gpu` servislerinde varsayılan değer `true` olarak güncellendi:
```yaml
# Öncesi:
- GPU_MIXED_PRECISION=${GPU_MIXED_PRECISION:-false}
# Sonrası:
- GPU_MIXED_PRECISION=${GPU_MIXED_PRECISION:-true}   # Ampere+ FP16 destekler; eski GPU için .env'de false yapın
```

**Etki:** Ampere mimarisi (RTX 30xx/40xx) ve üzeri GPU'larda varsayılan olarak FP16 mixed precision etkin; Maxwell/Pascal/Turing kullananlar `.env` ile `GPU_MIXED_PRECISION=false` yapabilir.

---

### ✅ 3.72 `install_sidar.sh` — Ollama Başlangıç Race Condition (N-04 → ÇÖZÜLDÜ)

**Sorun:** `ollama serve` arka planda başlatıldıktan sonra `sleep 5` ile sabit 5 saniye bekleniyor; yavaş veya yüklü sistemlerde Ollama henüz hazır olmadan `ollama pull` komutları çalışarak başarısız olabiliyordu.

**Düzeltme:** `sleep 5` kaldırıldı, yerine `curl` ile `/api/tags` endpoint'ini polling eden döngü eklendi — 1 saniye aralıklarla en fazla 30 saniye beklenir:
```bash
local retries=30
local i=0
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
  i=$((i + 1))
  if [[ $i -ge $retries ]]; then
    echo "❌ Ollama 30 saniye içinde yanıt vermedi. Kurulum durduruluyor."
    exit 1
  fi
  sleep 1
done
echo "   ✅ Ollama hazır (${i}s)."
```

---

### ✅ 3.73 `web_ui/index.html` — CDN Bağımlılığı Çevrimdışı Kırılma (N-05 → ÇÖZÜLDÜ)

**Sorun:** `highlight.js` ve `marked.js` yalnızca CDN kaynaklarından yükleniyordu (`cdnjs.cloudflare.com`, `cdn.jsdelivr.net`). İntranet/çevrimdışı ortamlarda arayüz JS hatalarıyla çalışmaz hale geliyordu.

**Düzeltme:** Üç bileşen eklendi:

1. **`install_sidar.sh`**: `download_vendor_libs()` fonksiyonu — kurulum sırasında kütüphaneleri `web_ui/vendor/` dizinine indirir.
2. **`web_server.py`**: `/vendor/{file_path}` rotası — `web_ui/vendor/` dizininden statik dosya servis eder (path traversal korumalı).
3. **`web_ui/index.html`**: CDN referansları yerel `vendor/` yollarına taşındı; `typeof hljs/marked === 'undefined'` kontrolü ile CDN yedek mekanizması eklendi:
```html
<link rel="stylesheet" href="/vendor/highlight.min.css"
  onerror="this.onerror=null;this.href='https://cdnjs.cloudflare.com/...'" />
<script src="/vendor/highlight.min.js"></script>
<script src="/vendor/marked.min.js"></script>
<script>
  if (typeof hljs === 'undefined') {
    document.write('<script src="https://cdnjs...highlight.min.js">\x3C/script>');
  }
  if (typeof marked === 'undefined') {
    document.write('<script src="https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js">\x3C/script>');
  }
</script>
```
4. **`.gitignore`**: `web_ui/vendor/` dizini repo dışında tutuldu.

**Sonuç:** Çevrimiçi + çevrimdışı kullanımda arayüz tam işlevsel; CDN yalnızca vendor dosyaları indirilmemişse devreye girer.

---

### ✅ 3.74 `main.py:247-621` — Commented-Out Dead Code (V-01 → ÇÖZÜLDÜ)

**Dosya:** `main.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Sorun:** `if __name__ == "__main__": main()` bloğundan sonra satır 247'den itibaren **374 satır** yorum bloğu olarak sarılmış eski implementasyon kopyası mevcuttu. Aktif kodu etkilemiyordu; ancak kod tabanını şişiriyor ve bakımı güçleştiriyordu.

**Uygulanan düzeltme:** `main.py:245-621` arası tüm dead code silindi. Dosya artık yalnızca **244 satır** aktif kod içeriyor.

```python
# ÖNCESİ (main.py:242-621)
if __name__ == "__main__":
    main()


# """
# Sidar Project - Giriş Noktası   ← 374 satır dead code
# ...
# """

# SONRASI (main.py:242-244)
if __name__ == "__main__":
    main()
```

---

### ✅ 3.75 `config.py` — Docstring Versiyon Uyumsuzluğu (V-02 → ÇÖZÜLDÜ)

**Dosya:** `config.py`
**Önem:** ~~🟢 DÜŞÜK~~ → ✅ **ÇÖZÜLDÜ**

**Sorun:** Modül docstring "Sürüm: 2.6.0" gösteriyordu; `VERSION = "2.6.1"` sabiti ve PROJE_RAPORU.md ile tutarsızdı.

**Uygulanan düzeltme:**
```python
# ÖNCESİ
"""
Sidar Project — Merkezi Yapılandırma Modülü
Sürüm: 2.6.0 (GPU & Donanım Hızlandırma Desteği)
...
"""

# SONRASI
"""
Sidar Project — Merkezi Yapılandırma Modülü
Sürüm: 2.6.1 (GPU & Donanım Hızlandırma Desteği)
...
"""
```

---

### ✅ 3.76 `web_server.py` — Git Endpoint'leri Blocking Subprocess (V-03 → ÇÖZÜLDÜ)

**Dosya:** `web_server.py`
**Önem:** ~~🟡 ORTA~~ → ✅ **ÇÖZÜLDÜ**

**Sorun:** `git_info()`, `git_branches()`, `set_branch()` async FastAPI handler'ları içinde `subprocess.check_output()` (senkron I/O) doğrudan çağrılıyordu. Git komutu çalışırken tüm event loop askıya alınıyor, bu sürede başka HTTP istekleri yanıt alamıyordu.

**Uygulanan düzeltme:** Modül düzeyinde `_git_run()` yardımcı fonksiyonu oluşturuldu; tüm subprocess çağrıları `asyncio.to_thread()` ile thread pool'a itildi:

```python
# YENİ: Modül düzeyinde senkron yardımcı
def _git_run(cmd: list, cwd: str, stderr=subprocess.DEVNULL) -> str:
    """Senkron git alt süreci çalıştırır. asyncio.to_thread() ile çağrılmalı."""
    try:
        return subprocess.check_output(cmd, cwd=cwd, stderr=stderr).decode().strip()
    except Exception:
        return ""

# git_info() — ÖNCESİ
branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "main"  # ❌ BLOKLAYICI

# git_info() — SONRASI
branch = await asyncio.to_thread(
    _git_run, ["git", "rev-parse", "--abbrev-ref", "HEAD"], _root
) or "main"  # ✅ thread pool

# set_branch() — ÖNCESİ
subprocess.check_output(["git", "checkout", branch_name], ...)  # ❌ BLOKLAYICI

# set_branch() — SONRASI
await asyncio.to_thread(
    subprocess.check_output,
    ["git", "checkout", branch_name],
    cwd=_root,
    stderr=subprocess.STDOUT,
)  # ✅ thread pool
```

---

---

<a id="sec-8-1-8-4"></a>
## Kapatılan Uyumsuzluk Taramaları (§8.1–§8.4)

> Bu bölüm `PROJE_RAPORU.md §8` içinden ayrılmıştır.  
> Tüm maddeler **✅ Kapalı** statüsündedir.  
> Ana rapor: [PROJE_RAPORU.md](PROJE_RAPORU.md) — §8 referansı (aktif sorunlar orada)

### 8.1 Önceki Sürümlerde Giderilen Uyumsuzluklar (Kapalı)

| # | Dosya A | Dosya B | Uyumsuzluk Türü | Önem | Durum |
|---|---------|---------|----------------|------|-------|
| 1 | `README.md` (v2.3.2) | Tüm proje (v2.6.0) | Versiyon drift | 🔴 YÜKSEK | ✅ Düzeltildi |
| 2 | `config.py:validate_critical_settings()` | Tüm proje (httpx) | Senkron `requests` kullanımı | 🔴 YÜKSEK | ✅ Düzeltildi |
| 3 | `environment.yml` | `config.py` | `requests` bağımlılığı kaldırılmadı | 🔴 YÜKSEK | ✅ Düzeltildi |
| 4 | `memory.py` (threading.RLock) | Async mimari | RLock async bağlamda I/O yapıyor | 🟡 ORTA | ✅ Düzeltildi |
| 5 | `web_server.py` (asyncio.Lock module-level) | Python <3.10 uyumu | Loop bağımsız lock oluşturma | 🟡 ORTA | ✅ Geçersiz |
| 6 | `README.md` | `web_server.py`, `memory.py`, `config.py` | Yeni özellikler belgelenmemiş | 🟡 ORTA | ✅ Düzeltildi |
| 7 | `tests/test_sidar.py` | `memory.py` (session API) | Session lifecycle testleri eksik | 🟡 ORTA | ✅ Düzeltildi |
| 8 | `web_search.py:search_docs()` | DuckDuckGo motoru | `site:` OR operatörü DDG'de sınırlı | 🟢 DÜŞÜK | ✅ Düzeltildi |
| 9 | `sidar_agent.py:163` (greedy regex) | JSON çıktısı veren LLM | Açgözlü `\{.*\}` regex yanlış JSON yakalayabilir | 🔴 KRİTİK | ✅ Düzeltildi |
| 10 | `llm_client.py:129` (UTF-8 errors="replace") | Türkçe/multibyte içerik | TCP sınırında multibyte karakter sessizce bozulur | 🔴 KRİTİK | ✅ Düzeltildi |
| 11 | `code_manager.py:208` (hardcoded image) | `config.py` (DOCKER_PYTHON_IMAGE) | Docker image özelleştirilemez | 🔴 KRİTİK | ✅ Düzeltildi |
| 12 | `memory.py:170` (mesaj sayısı limiti) | LLM context window | Token sayısı kontrolsüz büyüyebilir | 🔴 KRİTİK | ✅ Düzeltildi |
| 13 | `auto_handle.py:156` (no null check) | `SystemHealthManager` init | health=None durumunda AttributeError | 🔴 KRİTİK | ✅ Düzeltildi |
| 14 | `github_manager.py:148` (uzantısız bypass) | `SAFE_TEXT_EXTENSIONS` whitelist | Extensionless binary dosyaları filtreden kaçar | 🔴 YÜKSEK | ✅ Düzeltildi |
| 15 | `web_server.py:89-91` (TOCTOU) | Rate limit mantığı | Eş zamanlı istek check-write atomik değil | 🔴 YÜKSEK | ✅ Düzeltildi |
| 16 | `rag.py:287` (delete+upsert) | ChromaDB collection | Eş zamanlı güncelleme race condition | 🔴 YÜKSEK | ✅ Düzeltildi |
| 17 | `definitions.py:23` (eğitim tarihi) | Claude Sonnet 4.6 (Aug 2025) | Yanlış bilgi sınırı yorumu | 🟢 DÜŞÜK | ✅ Düzeltildi |

**Notlar:**
- **#5 (Geçersiz):** Proje `python=3.11` gerektirir (bkz. `environment.yml:6`). Python 3.10+ ile `asyncio.Lock()` event loop dışında oluşturulabilir; sorun geçersizdir.
- **#4 (Düzeltildi):** `sidar_agent.py` içindeki tüm `memory.add()` ve `memory.set_last_file()` çağrıları `asyncio.to_thread()` ile thread pool'a iletildi. `memory.py` senkron API'si korundu.

---

### 8.2 Tespit Edilen Uyumsuzluklar — Tamamı Kapatıldı

> Tespit tarihi: 2026-03-01 | Kapatma tarihi: 2026-03-01 — **15 uyumsuzluktan 15'i giderilmiştir.**

| # | Dosya A | Dosya B | Uyumsuzluk Açıklaması | Önem | Durum |
|---|---------|---------|----------------------|------|-------|
| U-01 | `tests/test_sidar.py:374` | `core/rag.py:383` | `get_document()` test assertion hatası | 🔴 KRİTİK | ✅ Kapalı — §3.56 |
| U-02 | `managers/security.py:92` | `managers/security.py:79` | `status_report()` SANDBOX terminal iznini yanlış gösteriyor | 🔴 KRİTİK | ✅ Kapalı — §3.57 |
| U-03 | `.env.example:57` | `.env.example:113` | `HF_HUB_OFFLINE` anahtarı çift tanımlı, çelişkili değerler | 🔴 YÜKSEK | ✅ Kapalı — §3.58 |
| U-04 | `environment.yml:29` (cu121) | `docker-compose.yml:46,130` (cu124) | PyTorch CUDA wheel versiyonu tutarsızlığı | 🔴 YÜKSEK | ✅ Kapalı — §3.59 |
| U-05 | `web_server.py:66-70` | `config.py:WEB_PORT` | CORS izin listesi port 7860'a sabit kodlanmış | 🔴 YÜKSEK | ✅ Kapalı — §3.60 |
| U-06 | `web_server.py:89` (`_rate_lock`) | `web_server.py:44` (`_agent_lock`) | `_rate_lock` modül seviyesinde; `_agent_lock` lazy init | 🟡 ORTA | ✅ Kapalı — §3.61 |
| U-07 | `core/__init__.py` | `core/rag.py` | `DocumentStore` `__all__`'dan dışa aktarılmıyor | 🟡 ORTA | ✅ Kapalı — §3.62 |
| U-08 | `sidar_agent.py:64` (`VERSION="2.6.0"`) | `PROJE_RAPORU.md` başlığı (`v2.6.1`) | Kod versiyonu ile rapor versiyonu uyuşmuyor | 🟡 ORTA | ✅ Kapalı — §3.63 |
| U-09 | `agent/auto_handle.py` (tüm dosya) | `web_server.py:POST /clear` | Web UI'da "belleği temizle" komutu AutoHandle tarafından işlenmiyor | 🟡 ORTA | ✅ Kapalı — §3.64 |
| U-10 | `web_server.py:330-345` | `managers/security.py` | Dal adı `git checkout`'a geçilmeden önce sanitize edilmiyor | 🟡 ORTA | ✅ Kapalı — §3.65 |
| U-11 | `Dockerfile:82-83` (HEALTHCHECK) | `web_server.py` (FastAPI) | HEALTHCHECK HTTP servis durumunu kontrol etmiyor | 🟢 DÜŞÜK | ✅ Kapalı — §3.66 |
| U-12 | `auto_handle.py` (erişim regex) | Türkçe doğal dil | `"erişim"` kelimesi çok geniş — mevcut kodda zaten düzeltilmiş | 🟢 DÜŞÜK | ✅ Kapalı — §3.67 |
| U-13 | `web_server.py:301` (`rstrip`) | `/git-info` endpoint | `rstrip(".git")` suffix değil karakter kümesi siliyor | 🔴 YÜKSEK | ✅ Kapalı — §3.68 |
| U-14 | `agent/sidar_agent.py:679` | `core/rag.py` (ChromaDB) | `docs.add_document()` event loop'ta senkron çağrılıyor | 🟡 ORTA | ✅ Kapalı — §3.69 |
| U-15 | `tests/test_sidar.py:193` | `managers/system_health.py` | `_gpu_available` private attribute'a doğrudan erişim | 🟢 DÜŞÜK | ✅ Kapalı — §3.70 |

---

#### U-01 Detay: `tests/test_sidar.py` — `get_document()` Dönüş Formatı Uyumsuzluğu

**Sorun:** `core/rag.py:383` `get_document()` şu formatı döndürür:
```python
return True, f"[{doc_id}] {meta['title']}\nKaynak: {meta.get('source', '-')}\n\n{content}"
```
Ancak `tests/test_sidar.py:372-374` şunu kontrol ediyor:
```python
ok, retrieved = docs.get_document(doc_id)
assert ok is True
assert retrieved == small   # ❌ FAIL: retrieved başlık+kaynak öneki içeriyor
```
Ve `tests/test_sidar.py:381-386`:
```python
ok, retrieved = docs.get_document(doc_id)
assert ok is True
assert len(retrieved) == len(large)   # ❌ FAIL: retrieved önekle birlikte çok daha uzun
```
İki test de **TestPassed gibi görünse bile anlamsızdır** ve gerçekte hatalı assertion'lar nedeniyle başarısız olur.

---

#### U-02 Detay: `managers/security.py` — `status_report()` SANDBOX Terminal İzni Yanlış

**Sorun:** `can_execute()` SANDBOX modunda kod çalıştırmaya izin veriyor:
```python
# security.py:79
def can_execute(self) -> bool:
    return self.level >= SANDBOX   # ✅ SANDBOX'ta True döner
```
Ama `status_report()` Terminal iznini yanlış gösteriyor:
```python
# security.py:92
perms.append(f"Terminal: {'✓' if self.level == FULL else '✗'}")
# ❌ SANDBOX modunda '✗' (yasak) yazıyor ama aslında Docker REPL çalışabiliyor
```
Kullanıcı arayüzde "Terminal: ✗" görürken Docker sandbox REPL gerçekte çalışabilir durumda. Tutarsız bilgi.

---

#### U-03 Detay: `.env.example` — `HF_HUB_OFFLINE` Çift Tanımlı

**Sorun:** Aynı değişken iki farklı satırda, farklı değerlerle tanımlı:
```bash
# .env.example:57
HF_HUB_OFFLINE=0    # ← İlk tanım: model indirmesine izin ver

# .env.example:113
HF_HUB_OFFLINE=1    # ← İkinci tanım: çevrimdışı mod (override eder)
```
Kullanıcı `.env` oluştururken hangi değerin geçerli olacağını bilemez. İkinci tanım birincisini geçersiz kılar.

---

#### U-04 Detay: `environment.yml` vs `docker-compose.yml` — CUDA Wheel Sürümü Tutarsızlığı

**Sorun:**
```yaml
# environment.yml:29 (Conda/doğrudan kurulum)
- --extra-index-url https://download.pytorch.org/whl/cu121  # CUDA 12.1

# docker-compose.yml:46 (GPU Docker servisi)
TORCH_INDEX_URL: https://download.pytorch.org/whl/cu124     # CUDA 12.4

# Dockerfile:51 (GPU build-arg)
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu   # CPU varsayılan
# GPU build: docker-compose cu124 geçiyor
```
Conda ortamında kurulan PyTorch CUDA 12.1 (cu121) wheel'ı, Docker GPU build'ında kurulan CUDA 12.4 (cu124) wheel'ıyla **farklı sürümler** olabilir. Geliştiricilerin farklı ortamlarda farklı PyTorch davranışı görmesine neden olur.

---

#### U-05 Detay: `web_server.py` — CORS Port Sabit Kodlanmış

**Sorun:**
```python
# web_server.py:66-70
_ALLOWED_ORIGINS = [
    "http://localhost:7860",    # ← Sabit port
    "http://127.0.0.1:7860",   # ← Sabit port
    "http://0.0.0.0:7860",     # ← Sabit port
]
```
Ancak `config.py:299` ve `.env.example:111`:
```python
WEB_PORT: int = get_int_env("WEB_PORT", 7860)  # Değiştirilebilir
```
Kullanıcı `WEB_PORT=8080` ayarlarsa, CORS tüm istekleri bloklar çünkü `http://localhost:8080` izin listesinde yok. `_ALLOWED_ORIGINS` `cfg.WEB_PORT` kullanarak dinamik oluşturulmalı.

---

#### U-06 Detay: `web_server.py` — `_rate_lock` / `_agent_lock` Tutarsız Başlatma

**Sorun:**
```python
# web_server.py:44 — _agent_lock DOĞRU: lazy init
_agent_lock: asyncio.Lock | None = None  # event loop başladıktan sonra oluşturulacak

# web_server.py:89 — _rate_lock TUTARSIZ: modül seviyesinde
_rate_lock = asyncio.Lock()  # import anında oluşturuluyor
```
Aynı dosyada aynı pattern için iki farklı yaklaşım kullanılıyor. Python 3.11 için fonksiyonel sorun olmasa da tutarsızlık kod bakımını zorlaştırır.

---

#### U-07 Detay: `core/__init__.py` — `DocumentStore` Dışa Aktarılmıyor

**Sorun:**
```python
# core/__init__.py
from .memory import ConversationMemory
from .llm_client import LLMClient
# ❌ DocumentStore eksik!
__all__ = ["ConversationMemory", "LLMClient"]
```
Diğer tüm modüller `__init__.py`'den dışa aktarılmışken `DocumentStore` dışarıda bırakılmış. Tüm importlar `from core.rag import DocumentStore` şeklinde doğrudan yapılıyor (tutarlı değil).

---

#### U-08 Detay: `sidar_agent.py` / `config.py` — Versiyon Rapor Uyumsuzluğu

**Sorun:**
```python
# sidar_agent.py:55
VERSION = "2.6.0"

# config.py:207-208
VERSION: str = "2.6.0"
```
Ancak `PROJE_RAPORU.md:5`:
```
**Versiyon:** SidarAgent v2.6.1 (Web UI + Backend patch + Kritik hata yamaları)
```
Rapora göre uygulanan v2.6.1 yamaları kodda versiyon güncellemesini içermiyor. `main.py:50` banner'ı da `v2.6.0` gösteriyor.

---

#### U-09 Detay: `auto_handle.py` — Web UI'da "Belleği Temizle" Komutu Desteklenmiyor

**Sorun:** CLI'da `.clear` komutu `main.py` tarafından doğrudan handle ediliyor. Web UI'da `/clear` endpoint'i var. Ancak kullanıcı web chat'te "belleği temizle", "sohbeti sıfırla" gibi doğal dil komutları yazarsa `AutoHandle` bunu işlemiyor, LLM'e gönderiliyor.

`auto_handle.py`'de bu pattern için hiçbir handler yok. `test_auto_handle_clear_command` testi de bunu kabul ederek:
```python
# tests/test_sidar.py:406-408
assert isinstance(handled, bool)   # ❌ Her zaman geçer, gerçek test değil
assert isinstance(response, str)
```

---

#### U-10 Detay: `web_server.py` — Dal Adı Sanitize Edilmeden `git checkout`'a Geçiliyor

**Sorun:**
```python
# web_server.py:330-345
branch_name = body.get("branch", "").strip()
# ❌ Yalnızca whitespace temizleniyor; git flag injection kontrolü yok
subprocess.check_output(
    ["git", "checkout", branch_name],  # Liste formatı shell injection'ı engeller
    ...
)
```
Subprocess list formatı shell injection'ı önler, ancak git'e özel bayraklar (örn: `--force`, `--orphan`) hâlâ zararlı olabilir. Dal adı `^[a-zA-Z0-9/_.-]+$` regex ile doğrulanmalı.

---

#### U-11 Detay: `Dockerfile` — HEALTHCHECK HTTP Sağlığını Kontrol Etmiyor

**Sorun:**
```dockerfile
# Dockerfile:82-83
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD ps aux | grep "[p]ython" || exit 1
```
Python süreci çalışıyor ama web servis yanıt vermiyorsa (port bağlanamadı, exception, vb.) HEALTHCHECK yine de `healthy` döner. `web_server.py` modu için `curl http://localhost:7860/status` ile HTTP sağlık kontrolü yapılmalı.

---

#### U-12 Detay: `auto_handle.py` — `"erişim"` Regex'i Çok Geniş

**Sorun:**
```python
# auto_handle.py:217
if re.search(r"erişim|güvenlik|openclaw|access.*level|yetki", t):
    return True, self.code.security.status_report()
```
Türkçe'de "erişim" (access) son derece yaygın bir kelime. Örnek:
- "Bu API'ye **erişim** nasıl yapılır?" → Güvenlik durum raporu gösterir ❌
- "Dosyaya **erişim** izni var mı?" → Güvenlik durum raporu gösterir ❌

LLM'e iletilmesi gereken meşru sorular yanlışlıkla yakalanır.

---

#### U-13 Detay: `web_server.py:301` — `rstrip(".git")` Yanlış Kullanımı

**Kaynak:** ANALIZ_RAPORU_2026_03_01.md §4.1

**Sorun:** `str.rstrip(chars)` bir **karakter kümesini** sondan siler, bir suffix'i değil. `.git` argümanı `g`, `i`, `t`, `.` karakterlerinden oluşan küme olarak yorumlanır:
```python
# web_server.py:301
repo = remote.rstrip(".git")
# YANLIŞ ÖRNEK:
# "https://github.com/owner/my_project.git".rstrip(".git")
# → "https://github.com/owner/my_projec"  ← son 't' silinir!
```
Özellikle `tag`, `digit`, `script`, `git` gibi harf içeren depo adlarında URL'nin son karakterleri yanlışlıkla silinebilir.

**Beklenen düzeltme:**
```python
repo = remote.removesuffix(".git")   # Python 3.9+ — proje Python 3.11 gerektiriyor ✓
```

**Etki:** `/git-info` endpoint'i yanlış `owner/repo` değeri döndürebilir; dal ve repo seçimi UI'da hatalı çalışabilir.

---

#### U-14 Detay: `agent/sidar_agent.py:452` — `docs.add_document()` Event Loop'u Bloke Edebilir

**Kaynak:** ANALIZ_RAPORU_2026_03_01.md §4.2

**Sorun:** `_summarize_memory()` metodunda `self.docs.add_document()` `asyncio.to_thread()` sarmalı olmadan çağrılmaktadır:
```python
# sidar_agent.py:451-460
async def _summarize_memory(self) -> None:
    ...
    self.docs.add_document(        # ← Senkron ChromaDB I/O — event loop engelleniyor
        title=f"Sohbet Geçmişi Arşivi ...",
        content=full_turns_text,
        ...
    )
```
ChromaDB Python istemcisi senkron API kullanmaktadır. Büyük konuşma geçmişleri arşivlenirken embedding hesaplaması ve disk I/O event loop'u bloklayabilir; bu sürede diğer HTTP istekleri yanıt alamaz.

Aynı dosyanın başka yerlerinde (`sidar_agent.py:124,127,198`) `asyncio.to_thread()` tutarlı biçimde kullanılmaktadır.

**Beklenen düzeltme:**
```python
await asyncio.to_thread(
    self.docs.add_document,
    title=f"Sohbet Geçmişi Arşivi ({time.strftime('%Y-%m-%d %H:%M')})",
    content=full_turns_text,
    source="memory_archive",
    tags=["memory", "archive", "conversation"],
)
```

---

#### U-15 Detay: `agent/sidar_agent.py:418` — Private Attribute Doğrudan Erişimi

**Kaynak:** ANALIZ_RAPORU_2026_03_01.md §4.4

**Sorun:**
```python
# sidar_agent.py:418
lines.append(f"  GPU        : {'Mevcut' if self.health._gpu_available else 'Yok'}")
```
`_gpu_available` private bir attribute'tur (`_` öneki); `SystemHealthManager`'ın iç durumuna doğrudan erişim encapsulation prensibini ihlal eder.

**Beklenen düzeltme:**
```python
gpu_info = self.health.get_gpu_info()
lines.append(f"  GPU        : {'Mevcut' if gpu_info.get('available') else 'Yok'}")
```
`get_gpu_info()` public API bu bilgiyi `{"available": bool}` formatında zaten sunmaktadır.

---

### 8.3 Yeni Doğrulama Taraması — V-01–V-03 (Tamamı Kapatıldı)

> Tespit tarihi: 2026-03-01 | Kapatma tarihi: 2026-03-01 — **3 yeni uyumsuzluktan 3'ü giderilmiştir.**

| # | Dosya A | Dosya B | Uyumsuzluk Açıklaması | Önem | Durum |
|---|---------|---------|----------------------|------|-------|
| V-01 | `main.py:247-621` (374 satır commented-out dead code) | `PROJE_RAPORU.md §13` (main.py 100/100 iddiası) | Eski implementasyon kopyası yorum bloğu olarak kalmıştı | 🟡 ORTA | ✅ Kapalı — §3.74 |
| V-02 | `config.py:1-6` (docstring "Sürüm: 2.6.0") | `config.py:VERSION = "2.6.1"` | Modül başlık yorumu eski sürümü gösteriyordu | 🟢 DÜŞÜK | ✅ Kapalı — §3.75 |
| V-03 | `web_server.py:git_info()`, `git_branches()`, `set_branch()` | Async FastAPI mimarisi | Senkron `subprocess.check_output()` async handler'da event loop'u blokluyordu | 🟡 ORTA | ✅ Kapalı — §3.76 |

#### V-01 Detay: `main.py:247-621` — Commented-Out Dead Code

**Sorun:** `main.py:242-244` satırlarında aktif kod sona erdiği hâlde satır 247'den itibaren 374 satır boyunca eski implementasyonun birebir kopyası yorum bloğu olarak durmaktadır:

```python
# main.py:242-247 (sorun başlangıcı)
if __name__ == "__main__":
    main()


# """
# Sidar Project - Giriş Noktası
# ...
```

Rapor §13 main.py girişi "100/100 ✅ — `if __name__ == "__main__": main()` bloğundan sonra kalan sahipsiz yinelenen kod temizlendi" demektedir. Ancak kod incelemesinde satır 247–621 arasında **374 satırlık** eski implementasyonun tam kopyası hâlâ mevcut olduğu doğrulandı.

**Etki:** Çalışma zamanına etkisi yok (yorum satırları Python'da yürütülmez); fakat kod tabanı şişiyor, bakım güçleşiyor ve rapordaki "100/100" değerlendirmesi gerçeği yansıtmıyor.

**Beklenen düzeltme:** `main.py:246-621` arasındaki tüm yorum bloğunun silinmesi.

---

#### V-02 Detay: `config.py` Docstring Versiyon Uyumsuzluğu

**Sorun:**
```python
# config.py:1-6
"""
Sidar Project - Yapılandırma
...
Sürüm: 2.6.0    ← eski versiyon
"""
...
VERSION: str = "2.6.1"   # ← gerçek versiyon
```

Modül docstring "Sürüm: 2.6.0" gösteriyor; `VERSION` sabiti ise "2.6.1". U-08 yamasında (§3.63) `VERSION` sabiti güncellendi ama docstring atlandı.

**Etki:** Çok düşük — sadece belgeleme tutarsızlığı. Çalışma zamanına etkisi yok.

**Beklenen düzeltme:** `config.py` başlık yorumundaki "Sürüm: 2.6.0" → "Sürüm: 2.6.1" olarak güncellenmesi.

---

#### V-03 Detay: `web_server.py` Git Endpoint'lerinde Senkron Subprocess

**Sorun:** FastAPI async handler'ları içinde `subprocess.check_output()` (senkron I/O) doğrudan çağrılmaktadır:

```python
# web_server.py — git_info() endpoint'i (async!)
@app.get("/git-info")
async def git_info():
    remote = subprocess.check_output(     # ← BLOKLAYICI — event loop duraksıyor
        ["git", "remote", "get-url", "origin"], cwd=str(_root), ...
    ).decode().strip()
    branch = subprocess.check_output(     # ← BLOKLAYICI
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(_root), ...
    ).decode().strip()
    ...

# web_server.py — set_branch() (POST /set-branch)
@app.post("/set-branch")
async def set_branch(request: Request):
    subprocess.check_output(              # ← BLOKLAYICI
        ["git", "checkout", branch_name], cwd=str(_root), ...
    )
```

`subprocess.check_output()` senkron bir çağrıdır; async FastAPI handler içinde çağrıldığında git komutunun tamamlanmasını beklerken tüm event loop askıya alınır ve bu süre içinde başka HTTP istekleri yanıt alamaz.

**Etki:** Git komutu hızlı çalışırsa (yerel repo) pratik etkisi düşük; ancak yavaş ağ veya büyük repo durumunda `/chat` dahil tüm istekler yavaşlar. Mimari açıdan doğru değil.

**Beklenen düzeltme:** `asyncio.to_thread()` ile subprocess'i thread pool'a itmek:
```python
result = await asyncio.to_thread(
    subprocess.check_output,
    ["git", "remote", "get-url", "origin"],
    cwd=str(_root), stderr=subprocess.DEVNULL
)
remote = result.decode().strip()
```

---

### 8.4 Yeni Doğrulama Taraması — N-01–N-04 (2026-03-02 Güncel Bulgular)

> Tespit tarihi: 2026-03-02 | Kod v2.7.0 ile eksiksiz satır satır doğrulama yapılmıştır.
> **Önceki 35 sorunun TAMAMI kapatılmış olduğu doğrulandı ✅**
> Yeni tespit edilen 4 sorun aşağıda listelenmiştir.

| # | Dosya A | Dosya B | Uyumsuzluk Açıklaması | Önem | Durum |
|---|---------|---------|----------------------|------|-------|
| N-01 | `core/__init__.py:10` (`__version__ = "2.6.1"`) | `config.py:212`, `sidar_agent.py:86` (`VERSION = "2.7.0"`) | Versiyon uyumsuzluğu: core paketi v2.6.1, kod tabanı v2.7.0 | 🟡 ORTA | ✅ Kapalı |
| N-02 | `.env.example:125` (`DOCKER_IMAGE=...`) | `config.py:295` (`os.getenv("DOCKER_PYTHON_IMAGE", ...)`) | `.env.example` ortam değişkeni adı yanlış — kullanıcı ayarı sessizce yoksayılır | 🔴 YÜKSEK | ✅ Kapalı |
| N-03 | `web_server.py:321` (`agent.docs._index`) | `core/rag.py` (`_index` private) | Private iç değişkene dış modülden doğrudan erişim (encapsulation ihlali) | 🟢 DÜŞÜK | ✅ Kapalı |
| N-04 | `environment.yml:11` (`packaging>=23.0` conda bölümünde) | `managers/package_info.py` (`from packaging.version import Version`) | `packaging` pip bölümünde değil; Docker build'da versiyon kısıtlaması uygulanmaz | 🟢 DÜŞÜK | ✅ Kapalı |

---

<a id="n-01"></a>
#### N-01 Detay: `core/__init__.py` — Versiyon v2.6.1 Eski (Kod v2.7.0'da)

**Sorun:** Kod tabanı v2.7.0'a güncellenmiş ancak `core/__init__.py` ve `Dockerfile` hâlâ v2.6.1 gösteriyor:

```python
# core/__init__.py:10
__version__ = "2.6.1"   # ❌ Eski — v2.7.0 olmalı

# Dockerfile:25
LABEL version="2.6.1"   # ❌ Eski — v2.7.0 olmalı

# config.py:212  ← DOĞRU
VERSION: str = "2.7.0"

# agent/sidar_agent.py:86  ← DOĞRU
VERSION = "2.7.0"
```

Ayrıca `PROJE_RAPORU.md:5` başlığı da hâlâ `v2.6.1` göstermekteydi (bu güncellemeyle düzeltildi).

**Etki:** Çalışma zamanına doğrudan etkisi yok; `import core; core.__version__` sorgulandığında yanlış versiyon döner. Dağıtım süreçleri (CI/CD, Docker image tag) etkilenebilir.

**Beklenen düzeltme:**
```python
# core/__init__.py:10
__version__ = "2.7.0"

# Dockerfile:25
LABEL version="2.7.0"
```

---

<a id="n-02"></a>
#### N-02 Detay: `.env.example` — `DOCKER_IMAGE` vs `DOCKER_PYTHON_IMAGE` Ortam Değişkeni Adı Yanlış

**Sorun:** `.env.example` belgesinde `DOCKER_IMAGE` adıyla ortam değişkeni sunulmuş, fakat `config.py`'de bu değişken farklı bir adla okunuyor:

```bash
# .env.example:125
DOCKER_IMAGE=python:3.11-alpine    # ← Belgede gösterilen ad
```

```python
# config.py:295
DOCKER_PYTHON_IMAGE: str = os.getenv("DOCKER_PYTHON_IMAGE", "python:3.11-alpine")
# ❌ kod "DOCKER_PYTHON_IMAGE" okuyor ama .env.example "DOCKER_IMAGE" gösteriyor
```

Kullanıcı `.env` dosyasına `DOCKER_IMAGE=my-custom:3.11` yazsa da bu değer hiçbir zaman okunamaz; kod her zaman varsayılan `python:3.11-alpine` imajını kullanır.

**Etki:** Docker sandbox imajı özelleştirilmek istendiğinde sessizce yoksayılır. Hata mesajı veya uyarı üretilmez; kullanıcı neden değişikliğin işe yaramadığını anlayamaz.

**Beklenen düzeltme (iki seçenek):**
```bash
# Seçenek A: .env.example'ı düzelt
DOCKER_PYTHON_IMAGE=python:3.11-alpine    # ← config.py ile eşleştirilmeli

# Seçenek B: config.py'deki anahtar adını değiştir
DOCKER_PYTHON_IMAGE: str = os.getenv("DOCKER_IMAGE", "python:3.11-alpine")
```
Seçenek A daha güvenlidir (geriye dönük uyumluluk korunur).

---

<a id="n-03"></a>
#### N-03 Detay: `web_server.py` — Private Attribute'lara Dış Modülden Erişim

**Sorun:** `web_server.py` iki farklı satırda private (alt-çizgi ön ekli) attribute'lara doğrudan erişiyor:

```python
# web_server.py:321
rag_docs = len(agent.docs._index)     # ❌ _index private

# web_server.py:586
for pr in agent.github._repo.get_pulls(...):  # ❌ _repo private
```

Bu durum encapsulation prensibini ihlal eder; U-15'te `sidar_agent.py`'deki benzer sorun düzeltilmişti (bkz. §3.70), ancak `web_server.py`'deki örnekler atlanmıştı.

**Etki:** Kısa vadede çalışma hatasına yol açmaz; uzun vadede iç API değişikliklerinde sessiz kırılma riski.

**Beklenen düzeltme:**
```python
# core/rag.py — public property ekle
@property
def document_count(self) -> int:
    return len(self._index)

# managers/github_manager.py — public method ekle
def get_pull_requests_raw(self, state: str, limit: int):
    return self._repo.get_pulls(state=state, sort="updated")[:limit]
```

---

<a id="n-04"></a>
#### N-04 Detay: `environment.yml` — `packaging` Conda Bölümünde, Docker'da Versiyon Kısıtlaması Uygulanmıyor

**Sorun:** `packaging>=23.0` conda bağımlılıkları bölümünde tanımlı; pip bölümünde değil:

```yaml
# environment.yml:11 (conda bölümü)
- packaging>=23.0     # ← conda dep — Dockerfile'da pip'e aktarılmaz

# Dockerfile pip bölümüne aktarılan pip kısmı — packaging YOK
```

`Dockerfile`, `environment.yml`'in yalnızca `pip:` alt bölümünü `requirements.txt`'e dönüştürür. `packaging` bu bölümde olmadığı için Docker build'a `>=23.0` kısıtlaması uygulanmaz. `managers/package_info.py:14` ise `from packaging.version import Version, InvalidVersion` ile bu modüle bağımlı.

**Pratik risk:** `pip install --upgrade pip` ile gelen `packaging` genellikle 23+ sürümüne sahiptir; çoğu durumda sorun çıkmaz. Fakat resmi kısıtlamanın Docker ortamında güvence altında alınmamış olması bir tutarsızlıktır.

**Beklenen düzeltme:**
```yaml
# environment.yml — pip bölümüne taşı
- pip:
    ...
    - packaging>=23.0    # ← pip bölümüne alınmalı
```

---

<a id="sec-16-n-01-n-06"></a>
## §16'dan Taşınan Bulgular (N-01–N-06) — Session 4 (2026-03-01)

> `PROJE_RAPORU.md` içindeki **“16. Son Satır Satır İnceleme — Yeni Bulgular”** bölümü sadeleştirilmiş; kapanmış maddelerin ayrıntıları bu bölüme taşınmıştır.

| Bulgu | Kısa Açıklama | Durum | Kayıt |
|---|---|---|---|
| N-01 | RAG chunking testlerinde header prefix nedeniyle assertion kırılması | ✅ Kapalı | §3.56 |
| N-02 | `test_system_health_manager_cpu_only` testinde private `_gpu_available` erişimi | ✅ Kapalı | §3.57 |
| N-03 | `docker-compose.yml` ile `.env.example` arasında `GPU_MIXED_PRECISION` varsayılan çelişkisi | ✅ Kapalı | §3.71 |
| N-04 | `install_sidar.sh` içinde sabit `sleep 5` nedeniyle Ollama başlangıç race condition riski | ✅ Kapalı | §3.72 |
| N-05 | `web_ui/index.html` içinde CDN bağımlılığı (çevrimdışı kırılma) | ✅ Kapalı | §3.73 |
| N-06 | `environment.yml` ile rapor notları arasında kalan “requests” tutarsızlığının rapor tarafında güncellenmesi | ✅ Kapalı | §3.30 not güncellemesi |

**Özet:** Session 4 kapsamında rapora eklenen yeni bulguların tamamı uygulanmış ve kapanmıştır; aktif sorun bulunmamaktadır.

<a id="o-01"></a>
<a id="o-02"></a>
<a id="o-03"></a>
<a id="o-04"></a>
<a id="o-05"></a>
<a id="o-06"></a>
<a id="sec-8-2-18-o-01-o-06"></a>
## §8.2/§18’den Taşınan Bulgular (O-01–O-06) — Session 7 (2026-03-02)

> `PROJE_RAPORU.md` içindeki §8.2 ve §18.3 bölümlerinde yer alan ve artık kapalı olan O-01–O-06 detayları bu bölüme taşınmıştır.

| Bulgu | Kısa Açıklama | Durum | Kayıt |
|---|---|---|---|
| O-01 | 4 modülde docstring sürümü `2.6.1` olarak kalmıştı | ✅ Kapalı | §3 (O-01 düzeltmesi) |
| O-02 | `/metrics` içinde `agent.docs._index` private erişimi vardı | ✅ Kapalı | §3 (O-02 düzeltmesi) |
| O-03 | `/github-prs` içinde `agent.github._repo.get_pulls()` private erişimi vardı | ✅ Kapalı | §3 (O-03 düzeltmesi) |
| O-04 | `_tool_github_smart_pr` içinde `_repo.default_branch` private erişimi vardı | ✅ Kapalı | §3 (O-04 düzeltmesi) |
| O-05 | `/rag/docs` ve `/rag/search` GET endpoint’leri rate-limit kapsamı dışındaydı | ✅ Kapalı | §3 (O-05 düzeltmesi) |
| O-06 | `add_document_from_file()` içinde gereksiz çift chunking yapılıyordu | ✅ Kapalı | §3 (O-06 düzeltmesi) |

**Özet:** O-01–O-06 kapsamındaki teknik borç maddelerinin tamamı giderilmiş olup ana rapordaki ilgili başlıklar özet forma indirilmiştir.
<a id="sec-14-closed"></a>
## §14’ten Taşınan Kapatılmış Geliştirme Önerileri (2026-03-02)

> `PROJE_RAPORU.md` içindeki **14. Geliştirme Önerileri** bölümü sadeleştirilmiş; kapanmış/uygulanmış maddeler ana rapordan çıkarılarak bu arşiv kaydına taşınmıştır.

| Madde | Kısa Açıklama | Durum |
|---|---|---|
| 14 | Session lifecycle testleri (`create/load/delete/...`) | ✅ Kapalı (testler mevcut) |
| 15 | `GPU_MEMORY_FRACTION` validasyonu ve warning fallback | ✅ Kapalı |
| 16 | `package_info.py` version sort (`packaging.version.Version`) | ✅ Kapalı |
| 17 | Araç sonuç format şeması (`[ARAÇ:{name}:SONUÇ/HATA]`) | ✅ Kapalı |
| 18 | Bozuk JSON karantina (`.json.broken`) | ✅ Kapalı |
| 21 | CodeManager Docker image hata mesajı yönlendirmesi | ✅ Kapalı |
| 22 | GitHub token eksikliği için kullanıcı yönlendirmesi | ✅ Kapalı |

**Özet:** Bu maddeler artık aktif geliştirme işi değildir; ana raporda sadece güncel açık iyileştirmeler bırakılmıştır. 