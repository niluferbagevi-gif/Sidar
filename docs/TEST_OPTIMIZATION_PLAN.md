# Test ve Kalite Koruma Planı (Sidar)

Bu belge, ulaşılan %100 line/branch coverage seviyesini korumak ve yeni geliştirmelerde regresyonu önlemek için **modül bazlı ve risk odaklı** bir yol haritası sunar.

> Not: Büyük projelerde %100 line coverage hedefi teknik olarak mümkün olsa da, sürdürülebilir kalite için tek metrik değildir. Öncelik; kritik iş akışları + hata patikaları + regresyon riski yüksek noktalar olmalıdır.


> **Bu dosya ne işe yarıyor?**
> Bu belge bir **uygulama rehberi / plan dokümanıdır**; test kodunun kendisi değildir.
> Yeni test yazarken birebir satır satır zorunlu bir "checklist" değil, **önceliklendirme ve karar desteği** sağlar.

### Bu plan nasıl kullanılmalı?

- Evet, testleri oluştururken **referans plan** olarak bunu takip edeceğim.
- Ancak uygulamada her PR’da yalnızca ilgili modülün bölümü ele alınır (hepsi birden değil).
- Kaynak dosya değiştikçe plan da güncellenir; yani yaşayan bir dokümandır.
- Planın başındaki metrikler (coverage, kırmızı/sarı liste, hedef eşikler) **her sprint başında coverage raporuna göre** güncellenir.

### Mevcut kalite geçidi ile hizalama (zorunlu not)

- Repo’daki `.coveragerc` ayarına göre güncel global kalite geçidi `fail_under = 90` olarak uygulanır.
- `run_tests.sh` içinde de varsayılan eşik `COVERAGE_FAIL_UNDER=90` olarak tanımlıdır.
- Bazı üst seviye raporlarda `%100` kalite geçidi ifadesi geçse bile, **çalışan teknik doğruluk kaynağı** CI çalıştırdığı dosyalardır (`.coveragerc`, `run_tests.sh`, `.github/workflows/ci.yml`).
- Bu nedenle aşağıdaki “kademeli hedefler”, global gate’in alternatifi değil; **modül bazlı iyileştirme hedefi** olarak yorumlanmalıdır.

### Proje Ekibine Aksiyon Notu (2026-04-08)

- Test yazarken `%100` geneline odaklanarak sprint kapasitesini tüketmeyin; modül bazlı kademeli hedefleri takip edin (`%70 -> %80 -> %90+`).
- `.coveragerc` içinde `omit` edilen dosyalar (örn. `core/vision.py`, `core/voice.py`) için coverage artırma işi açmayın; yalnızca fonksiyonel/regresyon ihtiyacı varsa test ekleyin.
- Sprint başında hedef modül listesi oluşturun, sprint sonunda sadece bu modüller için line/branch ilerleme raporu çıkarın.

### Testleri sıfırdan yazma (greenfield) yaklaşımı

Bu planda dolaylı olarak var; ayrıca net kural seti aşağıdadır:

1. Önce **kritik akış listesi** çıkar (giriş noktası, yan etki, hata etkisi).
2. Her akış için önce **başarılı senaryo**, sonra en az bir **hata senaryosu** yaz.
3. Dış bağımlılıkları (LLM/API/DB/ağ/zaman) gerçek çağrı yerine mock/stub/fake ile izole et.
4. Testleri `Arrange-Act-Assert` formatında kısa tut; tek test tek davranış doğrulasın.
5. Modül tamamlandığında branch coverage raporundan eksik `if/else` ve `except` bloklarını kapat.
6. Son adımda entegrasyon testi ekleyip modülün diğer bileşenlerle uyumunu doğrula.

Önerilen minimum şablon (sıfırdan başlarken):
- `tests/unit/<modul>/test_<davranis>.py`
- `tests/integration/<modul>/test_<akis>.py`
- Ortak fixture: `tests/conftest.py`

Parçalanmayı önleme kuralları (zorunlu):
- Aynı modül için `test_*_improvements.py`, `test_*_runtime.py`, `test_quick_*` benzeri
  ad-hoc dosyalar açılmamalıdır.
- Mevcut bir modül dosyası varken yeni testler önce o dosyaya eklenmeli; sadece açık bir
  sorumluluk ayrımı varsa ikinci dosya açılmalıdır.
- Geçici coverage artırma dosyaları kalıcı hale getirilmeden önce modül bazlı dosyaya
  taşınmalı ve eski dosya silinmelidir.

> Uygulama notu (2026-04-09): `sidar_agent` testleri tekilleştirilmiş yapı olarak
> `tests/unit/agent/test_sidar_agent.py` altında tutulur.

---

## 1) Stratejik Hedefler

