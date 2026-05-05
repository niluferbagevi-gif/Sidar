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

Aşağıdaki özet, `agent/roles/*.py` içindeki `@AgentCatalog.register(...)`
dekoratörleriyle senkron tutulmalıdır. Rol açıklamaları yalnızca isim listesi değil,
operasyon sırasında hangi ajanın hangi sınırda kalacağını da belirtir.

- **coder** (`CoderAgent`):
  - Capability seti: `code_generation`, `file_io`, `shell_execution`, `code_review`
  - Görevi: Kod üretimi/değişikliği, dosya işlemleri, güvenli shell komutları ve ilk
    seviye kod öz denetimi. Reviewer veya QA geri bildirimi geldiyse revizyonu uygular.
- **researcher** (`ResearcherAgent`):
  - Capability seti: `web_search`, `rag_search`, `summarization`
  - Görevi: Web/RAG kaynaklarından doğrulanabilir bilgi toplamak, kaynak özetlemek ve
    coder/reviewer/poyraz rollerine bağlam sağlamak. Kod veya repo dosyası değiştirmez.
- **reviewer** (`ReviewerAgent`):
  - Capability seti: `code_review`, `security_audit`, `quality_check`
  - Görevi: PR/issue/repo inceleme, LSP ve güvenlik sinyallerini değerlendirme, browser
    sinyallerini yorumlama ve P2P geri bildirimle coder/coverage/qa akışını yönlendirme.
- **qa** (`QAAgent`):
  - Capability seti: `test_generation`, `ci_remediation`
  - Görevi: Hedefli test üretimi, CI hata özetinden remediation planı oluşturma ve
    reviewer onayı için deterministik test çıktısı hazırlama.
- **coverage** (`CoverageAgent`):
  - Capability seti: `coverage_analysis`, `pytest_output_analysis`, `autonomous_test_generation`
  - Görevi: `coverage.xml`, pytest çıktısı ve `.coveragerc` bilgisinden eksik senaryoları
    bulmak; ağ/dış servis bağımlılığı olmayan pytest adayları üretmek; %100 coverage
    hedefi için reviewer/qa döngüsüne veri sağlamak.
- **poyraz** (`PoyrazAgent`):
  - Capability seti: `marketing_strategy`, `seo_analysis`, `campaign_copy`, `audience_ops`
  - Görevi: SEO, kampanya metni, hedef kitle, sosyal yayın, landing page ve video insight
    gibi dijital pazarlama operasyonlarını yürütmek; gerektiğinde researcher kaynakları ve
    multimodal video özetlerini kullanmak.

#### 2.3.1 Rol sorumlulukları, araç sınırları ve devir kuralları

- **Researcher çıktı sınırı:** Researcher `web_search`, `fetch_url`, `search_docs` ve
  `docs_search` araçlarıyla doğrulanabilir kaynak/özet üretir; kod, test veya repo dosyası
  değiştirmez. Kod değişikliği gerekiyorsa bağlamı `coder` veya `reviewer` rolüne devreder.
- **Poyraz araç sınırı:** Poyraz pazarlama stratejisi, SEO, kampanya metni, landing page,
  sosyal yayın, WhatsApp/Facebook/Instagram operasyonları ve `ingest_video_insights`
  gibi multimodal pazarlama girdileriyle çalışır. Teknik kod değişikliği veya güvenlik
  kararı gerekiyorsa sonucu `reviewer`/`coder` hattına aktarır.
- **Coverage devir kuralı:** Coverage `run_pytest`, `analyze_pytest_output`,
  `analyze_coverage_report`, `analyze_test_artifacts`, `generate_missing_tests` ve
  `write_missing_tests` araçlarıyla coverage gap analizi ve deterministik pytest adayı
  üretir. Yüksek riskli test yazımı, fixture değişikliği veya üretim koduna dokunan
  düzeltmeler `qa -> reviewer -> coder` kontrolünden geçmelidir.
- **Reviewer kalite kapısı:** Reviewer, LSP/security/browser/test sinyallerini birleştirir;
  red/revizyon kararını P2P geri bildirim olarak üretir. Reviewer onayı olmadan riskli
  self-heal, browser aksiyonu, sosyal yayın veya üretim kodu değişikliği tamamlanmış
  kabul edilmez.

### 2.4 Önerilen temel iş akışları

