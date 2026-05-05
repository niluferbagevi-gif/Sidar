# AGENTS.md

Bu dosya, `/workspace/Sidar` deposunda çalışan ajanlar için operasyonel rehberdir.
Kapsam: Bu dosyanın bulunduğu dizin ve tüm alt dizinler.

## 1) Amaç ve kapsam

`AGENTS.md` iki farklı ama tamamlayıcı alanı dokümante eder:

1. **Repo içi çalışma ajanları (multi-agent mimarisi)**
   - Kod, araştırma, inceleme, QA ve coverage gibi rol bazlı ajanlar.
2. **Codex skill kullanımı (çalıştırma yardımcıları)**
   - `SKILL.md` tabanlı sistem skill’lerinin ne zaman ve nasıl uygulanacağı.

> Not: Önceki sürümlerde içerik ağırlıklı olarak skills tarafını anlatıyordu. Bu sürümde
> repo içi gerçek ajan mimarisi de eklenmiştir.

---

## 2) Repo içi ajan mimarisi

### 2.1 Yerleşik ajan rolleri

`agent/roles/__init__.py` içinde dışa açılan yerleşik roller:

- `CoderAgent`
- `ResearcherAgent`
- `ReviewerAgent`
- `PoyrazAgent`
- `QAAgent`
- `CoverageAgent`

> Kaynak doğrulama notu: Bu listedeki rollerin **tek doğruluk kaynağı**
> `agent/roles/__init__.py` ve dekoratör kayıtlarıdır.

### 2.2 AgentCatalog kayıt sistemi

Ajanlar çalışma zamanında `agent/registry.py` içindeki `AgentCatalog` ile yönetilir.

- Dekoratör tabanlı kayıt:
  - `@AgentCatalog.register(capabilities=[...], description=..., version=..., is_builtin=...)`
  - Yeni yerleşik roller için `is_builtin=True` açıkça verilmelidir; decorator
    varsayılanı `False` olduğu için bu alan unutulursa rol metadata'sı yerleşik
    olmayan ajan gibi oluşur.  
- Programatik kayıt:
  - `AgentCatalog.register_type(...)`
  - Programatik kayıt varsayılanı geriye dönük uyumluluk nedeniyle `is_builtin=True`
    değerini kullanır; harici/çalışma zamanı eklenti rollerinde `is_builtin=False`
    açıkça verilmelidir.
- Keşif/üretim:
  - `AgentCatalog.get(role_name)`
  - `AgentCatalog.find_by_capability(capability)`
  - `AgentCatalog.list_all()`
  - `AgentCatalog.create(role_name, **kwargs)`

Yerleşik roller, `agent/registry.py` içindeki `_import_builtin_roles()` ile import edilerek
otomatik kaydedilir.

> Operasyonel kural: Yeni bir rol eklendiğinde hem `agent/roles/__init__.py` hem de
> `_import_builtin_roles()` listesi birlikte güncellenmelidir.

### 2.3 Roller, iş tanımları ve yetki sınırları

Bu bölümdeki rol sözleşmeleri, ilgili ajan dosyalarındaki
`@AgentCatalog.register(capabilities=[...])`, `SYSTEM_PROMPT` ve kayıtlı araçlarla
tutarlı tutulmalıdır. Kısa capability listesi tek başına yeterli değildir; her rol için
iş tanımı, kullanabileceği araç/yetki alanı ve diğer ajanlarla beklenen etkileşim
aşağıda belirtilir.

#### 2.3.1 `coder` — `CoderAgent`

- **İş tanımı:** Kod üretimi, dosya okuma/yazma, terminal destekli düzeltme ve teknik
  tasarım uygulama işlerinden sorumludur.
- **Temel yetenekler:** `code_generation`, `file_io`, `shell_execution`, `code_review`.
- **Yetki sınırı:** Üretim kodu ve test dosyalarında değişiklik yapabilir; riskli veya
  kapsamı belirsiz değişikliklerde reviewer/QA geri bildirimi beklenir.
- **Etkileşim:** `researcher` bulgularını uygulamaya dönüştürür; çıktısı
  `reviewer -> qa` akışından geçmelidir. Coverage açığı varsa `coverage` tarafından
  önerilen deterministik testleri projeye uyarlar.