1. **Önce koruma seviyesini sürdür**: yeni/değişen kodda coverage düşüşünü engelleyecek smoke + hata senaryolarını aynı PR içinde tamamla.
2. **Riskli değişiklikleri derinleştir**: edge-case ve exception akışlarıyla regresyon ihtimali yüksek patikaları güçlendir.
3. **Dış bağımlılık izolasyonu**: ağ, saat, dosya sistemi, LLM çağrıları deterministik mock/stub ile sabitlenmeli.
4. **Coverage ajanı + HITL akışı**: Sprint önceliklerine göre Coverage Agent hedef dosyaları analiz edip taslak test üretebilir; bu çıktılar CI’a girmeden önce Reviewer Agent veya insan geliştirici onayından (HITL) geçmelidir.
5. **Katmanlı test mimarisi**:
   - Unit (hızlı, yoğun mock)
   - Integration (in-memory DB / local adapter)
   - E2E (az sayıda kritik uçtan uca akış)
6. **Kapsam dışı modül farkındalığı**: `.coveragerc` içinde `omit` edilen dosyalar (örn. `core/vision.py`, `core/voice.py`, `web_ui_react/*`, `migrations/*`) için coverage artışı hedefi konmaz; sadece fonksiyonel/regresyon ihtiyacı varsa test yazılır.

### 1.1 Mevcut güçlü mimari yapı (korunacak pratikler)

Bu bölüm, projede hâlihazırda iyi çalışan test/kurulum kararlarını netleştirir:

- **Docker Compose ile izole stateful servisler:** PostgreSQL ve Redis’in host ortamdan ayrıştırılarak compose ile çalıştırılması, yerel geliştirme ile CI davranışını hizalar ve kurulum karmaşıklığını azaltır.
- **DDoS/rate-limit smoke kapsaması:** `test_boot_health_probes_bypass_ddos_redis_rate_limit` benzeri testler, sistemin açılış/health davranışı ile koruma katmanlarını birlikte doğruladığı için erken regresyon yakalama açısından kritiktir.
- **Testcontainer tabanlı DB izolasyonu:** `tests/conftest.py` içindeki `PostgresContainer` kullanımı, testler arası veri sızıntısını azaltır ve flaky davranışı düşürür.
- **FakeAsyncRedis ile deterministik Redis testleri:** `fakeredis.FakeAsyncRedis` ile düşük maliyetli, hızlı ve internetsiz/servissiz test koşumu sağlanır.
- **`TEST_REDIS_DECODE_RESPONSES` uyumu:** Testteki decode davranışının konfigürasyonla değiştirilebilir olması, üretimde görülebilecek `str/bytes` farklılıklarından doğan hataları daha erken yakalamaya yardımcı olur.

> Operasyonel öneri: Bu pratikler “değiştirilebilir tercih” değil, proje kalite taban çizgisi olarak ele alınmalı ve yeni test altyapısı işlerinde geriye dönük korunmalıdır.

---

## 2) Önceliklendirme Matrisi

### A) Düşük Coverage Modüller (Kırmızı Bölge)

> Not: Bu bölümdeki liste “örnek”tir. Kesin öncelik sırası, son coverage raporundan otomatik üretilen tabloya göre belirlenmelidir.

#### Ajan sistemi (`agent/`)
Örnek dosyalar: `sidar_agent.py`, `swarm.py`, `auto_handle.py`, `reviewer_agent.py`, `coverage_agent.py`, `poyraz_agent.py`

Test yaklaşımı:
- Agent oluşturma, karar/routing akışını doğrulama.
- LLM yanıtlarını mock ederek farklı karar kombinasyonlarını tetikleme.
- Doğru tool çağrısı ve EventStream çıktısını assertion ile doğrulama.
- Hata akışları: invalid tool response, timeout, boş/bozuk model yanıtı.
- Coverage Agent için: hedef dosya seçimi, test taslağı üretimi ve onay/HITL zorunluluğu akışını test et.
- Uzman ajanlar (Poyraz vb.) için: sosyal medya ve medya analizi yeteneklerinde auth/rate-limit/bozuk payload akışlarını ayrı test et.

Önerilen fixture’lar:
- `fake_llm_response`
- `fake_event_stream`
- `agent_factory`
- `fake_social_api`
- `fake_video_stream`

#### Web sunucusu ve arayüz girişleri
Örnek dosyalar: `web_server.py`, `main.py`, `cli.py`, `gui_launcher.py`

> **Fazlama notu (2026-04-03):** `web_server.py` çok büyük bir dosya olduğu ve ~1533 eksik satır içerdiği için, tek PR içinde agresif coverage artışı maliyetlidir. Verimlilik için bu dosya sonraki fazlara bırakılmalı; mevcut sprintte küçük/orta ölçekli modüller (agent rolleri ve manager katmanı) önceliklendirilmelidir.

