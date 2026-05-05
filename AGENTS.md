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

### 2.3 Roller ve temel yetenekler

- **coder** (`CoderAgent`):
  - `code_generation`, `file_io`, `shell_execution`, `code_review`
- **researcher** (`ResearcherAgent`):
  - `web_search`, `rag_search`, `summarization`
- **reviewer** (`ReviewerAgent`):
  - `code_review`, `security_audit`, `quality_check`
- **qa** (`QAAgent`):
  - `test_generation`, `ci_remediation`
- **coverage** (`CoverageAgent`):
  - `coverage_analysis`, `pytest_output_analysis`, `autonomous_test_generation`
- **poyraz** (`PoyrazAgent`):
  - `marketing_strategy`, `seo_analysis`, `campaign_copy`, `audience_ops`

### 2.4 Detaylı rol tanımları, yetkiler ve etkileşim modeli

Bu bölüm, özellikle kod üretimi dışındaki uzman ajanların iş tanımı, operasyonel
yetki sınırları ve diğer ajanlarla beklenen el değiştirme noktalarını açıklar.
Yetenek listeleri için birincil kaynak ajan dosyalarındaki `@AgentCatalog.register(...)`
dekoratörleridir; araç/yetki listeleri ise ilgili sınıfların `register_tool(...)`
kayıtlarıyla uyumlu tutulmalıdır.

#### 2.4.1 ResearcherAgent (`researcher`)

- **İş tanımı:** Web, URL ve RAG/doküman kaynaklarından doğrulanabilir bilgi toplar;
  araştırma çıktısını özet, kaynak, risk ve belirsizlik notlarıyla birlikte sonraki
  ajana devreder.
- **Yetki ve sınırlar:** Kod veya repo dosyası değiştirmez; dış servis ya da doküman
  erişiminden gelen bilgiyi olduğu gibi uygulamak yerine doğrulanabilirlik ve
  güncellik uyarılarıyla raporlar.
- **Kayıtlı yetenekler:** `web_search`, `rag_search`, `summarization`.
- **Kullanabildiği araçlar:** `web_search`, `fetch_url`, `search_docs`, `docs_search`.
- **Etkileşim modeli:**
  - `researcher -> coder`: Teknik tasarım, API davranışı, ürün/alan bilgisi veya
    kaynaklı gereksinim notları sağlar.
  - `researcher -> poyraz`: Pazar, hedef kitle, SEO ve rekabet araştırması gibi
    pazarlama girdilerini teslim eder.
  - `researcher -> reviewer`: İnceleme sırasında doğrulanması gereken iddialar,
    kaynaklar ve belirsizlikleri bildirir.

#### 2.4.2 PoyrazAgent (`poyraz`)

- **İş tanımı:** Araştırma bulgularını pazarlama stratejisi, SEO önerisi, kampanya
  metni, landing page taslağı, hedef kitle operasyonu ve servis operasyon planına
  dönüştürür.
- **Yetki ve sınırlar:** Pazarlama ve sosyal medya operasyon araçlarını kullanabilir;
  yayınlama/mesaj gönderme gibi dış dünyaya etkisi olan araçlar için görev bağlamında
  açık onay, geçerli hesap yapılandırması ve marka/uyum kontrolü gerektirir.
- **Kayıtlı yetenekler:** `marketing_strategy`, `seo_analysis`, `campaign_copy`,
  `audience_ops`.
- **Kullanabildiği araçlar:** `web_search`, `fetch_url`, `search_docs`,
  `publish_social`, `publish_instagram_post`, `publish_facebook_post`,
  `send_whatsapp_message`, `build_landing_page`, `generate_campaign_copy`,
  `ingest_video_insights`, `create_marketing_campaign`, `store_content_asset`,
  `create_operation_checklist`, `plan_service_operations`.
- **Etkileşim modeli:**
  - `researcher -> poyraz`: Kaynaklı pazar/SEO/kitle içgörüleri alınır.
  - `poyraz -> reviewer`: Yayına, müşteri iletişimine veya marka algısına etki eden
    kampanya metinleri ve operasyon planları kalite/uyum kontrolüne gönderilir.
  - `poyraz -> coder`: Landing page veya kampanya entegrasyonu için gereken teknik
    değişiklikler iş paketine dönüştürülür.

#### 2.4.3 CoverageAgent (`coverage`)

- **İş tanımı:** Pytest ve coverage çıktılarını analiz ederek coverage açıklarını,
  eksik branch/line senaryolarını ve test önceliklerini belirler; deterministik pytest
  adayları üretip review akışına sunar.
- **Yetki ve sınırlar:** Test komutu çalıştırabilir ve önerilen test dosyalarına
  generated test yazabilir; üretilecek testler ağ erişimi veya dış servis bağımlılığı
  kullanmamalıdır. Üretilen testlerin `is_approved=False` /
  `pending_reviewer_or_human` durumuyla reviewer veya insan onayına gitmesi esastır.
- **Kayıtlı yetenekler:** `coverage_analysis`, `pytest_output_analysis`,
  `autonomous_test_generation`.
- **Kullanabildiği araçlar:** `run_pytest`, `analyze_pytest_output`,
  `analyze_coverage_report`, `analyze_test_artifacts`, `generate_missing_tests`,
  `write_missing_tests`.
- **Etkileşim modeli:**
  - `qa -> coverage`: Test çıktısı, coverage raporu veya CI başarısızlığı coverage
    açığına işaret ediyorsa analiz için devredilir.
  - `coverage -> reviewer`: Üretilen test adayı, hedef dosya, önerilen test yolu ve
    coverage bulguları onay için gönderilir.
  - `coverage -> coder/qa`: Onaylanan testler veya kalan coverage açıkları düzeltme
    ve regresyon döngüsüne aktarılır.

### 2.5 Önerilen temel iş akışları

- Kod geliştirme akışı:
  - `coder -> reviewer -> qa` (gerekirse `coverage` ile iyileştirme döngüsü)
- Araştırma tabanlı üretim akışı:
  - `researcher -> coder/reviewer`
- Pazarlama operasyon akışı:
  - `researcher -> poyraz -> reviewer`

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