- Kod geliştirme akışı:
  - `coder -> reviewer -> qa` (gerekirse `coverage` ile iyileştirme döngüsü)
- Araştırma tabanlı üretim akışı:
  - `researcher -> coder/reviewer`
- Pazarlama operasyon akışı:
  - `researcher -> poyraz -> reviewer`
- Coverage iyileştirme akışı:
  - `coverage -> qa -> reviewer -> coder`

### 2.5 Supervisor, swarm ve event-driven koordinasyon

Sidar ajanları yalnızca doğrusal pipeline olarak çalışmaz; görev türüne göre iki
orkestrasyon katmanı kullanılır:

- **Supervisor merkezli yönlendirme** (`agent/core/supervisor.py`):
  - Intent tespit eder ve görevi `researcher`, `reviewer`, `poyraz`, `coverage` veya
    `coder` rolüne yönlendirir.
  - Kod akışında `coder -> reviewer` zincirini çalıştırır; reviewer revizyon isterse
    P2P geri bildirimle coder'a yeni tur açar.
  - `MAX_QA_RETRIES` ve `MAX_TURNS` sınırlarıyla retry/circuit breaker davranışını korur;
    bu limitler aşılırsa P2P akışı güvenli şekilde durdurulmalıdır.
  - `DelegationRequest` sözleşmesiyle P2P handoff derinliğini ve hedef ajanı doğrular.
- **Swarm orkestrasyonu** (`agent/swarm.py`):
  - `SwarmTask(intent=...)` değerini `AgentCatalog` capability metadata'sına göre route eder.
  - Paralel görev, ardışık pipeline, direct handoff, loop guard ve supervisor fallback
    davranışlarını içerir.
  - Dağıtık senaryoda `AsyncDelegationBackend` enjekte edilerek broker/kuyruk tabanlı
    task dispatch yapılabilir; test/prototip için `InMemoryDelegationBackend` vardır.