Test yaklaşımı:
- API endpoint testleri için `FastAPI TestClient` (veya mevcut framework’ün async test client’ı).
- Doğrulama başlıkları, authorization ve schema doğrulaması.
- 2xx + 4xx + 5xx senaryoları (özellikle validation ve internal error path).
- CLI komutları için `click.testing.CliRunner` ile argüman/hata simülasyonu.

#### Coverage’ı düşük manager’lar
Örnek dosyalar: `system_health.py`, `todo_manager.py`, `web_search.py`, `package_info.py`

Test yaklaşımı:
- Dış servis çağrılarını (`httpx`, entegrasyon SDK’ları) mock ile kes.
- Başarılı cevap, timeout, rate-limit, malformed payload senaryoları.
- `system_health` için metric toplama fallback davranışlarını test et.

---

### B) Kısmi Coverage Modüller (Sarı/Turuncu Bölge)

#### `core/db.py`
Odak:
- CRUD hata patikaları (invalid input, conflict, timeout, transaction rollback).
- `IntegrityError` / bağlantı kesintisi / retry davranışı.

Test yaklaşımı:
- Unit seviyede repository fonksiyonlarını izole test et.
- Integration seviyede `tmp_path` destekli dosya tabanlı geçici veritabanı (`aiosqlite`) ile transaction akışlarını doğrula.

#### `core/llm_client.py`
Odak:
- Provider bazlı dallanmalar (OpenAI/Anthropic/Gemini vb.).
- Context limit, rate-limit ve provider error mapping.

Test yaklaşımı:
- Provider çağrılarını `unittest.mock.patch` veya `pytest-mock` ile kes.
- Uzun prompt, boş prompt, invalid model, retry/backoff akışlarını ayrı testle.

#### `core/rag.py`
Odak:
- Chunking sınırları, boş input, çok büyük input.
- Retrieval boş dönmesi, vector DB erişim hataları.

Test yaklaşımı:
- Küçük deterministik fixture dokümanlar.
- Vector store adapter mock’ları ile hem hit hem no-hit durumları.

#### `managers/code_manager.py`
Odak:
- Dosya/klasör I/O edge case’leri.
- `PermissionError`, `FileNotFoundError`, encoding sorunları.

Test yaklaşımı:
- `tmp_path` ile izole dosya sistemi testleri.
- İzin ve hata senaryoları için controlled monkeypatch.

#### v5.x ile eklenen kritik modüller (`core/`)
Örnek dosyalar: `entity_memory.py`, `cost_routing.py`, `lsp.py`, `semantic_cache.py`

Odak:
- `entity_memory.py`: kullanıcı kimliği/personalization eşleme, TTL, bozuk kayıt geri kazanımı.
- `cost_routing.py`: model seçimi eşikleri, fallback/fail-closed davranışı, yanlış sınıflandırma sınırları.
- `lsp.py`: timeout, dil sunucusu unavailable, parse/diagnostic dönüşüm hataları.
- `semantic_cache.py`: cache hit/miss, benzerlik eşiği, Redis bağlantı kesintisi ve fallback.

Test yaklaşımı:
- Deterministik fixture + fake adapter (Redis/LSP/Router).
- Başarılı + hata + degrade modlarını ayrı testlerle doğrula.
- Özellikle routing/caching kararlarında yan etki assertion’ları (seçilen provider, cache anahtarı, TTL) ekle.

---

## 3) Uygulama Takvimi (Sprint Bazlı)

### Sprint 1 — Stabil temel
- Dış bağımlılık mock altyapısı ve ortak fixture seti.
- Düşük coverage modüller için smoke testler.
- Coverage Agent / test-oluşturucu agent workflow’unun, en az smoke seviyede deterministik test taslağı üretebildiğinin doğrulanması.
- CI’da hızlı test job’ı (kritik unit set).

### Sprint 2 — Kritik path derinleştirme
- `core/db.py`, `core/llm_client.py`, `core/rag.py` hata patikaları.
- Branch coverage artışı için `if/else` ve `try/except` odaklı testler.

### Sprint 3 — Sertleştirme
- Regresyon test seti ve flaky test temizliği.
- Nightly tam koşu + coverage trend raporu.

---

## 4) Teknik Kurallar (Zorunlu)