#### 2.3.2 `researcher` — `ResearcherAgent`

- **İş tanımı:** Web, URL ve RAG/doküman kaynaklarından doğrulanabilir bilgi toplar;
  bulguları özetleyerek kod, pazarlama veya inceleme ekiplerine aktarır.
- **Temel yetenekler:** `web_search`, `rag_search`, `summarization`.
- **Araç/yetki alanı:** `web_search`, `fetch_url`, `search_docs` ve `docs_search`
  araçlarıyla araştırma yapar. Kod yazma/değiştirme rolü değildir; kaynak, tarih,
  belirsizlik ve varsayımları açıkça belirtmelidir.
- **Etkileşim:** Teknik karar gerektiren araştırmalarda `coder` ve `reviewer` için
  kaynaklı bağlam üretir. Kampanya, SEO veya hedef kitle çalışmaları için ham
  araştırmayı `poyraz` ajanına devreder.

#### 2.3.3 `reviewer` — `ReviewerAgent`

- **İş tanımı:** Kod kalitesi, güvenlik, mimari tutarlılık ve değişiklik kapsamı
  açısından inceleme yapar.
- **Temel yetenekler:** `code_review`, `security_audit`, `quality_check`.
- **Yetki sınırı:** Üretim değişikliğini onaylama/geri çevirme niteliğinde bulgu
  üretir; doğrudan uygulama rolü değildir.
- **Etkileşim:** `coder` çıktısını inceler, `qa` ve `coverage` bulgularının üretim
  davranışını bozmadığını doğrular. Pazarlama çıktılarında marka/güvenlik riski
  kontrolü için `poyraz` sonrasında çalışabilir.

#### 2.3.4 `qa` — `QAAgent`

- **İş tanımı:** Test stratejisi, CI hatası analizi ve kalite kapısı iyileştirmelerinden
  sorumludur.
- **Temel yetenekler:** `test_generation`, `ci_remediation`.
- **Yetki sınırı:** Test kapsamını genişletir ve CI düzeltmeleri önerir; coverage
  hedefleri için `coverage` ajanından gelen hotspot/finding listesini kullanır.
- **Etkileşim:** `coder` değişikliklerinden sonra smoke/unit/integration doğrulamayı
  planlar; kalıcı başarısızlıkları `reviewer` ve `coder` geri bildirimine dönüştürür.

#### 2.3.5 `coverage` — `CoverageAgent`

- **İş tanımı:** Pytest ve coverage çıktısını analiz ederek eksik senaryoları, kaçan
  branch/line noktalarını ve test hotspotlarını belirler; %100 coverage hedefine
  yaklaşmak için deterministik pytest testleri üretir.
- **Temel yetenekler:** `coverage_analysis`, `pytest_output_analysis`,
  `autonomous_test_generation`.
- **Araç/yetki alanı:** `run_pytest`, `analyze_pytest_output`,
  `analyze_coverage_report`, `analyze_test_artifacts`, `generate_missing_tests` ve
  `write_missing_tests` araçlarını kullanır. Dış servis/ağ bağımlılığına dayalı test
  üretmemeli; ürettiği testler reviewer onayına sunulabilecek şekilde deterministik
  olmalıdır.
- **Etkileşim:** `qa` ile coverage açığı kapatma döngüsünde çalışır; `coder` üretim
  davranışını bozmadan eksik testleri entegre eder; `reviewer` üretilen testlerin
  değerini, kırılganlığını ve güvenliğini kontrol eder.

#### 2.3.6 `poyraz` — `PoyrazAgent`

- **İş tanımı:** Dijital pazarlama, SEO, kampanya metni, funnel optimizasyonu, hedef
  kitle operasyonları, sosyal medya yayınlama ve içerik varlığı üretimi için uzman
  ajandır.
- **Temel yetenekler:** `marketing_strategy`, `seo_analysis`, `campaign_copy`,
  `audience_ops`.
- **Araç/yetki alanı:** `web_search`, `fetch_url`, `search_docs`, sosyal yayın
  araçları (`publish_social`, `publish_instagram_post`, `publish_facebook_post`,
  `send_whatsapp_message`), kampanya/landing page araçları
  (`build_landing_page`, `generate_campaign_copy`, `create_marketing_campaign`,
  `store_content_asset`) ve operasyon planlama araçlarını kullanır. Harici yayınlama
  veya müşteri iletişimi etkisi olan adımlarda konfigürasyon, onay ve platform
  kısıtları dikkate alınmalıdır.