- **Event bus altyapısı** (`agent/core/event_stream.py`, `agent/core/event_backends/`):
  - Process içi fanout her zaman çalışır; broker yoksa operasyon local/in-memory sinyallerle
    devam eder, ancak çoklu process/sunucu güvenilirliği için uzak backend şarttır.
  - Uzak backend `SIDAR_EVENT_BUS_BACKEND` ile seçilir.
  - Desteklenen backend stratejileri: `redis` (varsayılan), `rabbitmq`, `kafka`.
  - İlgili ortam değişkenleri: `SIDAR_EVENT_BUS_CHANNEL`, `SIDAR_EVENT_BUS_GROUP`,
    `SIDAR_EVENT_BUS_DLQ_CHANNEL`, `SIDAR_EVENT_BUS_DLQ_MAXLEN`, `REDIS_URL`,
    `RABBITMQ_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `SIDAR_EVENT_BUS_KAFKA_TOPIC`,
    `SIDAR_EVENT_BUS_KAFKA_GROUP`.
  - Uzak broker hatalarında circuit breaker ve local fallback davranışı beklenir; üretim
    ve çoklu sunucu kurulumlarında Redis/RabbitMQ/Kafka backend'i açıkça sağlanmalıdır.

### 2.6 Otonom hata giderme / self-healing döngüsü

Self-healing, kalite kapısı çıktılarından kontrollü düzeltme planı üretmek için vardır;
rastgele dosya değiştirme mekanizması değildir. Operasyonel kural seti:

1. **Sinyal toplama:** `autonomous_loop.sh`, mypy/pytest/coverage çıktıları ve hotspot
   raporlarını `artifacts/` altında toplar.
2. **Analiz ve plan:** `scripts/auto_heal.py`, logları `agent/auto_handle.py` içindeki
   `local_self_heal` aracına taşır; kaynak türüne göre uygun model seçer ve risk
   sınıflandırması yapar. CLI içinde aynı akış `.heal <log_dosyası>` kısayoluyla da
   tetiklenebilir.
3. **Batch ve retry sınırı:** Scope queue/batch retry davranışı sonsuz düzeltme döngüsüne
   dönüşmemelidir. `autonomous_loop.sh` remediation deneme sayısını sınırlı tutar; başarısız,
   partial veya blocked sonuçlar reviewer/QA değerlendirmesine veri olarak taşınmalıdır.
4. **Güvenlik sınırları:** Düşük riskli planlar otomatik uygulanabilir; yüksek riskli
   değişikliklerde HITL onayı gerekir. CI/otonom çalışmada `--hitl-approve yes/no`
   açıkça belirtilmelidir.
5. **Kalite kapısı:** Düzeltme sonrası test/lint/coverage komutları tekrar çalıştırılır;
   başarısız sonuç yeni self-heal turuna veri olur.
6. **Rollback/izlenebilirlik:** Üretilen planlar, loglar ve değişiklik diff'i commit öncesi
   gözden geçirilir; dış servis, ağ, secret veya yıkıcı shell aksiyonları self-heal içinde
   varsayılan olarak güvenli kabul edilmez.

### 2.7 Multimodal, vision ve voice kuralları

- `core/multimodal.py`, video/audio/image türünü MIME veya dosya yolundan ayırır;
  medya önce `MultimodalPipeline` ile ortak LLM bağlamına dönüştürülmelidir.
- Video girdilerinde frame özetleri ve ses transkripti birlikte kullanılabilir. Ses
  transkripsiyonunda Whisper CLI/STT sonucu yoksa hata nedeni açıkça raporlanmalı, ham medya
  verisi loglara yazılmamalıdır.
- `core/vision.py` içindeki `VisionPipeline`, görsel path/bytes girdisini analiz eder;
  browser/frontend doğrulamasında screenshot/vision sinyali reviewer veya swarm bağlamına
  özet olarak taşınmalıdır.
- `core/voice.py`, `/ws/voice` için VAD, barge-in/interrupt, duplex output buffer ve TTS
  segmentlerini yönetir; `WebRTCAudioIngress` tarayıcı ses paketlerini normalize eder.
- Sesli komutlar transcript'e dönüştürülmeden kod/dosya/browser aksiyonu tetiklememelidir.
  Destructive veya dış sistem etkili aksiyonlarda yanlış algılama riski nedeniyle reviewer/HITL
  onayı gerekir.
- Multimodal girdiler Poyraz'ın video insight/marketing akışında ve browser otomasyonu ile
  frontend görsel doğrulamada kullanılabilir; privacy/secret içerebilecek medya parçaları
  loglara ham içerik olarak yazılmamalıdır.

---

## 3) Geliştirme ortamı, araç standardı ve terminoloji

- Proje adı tüm doküman ve çıktılarda **Sidar** olarak kullanılmalıdır; eski proje adı
  yeni içeriklere eklenmemelidir.
- Yerel coding LLM varsayılanı `qwen2.5-coder:7b` değeridir; Ollama kullanan
  geliştirme ortamlarında Qwen 2.5 Coder ailesi temel kabul edilir.
- Standart paket/komut çalıştırma aracı **uv**'dir:
  - Kurulum: `uv sync --all-extras`
  - Komut çalıştırma: `uv run ...`
  - Otomatik kurulum betiği: `./install_sidar.sh` (dev bağımlılıkları varsayılan olarak
    kurulur; yalnız production/minimal kurulum için `--no-dev` kullanılır).
- `python -m pip install -e .` yalnızca legacy/minimum fallback olarak düşünülmelidir;
  dokümantasyon ve yeni otomasyonlarda uv komutları tercih edilmelidir.

---

## 4) Codex skills rehberi

Bu oturumdaki gerçek kullanılabilir skill listesi, çalışma zamanı tarafından sağlanan
`Available skills` bölümüdür. `AGENTS.md`, skill envanterinin tek doğruluk kaynağı
değildir; yalnızca `/workspace/Sidar` deposuna özel skill kullanım kurallarını,
tetikleme koşullarını ve bağlam hijyeni beklentilerini açıklar.

> Operasyonel kural: Belirli bir skill adı, yolu veya amacı dokümante edilecekse
> bilginin hızla bayatlayabileceği unutulmamalı; güncel kullanılabilirlik için her
> zaman oturumdaki `Available skills` çıktısı esas alınmalıdır.

### 4.1 Skill tetikleme kuralları

- Kullanıcı skill adını açıkça verirse (`$SkillName` veya düz metin) skill kullanılmalıdır.
- Kullanıcı isteği bir skill tanımıyla net eşleşiyorsa skill kullanılmalıdır.
- Birden fazla skill gerekiyorsa minimum gerekli set seçilmeli ve sıra belirtilmelidir.
- Skill bu turda tekrar anılmadıysa bir sonraki tura taşınmamalıdır.

### 4.2 Skill kullanım yöntemi (progressive disclosure)

1. İlgili `SKILL.md` dosyasını aç ve yalnızca gerekli kısmı oku.
2. Relative path’leri önce skill dizinine göre çöz.
3. `references/` gibi ek klasörlerden sadece gereken dosyaları yükle.
4. `scripts/` varsa uzun çıktıyı elle yazmak yerine script’i kullan.
5. `assets/templates` varsa yeniden üretmek yerine tekrar kullan.

### 4.3 Koordinasyon, bağlam hijyeni ve fallback

- Uzun metinleri kopyalamak yerine özetle; bağlamı küçük tut.
- Gereksiz derin referans zinciri açma.
- Skill uygulanamazsa sorunu kısa belirt ve en iyi alternatif yaklaşımı uygula.

---

## 5) Yeni ajan ekleme kısa rehberi

1. `agent/roles/` altında yeni ajan sınıfını oluştur.
2. `@AgentCatalog.register(...)` dekoratörüyle role/capability metadata’sını tanımla.
3. `agent/roles/__init__.py` içinde dışa aktar.
4. `agent/registry.py::_import_builtin_roles()` listesine yeni modülü ekle.
5. Supervisor/swarm routing etkisini değerlendir: yeni capability bir intent'e bağlanacaksa
   `agent/core/supervisor.py`, `agent/swarm.py` veya event bus sözleşmeleri de güncellenmelidir.
6. Ajanın rol adı, capability seti ve kullanım amacını dokümante et.
7. Testler ve entegrasyon kontrolleriyle kaydın çalıştığını doğrula (`AgentCatalog.list_all()` vb.).

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

## 6) Doküman bakım notları

- Bu dosya **ajan + skill** kapsamını birlikte taşır; içerik adıyla uyumludur.
- Skill kullanılabilirliği için statik liste tutulmaz; güncel envanter çalışma zamanı `Available skills` çıktısından doğrulanmalıdır.
- Yeni role/capability eklendiğinde bu dosyanın 2. bölümünü güncelleyin.

### 6.1 Hızlı doğrulama checklist’i

Ön koşul: Aşağıdaki çalışma zamanı doğrulamaları **bağımlılıkları kurulmuş** bir ortamda
çalıştırılmalıdır. Temiz/çıplak repo checkout ortamında `python-dotenv`,
`pydantic-settings` vb. proje bağımlılıkları henüz yoksa `agent.registry`, yerleşik rol
modüllerini import ederken başarısız olabilir ve `AgentCatalog.list_all()` boş liste
döndürebilir. Bu durumda önce bağımlılıkları kurun:

- `uv sync --all-extras`
- Kurulum betiği kullanılıyorsa `./install_sidar.sh` (dev bağımlılıkları varsayılan gelir).
- Legacy fallback gerekiyorsa minimum test/tooling için `python -m pip install -e ".[dev]"`
  kullanılabilir; ancak repo standardı uv akışıdır.

Doğrulama adımları:

**1. Hızlı görünürlük/smoke kontrolü**

Aşağıdaki komut kullanılabilir; ancak yalnızca mevcut role adlarını basar ve tek
başına yeterli kabul edilmemelidir:

```bash
uv run python -c "from agent.registry import AgentCatalog; print([s.role_name for s in AgentCatalog.list_all()])"
```

Çıktı `[]` ise öncelikle bağımlılık kurulumunu ve import uyarılarını kontrol edin.

**2. Fail-fast yerleşik rol doğrulaması**

Yerleşik rollerin eksiksiz yüklendiğini doğrulamak için aşağıdaki komut
çalıştırılmalıdır. Bu komut, boş liste veya eksik role durumlarını sessiz geçmez:

```bash
uv run python - <<'PY'
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
uv run python - <<'PY'
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

### 6.2 Ayrıştırma (SoC) yol haritası

- Doküman boyutu büyüdüğünde `Codex skills` kurallarını ayrı bir `SKILLS.md` dosyasına taşıyın.
- `AGENTS.md` dosyasını repo içi multi-agent mimari ve operasyonel standartlara odaklı tutun.