1. **Network bağımsız test**: Unit testler internetsiz çalışmalı.
2. **Deterministiklik**: Rastgelelik/saat bağımlılığı fixture ile sabitlenmeli.
3. **Küçük ve amaç odaklı test**: Her test tek davranışı doğrulamalı.
4. **Hata mesajı doğrulaması**: Sadece exception tipi değil, anlamlı mesaj/alanlar da assert edilmeli.
5. **Regresyon etiketi**: Bulunan bug için önce test, sonra düzeltme.
6. **Agent-üretimli test güvenliği**: Coverage Agent tarafından üretilen testler doğrudan merge edilmez; Reviewer Agent/HITL onayı zorunludur.
7. **Platform-özel mock standardı**: Instagram/WhatsApp/YouTube benzeri uzman ajan entegrasyonlarında auth, quota/rate-limit ve servis kesintisi senaryoları için ayrı fake adapter kullanılmalıdır.

---

## 5) Örnek Test İskeleti

```python
import pytest
from unittest.mock import patch


def test_llm_client_rate_limit_maps_to_domain_error(llm_client):
    with patch("core.llm_client.provider_call") as mocked:
        mocked.side_effect = RuntimeError("rate limit")

        with pytest.raises(RuntimeError, match="rate limit"):
            llm_client.complete("hello")
```

---

## 6) CI / Quality Gate Önerisi

- PR pipeline:
  - `pytest -m "not slow"` ile hızlı unit + kritik integration
  - değişen dosyalara hedefli coverage raporu (line + branch)
  - global quality gate: coverage `%90` altına düşerse fail
- Nightly pipeline:
  - full suite (`pytest`)
  - coverage trend karşılaştırması
  - flaky test raporu

Tek adımda `%100` yerine, modül bazlı **kademeli iyileştirme hedefi** uygulanmalı (mevcut global gate `%90` ile uyumlu):
- Faz 1: `%70`
- Faz 2: `%80`
- Faz 3: `%90+`
- Faz 4: risk-temelli hedef coverage (modül kritikliğine göre farklı eşik)

Önemli:
- Bu fazlar global `%90` gate’i düşürmez; yalnızca düşük coverage alanlarını planlı biçimde iyileştirmek için takip edilir.
- Eğer gelecekte teknik kaynaklar (`.coveragerc` + CI) gerçekten `%100` gate’e yükseltilirse, bu fazlar doğrudan `%100` hedefli yeniden kalibre edilmelidir.

---

## 7) Operasyonel Takip Alanları (Yeni)

Her sprintte aşağıdaki tablo güncellenmelidir:

| Modül | Mevcut Line% | Mevcut Branch% | Hedef | Sorumlu | Hedef Sprint | Durum |
|---|---:|---:|---:|---|---|---|
| `agent/*` | 100% | 100% | 90+ | Ekip | S1-S2 | completed |
| `core/llm_client.py` | 100% | 100% | 90+ | Ekip | S2 | completed |
| `core/rag.py` | 100% | 100% | 90+ | Ekip | S2 | completed |
| `core/entity_memory.py` | 100% | 100% | 90+ | Ekip | S2-S3 | completed |
| `core/cost_routing.py` | 100% | 100% | 90+ | Ekip | S2-S3 | completed |
| `core/lsp.py` | 100% | 100% | 85-90+ | Ekip | S3 | completed |
| `core/semantic_cache.py` | 100% | 100% | 90+ | Ekip | S2-S3 | completed |
| `managers/*` (kritik) | 100% | 100% | 85-90+ | Ekip | S1-S3 | completed |

> Operasyon notu (2026-04-07): `tests/conftest.py` içine Sprint-1 ortak fixture setinin ilk sürümü eklendi (`fake_llm_response`, `fake_event_stream`, `agent_factory`, `fake_social_api`, `fake_video_stream`) ve v5.x konfig anahtarları test config'e dahil edildi. `run_tests.sh` içinde coverage çağrısı açık hedeflerle sertleştirildi; benchmark için fail-safe davranış `RUN_BENCHMARKS=required` modu ile aktif edilebilir.

---

## 8) Tutarlılık Kontrol Notu (2026-04-05)

Bu plan, mevcut repo durumu ile çapraz kontrol edilerek güncellenmiştir:

- Global gate bugün için `%90` (`.coveragerc` + `run_tests.sh`).
- `%100 enforced` ifadesi taşıyan raporlar, teknik konfigürasyonla çelişiyorsa referans değil bilgilendirme olarak değerlendirilmelidir.
- `omit` kapsamı plan içine açık operasyon kuralı olarak eklenmiştir.
- v5.x ile gelen kritik `core/*` modülleri test öncelik matrisine dahil edilmiştir.

---

## 9) Beklenen Çıktılar

- Daha hızlı ve deterministik test suite.
- Kritik iş akışlarında yüksek güven.
- Coverage artışıyla birlikte gerçek regresyon yakalama oranında artış.
- Bakımı zor “gösteriş” testleri yerine sürdürülebilir kalite güvence katmanı.