- **Etkileşim:** `researcher` tarafından doğrulanan pazar/SEO bulgularını kampanya
  çıktısına dönüştürür. Teknik landing page veya entegrasyon gerekiyorsa `coder` ile,
  marka/güvenlik/kalite kontrolü gerekiyorsa `reviewer` ile çalışır.

### 2.4 Önerilen temel iş akışları

- Kod geliştirme akışı:
  - `researcher` (gerekiyorsa bağlam) -> `coder -> reviewer -> qa`
  - Coverage açığı varsa `coverage -> coder -> reviewer -> qa` iyileştirme döngüsü
    uygulanır.
- Araştırma tabanlı üretim akışı:
  - `researcher -> coder/reviewer`
- Pazarlama operasyon akışı:
  - `researcher -> poyraz -> reviewer`
  - Teknik kampanya/landing page değişikliği gerekiyorsa akışa `coder` ve `qa` eklenir.

---

## 3) Codex skills rehberi

Bu oturumdaki gerçek kullanılabilir skill listesi, çalışma zamanı tarafından sağlanan
`Available skills` bölümüdür. `AGENTS.md`, skill envanterinin tek doğruluk kaynağı
değildir; yalnızca `/workspace/Sidar` deposuna özel skill kullanım kurallarını,
tetikleme koşullarını ve bağlam hijyeni beklentilerini açıklar.

> Operasyonel kural: Belirli bir skill adı, yolu veya amacı dokümante edilecekse
> bilginin hızla bayatlayabileceği unutulmamalı; güncel kullanılabilirlik için her
> zaman oturumdaki `Available skills` çıktısı esas alınmalıdır.

### 3.1 Skill tetikleme kuralları

- Kullanıcı skill adını açıkça verirse (`$SkillName` veya düz metin) skill kullanılmalıdır.
- Kullanıcı isteği bir skill tanımıyla net eşleşiyorsa skill kullanılmalıdır.
- Birden fazla skill gerekiyorsa minimum gerekli set seçilmeli ve sıra belirtilmelidir.
- Skill bu turda tekrar anılmadıysa bir sonraki tura taşınmamalıdır.

### 3.2 Skill kullanım yöntemi (progressive disclosure)

1. İlgili `SKILL.md` dosyasını aç ve yalnızca gerekli kısmı oku.
2. Relative path’leri önce skill dizinine göre çöz.
3. `references/` gibi ek klasörlerden sadece gereken dosyaları yükle.
4. `scripts/` varsa uzun çıktıyı elle yazmak yerine script’i kullan.
5. `assets/templates` varsa yeniden üretmek yerine tekrar kullan.

### 3.3 Koordinasyon, bağlam hijyeni ve fallback

- Uzun metinleri kopyalamak yerine özetle; bağlamı küçük tut.
- Gereksiz derin referans zinciri açma.
- Skill uygulanamazsa sorunu kısa belirt ve en iyi alternatif yaklaşımı uygula.

---

## 4) Yeni ajan ekleme kısa rehberi

1. `agent/roles/` altında yeni ajan sınıfını oluştur.
2. `@AgentCatalog.register(...)` dekoratörüyle role/capability metadata’sını tanımla.
3. `agent/roles/__init__.py` içinde dışa aktar.
4. `agent/registry.py::_import_builtin_roles()` listesine yeni modülü ekle.
5. Ajanın rol adı, capability seti ve kullanım amacını dokümante et.
6. Testler ve entegrasyon kontrolleriyle kaydın çalıştığını doğrula (`AgentCatalog.list_all()` vb.).

Örnek şablon:

```python
from agent.base_agent import BaseAgent
from agent.registry import AgentCatalog

@AgentCatalog.register(
    capabilities=["example_capability"],
    description="Örnek uzman ajan",
    version="1.0.0",
    is_builtin=True,
)
class ExampleAgent(BaseAgent):
    ROLE_NAME = "example"
```

---

## 5) Doküman bakım notları

- Bu dosya **ajan + skill** kapsamını birlikte taşır; içerik adıyla uyumludur.
- Skill kullanılabilirliği için statik liste tutulmaz; güncel envanter çalışma zamanı `Available skills` çıktısından doğrulanmalıdır.
- Yeni role/capability eklendiğinde bu dosyanın 2. bölümünü güncelleyin.

### 5.1 Hızlı doğrulama checklist’i

Ön koşul: Aşağıdaki çalışma zamanı doğrulamaları **bağımlılıkları kurulmuş** bir ortamda
çalıştırılmalıdır. Temiz/çıplak repo checkout ortamında `python-dotenv`,
`pydantic-settings` vb. proje bağımlılıkları henüz yoksa `agent.registry`, yerleşik rol
modüllerini import ederken başarısız olabilir ve `AgentCatalog.list_all()` boş liste
döndürebilir. Bu durumda önce bağımlılıkları kurun:

- `python -m pip install -e .`
- Geliştirme/test araçları veya opsiyonel profiller gerekiyorsa ilgili extras ile kurulum yapın
  (örn. `python -m pip install -e ".[dev]"`).

Doğrulama adımları:

**1. Hızlı görünürlük/smoke kontrolü**

Aşağıdaki komut kullanılabilir; ancak yalnızca mevcut role adlarını basar ve tek
başına yeterli kabul edilmemelidir:

```bash
python -c "from agent.registry import AgentCatalog; print([s.role_name for s in AgentCatalog.list_all()])"
```

Çıktı `[]` ise öncelikle bağımlılık kurulumunu ve import uyarılarını kontrol edin.

**2. Fail-fast yerleşik rol doğrulaması**

Yerleşik rollerin eksiksiz yüklendiğini doğrulamak için aşağıdaki komut
çalıştırılmalıdır. Bu komut, boş liste veya eksik role durumlarını sessiz geçmez:

```bash
python - <<'PY'
from agent.registry import AgentCatalog

expected = {"coder", "researcher", "reviewer", "poyraz", "qa", "coverage"}
actual = {s.role_name for s in AgentCatalog.list_all()}
missing = expected - actual

if missing:
    raise SystemExit(f"Eksik built-in roller: {sorted(missing)}; actual={sorted(actual)}")

print("OK", sorted(actual))
PY
```

**3. Capability doğrulaması**

Capability listesinin dokümanla ve ajan dekoratörleriyle eşleştiğini doğrulamak
için aşağıdaki komut çalıştırılmalıdır:

```bash
python - <<'PY'
from agent.registry import AgentCatalog

expected = {
    "coder": {"code_generation", "file_io", "shell_execution", "code_review"},
    "researcher": {"web_search", "rag_search", "summarization"},
    "reviewer": {"code_review", "security_audit", "quality_check"},
    "qa": {"test_generation", "ci_remediation"},
    "coverage": {
        "coverage_analysis",
        "pytest_output_analysis",
        "autonomous_test_generation",
    },
    "poyraz": {"marketing_strategy", "seo_analysis", "campaign_copy", "audience_ops"},
}

actual = {s.role_name: set(s.capabilities) for s in AgentCatalog.list_all()}

for role, capabilities in expected.items():
    if role not in actual:
        raise SystemExit(f"Eksik rol: {role}")
    if actual[role] != capabilities:
        raise SystemExit(
            f"Capability mismatch for {role}: "
            f"expected={sorted(capabilities)} actual={sorted(actual[role])}"
        )

print("OK")
PY
```

**4. Statik tutarlılık kontrolleri**

- `agent/roles/__init__.py` içindeki dışa açılan roller ile
  `agent/registry.py::_import_builtin_roles()` listesi tutarlı olmalıdır.
- `AGENTS.md` içindeki capability listeleri, ilgili ajan dosyalarındaki
  `@AgentCatalog.register(capabilities=[...])` ile eşleşmelidir.

### 5.2 Ayrıştırma (SoC) yol haritası

- Doküman boyutu büyüdüğünde `Codex skills` kurallarını ayrı bir `SKILLS.md` dosyasına taşıyın.
- `AGENTS.md` dosyasını repo içi multi-agent mimari ve operasyonel standartlara odaklı tutun.
