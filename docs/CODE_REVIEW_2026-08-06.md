# Sidar AI — Kod İncelemesi ve İyileştirme Analizi (2026-08-06)

> **Tetikleyici:** Kullanıcının yerel WSL2/RTX 3070 Ti ortamında yaptığı uçtan uca kurulum
> (`./install_sidar.sh`, dev-full profili) ve doğrulama koşusu (`make benchmark-seed` →
> `make production-readiness`) **tamamen yeşil** sonuçlandı: 4459 unit + 166
> integration/smoke/e2e + 533 frontend testi geçti, backend+frontend coverage **%100**,
> Bandit **0 bulgu**, Ruff/mypy/ESLint/tsc **0 hata**, bundle budget içinde, GPU
> benchmarkları (TTFT/latency/VRAM/throughput) başarılı. Bu doküman, o sağlıklı temel
> üzerine, **otomatik kalite kapılarının (lint/coverage/security-scan) yakalayamayacağı**
> mimari, sürdürülebilirlik ve süreç risklerini tespit etmek için yapılan tam kapsamlı
> bir kod incelemesinin sonucudur.

## 0. Yöntem ve önemli bağlam

Bu inceleme dört paralel derin taramadan oluştu: **(A)** backend mimarisi
(`config.py`, `web_server.py`, `main.py`/`cli.py`, `core/db/monolith.py`,
`core/router.py`, `core/rag/`, `core/ci_remediation.py`, `agent/`), **(B)** installer/CI
tooling (`install_sidar.sh`, `scripts/install_modules/`, `run_tests.sh`, `Makefile`,
coverage/benchmark gate tasarımı, secrets), **(C)** frontend (`web_ui_react/`, TS
migrasyonu, bundle, test/E2E kapsamı, a11y), **(D)** test paketi yapısı ve
`.github/workflows/` (14 workflow), artı bu dokümanın kendisini yazan oturumda yapılan
doğrudan doğrulamalar (`pyproject.toml` omit listesi, `docs/REFACTOR_PLAN.md`,
`docs/TEST_OPTIMIZATION_PLAN.md`, PR şablonu).

**Kritik bağlam — proje zaten kendi mimari borcunu takip ediyor.** `docs/REFACTOR_PLAN.md`
ve `docs/TEST_OPTIMIZATION_PLAN.md`, büyük dosyaların (`web_server.py`, `config.py`,
`core/db/monolith.py`, `agent/sidar_agent.py`, `agent/swarm.py`, `core/rag/__init__.py`,
`core/doctor.py`, `managers/code_manager.py`, `managers/browser_manager.py`,
`core/ci_remediation.py`, `install_sidar.sh`, `run_tests.sh`) refactor durumunu, hedef
modül sınırlarını ve **P0 güvenlik maddesi** `SEC-PLUGIN-001`'i (plugin yürütmesinin
process/container sınırına taşınması, hedef kapanış 2026-09-30) satır satır izliyor;
hatta `tests/unit/test_refactor_plan.py` bu planın belirli cümlelerinin kodla senkron
kaldığını test ediyor. Bu, olağan bir proje için beklenmeyecek bir disiplin düzeyi.
**Bu rapor o planları tekrarlamıyor** — bunun yerine (1) planı doğrulayıp somutlaştırıyor,
(2) planda **yer almayan** yeni bulguları ekliyor, (3) kullanıcının yerel kurulum/test
çıktısına özgü notları ekliyor.

---

## 1. Öncelikli aksiyon listesi (özet)

| # | Öncelik | Bulgu | Dosya | Durum |
|---|---|---|---|---|
| 1 | **P0** | Frontend ESLint kapsamı hâlâ `.js/.jsx` ile sınırlı; 22 production `.tsx` dosyası (a11y kuralları dahil) **hiç lint edilmiyor** | `web_ui_react/eslint.config.js`, `package.json` (`lint` script) | 🆕 Yeni |
| 2 | **P0** | `core/db/monolith.py`: SQLite bootstrap şeması (elle yazılmış 14 `CREATE TABLE`) ile PostgreSQL'i yöneten Alembic migration zinciri arasında **otomatik senkron kontrolü yok** | `core/db/monolith.py:467-701` | 🆕 Yeni |
| 3 | **P0** | Semantic/dataflow SAST yok (CodeQL/Semgrep) — hem Python hem JS/TS için | `.github/workflows/` | 🆕 Yeni |
| 4 | **P0 (zaten planlı)** | Plugin yürütmesi hâlâ process-içi sandbox; container/process izolasyonu tamamlanmadı | `web/plugins/sandbox.py` | 📋 İzleniyor (`SEC-PLUGIN-001`, hedef 2026-09-30) |
| 5 | **P1** | Benchmark baseline cache tek nokta arızası: cache eviction / self-hosted runner yeniden adlandırma → **ilgisiz bir PR bile** `production-readiness` kapısında bloklanır | `.github/workflows/ci.yml` (`benchmark-compare`) | 📋 Kısmen izleniyor, iyileştirme fırsatı var |
| 6 | **P1** | `benchmark-baseline-keepalive.yml` cache-key formatı diğer tüm okuma/yazma noktalarıyla **uyuşmuyor** (muhtemelen sessizce çalışmıyor) | `.github/workflows/benchmark-baseline-keepalive.yml:31-35` | 🆕 Yeni, doğrulanmalı |
| 7 | **P1** | CI'da yalnızca `test:e2e:smoke` (2 test) çalışıyor; 7 panel-özel Playwright spec'i (`admin-panels`, `agent-manager`, `p2p-dialogue`, `prompt-admin`, `swarm-flow`, `tools-panel`, `voice-panel`) **CI'da hiç tetiklenmiyor** | `.github/workflows/ci.yml:385` | 🆕 Yeni |
| 8 | **P1** | `install_sidar.sh` içine gömülü modül hash manifesti yalnız CI'da (`make check-install-manifests`) doğrulanıyor; pre-commit hook yok → commit sonrası CI'da yakalanan drift riski | `.pre-commit-config.yaml` | 🆕 Yeni |
| 9 | **P2** | `INTEGRATION_PYTEST_WORKERS` sabit `2`'ye kilitli (unit fazı `auto`/8 worker); nedeni dokümante değil | `scripts/test_gates/coverage_helpers.sh:137` | 🆕 Yeni |
| 10 | **P2** | `core/doctor/__init__.py` (repo'nun **en büyük** dosyası, 1943 satır) içindeki `checks/` alt paketi gerçek ayrıştırma değil — 10 fonksiyonun tamamı tek satırlık pass-through | `core/doctor/checks/*.py` | 🆕 Yeni (plan bu nüansı içermiyor) |
| 11 | **P2** | Frontend: aynı "hata mesajı çıkar" helper'ı **6 dosyada 3 farklı imzayla** kopyalanmış | `AgentManagerPanel.tsx`, `OperationsQaPanel.tsx`, `PluginMarketplacePanel.tsx`, `PromptAdminPanel.tsx`, `TenantAdminPanel.tsx`, `useSwarmFlowController.ts` | 🆕 Yeni |
| 12 | **P2** | Frontend: 4 admin panelinde load/error/refresh state boilerplate'i tekrarlanmış; ortak `useAsyncResource` hook'u yok | `PluginMarketplacePanel.tsx`, `PromptAdminPanel.tsx`, `TenantAdminPanel.tsx`, `OperationsQaPanel.tsx` | 🆕 Yeni |
| 13 | **P2** | `Makefile`'daki `ci-parity` hedefi `TEST_PROFILE=ci` **ayarlamıyor** — `dev-full` ile fonksiyonel olarak aynı; adı yanıltıcı | `Makefile:79-83` | 🆕 Yeni |
| 14 | **P3** | `config_rag.py` ölü kod — yalnızca kendi testi import ediyor, üretim kodunda hiçbir çağıran yok | `config_rag.py` | 🆕 Yeni |
| 15 | **P3** | `config_llm.py`/`config_quality.py` içinde aynı ~15 satırlık "scoped pydantic settings" metaprogramlama bloğu birebir kopyalanmış | `config_llm.py:93-106`, `config_quality.py:78-88` | 🆕 Yeni |
| 16 | **P3** | Doküman sürüklenmesi: `TEST_OPTIMIZATION_PLAN.md`, `pyproject.toml`'da artık bulunmayan `core/vision.py`/`core/voice.py` coverage-omit kayıtlarından bahsediyor | `docs/TEST_OPTIMIZATION_PLAN.md:38,80` vs `pyproject.toml:516-533` | 🆕 Yeni (bu oturumda doğrulandı) |
| 17 | **P3** | Doküman şişkinliği: 115 markdown dosyası, 4 ayrı "audit report" (v4.0/v5.0/v5.1/v5.1_COMPREHENSIVE) + 2 ayrı "mimari raporu" (v5.0/v5.1) + `docs/project-report/` (6 dosya) + `PROJE_RAPORU.md` — konsolidasyon fırsatı | `docs/` | 🆕 Yeni |
| 18 | **P3** | `main.py` aslında kurulum sihirbazı/launcher'dır, `cli.py` gerçek REPL giriş noktasıdır — isimlendirme kafa karıştırıcı | `main.py`, `cli.py` | 🆕 Yeni |

🆕 = bu incelemede ilk kez tespit edildi ve mevcut planlarda yer almıyor. 📋 = zaten `docs/REFACTOR_PLAN.md`'de izleniyor, burada teyit/detaylandırma var.

---

## 2. Backend mimarisi

### 2.1 `config.py` ve config sprawl (27 config modülü)

`config.py` (1754 satır) artık ham bir `os.getenv()` yığını değil — çoğu, `core/config_*.py`
altındaki tipli dataclass/pydantic settings nesnelerinden beslenen bir **facade** sınıfı
(`class Config`, satır 490). Bu, `REFACTOR_PLAN.md`'nin belirttiği gibi gerçek bir refactor.
Ancak:

- **Tutarsız desen:** Aynı sınıf gövdesinde hem delege edilen facade alanları
  (`AI_PROVIDER: str = LLM_SETTINGS.AI_PROVIDER`, satır 554) hem de ham inline env-parse
  (`TEXT_MODEL: str = os.getenv("TEXT_MODEL", "gemma2:9b")`, satır 579) yan yana duruyor;
  `config.py` içinde hâlâ **84 doğrudan `os.environ`/`os.getenv` çağrısı** var. Bir okuyucu,
  her satıra tek tek bakmadan bir `Config.X` alanının tipli mi yoksa ad-hoc mu
  çözümlendiğini öngöremiyor.
- **Ölü kod:** `config_rag.py` kendi docstring'inde "geriye dönük uyumluluk shim'i" olduğunu
  itiraf ediyor; üretim kodunda **hiçbir** import eden yok, tek kullanıcısı
  `tests/unit/root/test_config.py:22` (yalnızca shim'in import edilebildiğini doğruluyor).
  **Öneri:** dosyayı silin veya gerçek bir dış tüketicisi varsa belgeleyin.
- **Kopyalanmış metaprogramlama:** `config_llm.py:93-106` (`load_llm_settings`) ve
  `config_quality.py:78-88` (`load_quality_gate_settings`), bir pydantic `BaseSettings`
  sınıfını çalışma zamanında belirli bir dotenv yoluna yeniden kapsamak için aynı
  `type("Scoped<X>Settings", (X,), {...})` deseninin birebir kopyasını kullanıyor — hatta
  biri `env_ignore_empty=True` alırken diğeri almıyor (satır 57 vs 20), bu da fark edilmeyen
  bir tutarsızlık. **Öneri:** `core/config_env_helpers.load_scoped_settings(...)` gibi ortak
  bir yardımcıya çıkarın.
- **Kök/`core/` sınırı belirsiz:** `config_gpu.py` (kök) yalnızca `core/config_gpu_detect.py`'nin
  saf yeniden-export'u; hangi ayarın nerede yaşayacağına dair yazılı bir kural yok.

### 2.2 `web_server.py` — 2627 satır, kısmen tamamlanmış extraction

`web/` paketi (42 dosya: `web/routes/*`, `web/middleware/*`, `web/plugins/*`,
`web/app_factory.py` vb.) gerçekten var ve `REFACTOR_PLAN.md`'nin belirttiği gibi büyük
oranda ayrıştırma yapılmış. Ama **plugin marketplace örneği belgelenmiş, yarım kalmış bir
extraction**: `web/routes/plugin_marketplace.py:1-11`, mantığın oradan taşındığını ama
"mevcut monkeypatch tabanlı testler aynı isimleri gözlemlemeye devam etsin diye"
`web_server.py` içinde ~15 ince forwarding fonksiyonunun (`_install_marketplace_plugin`,
`_uninstall_marketplace_plugin` vb., satır 1447-1550) bilerek bırakıldığını söylüyor.
**Aynı desen `main.py:869-903`'te de var** (`build_command`, `_launcher_child_env` —
`launcher/process.py`'ye taşınmış ama testler eski modül-seviyesi isimleri monkeypatch'lediği
için wrapper bırakılmış).

**Somut sonuç:** `tests/unit/root/test_web_server.py` **12.073 satır** — repodaki en büyük
test dosyası, test ettiği dosyanın (2627 satır) ~4.6 katı. God-file'ın testleri de
kendine çekmesinin doğrudan kanıtı.

**Öneri:** Plugin-marketplace testlerini `web.routes.plugin_marketplace` modülünü
doğrudan patch edecek şekilde yeniden hedefleyin (diğer `_build_*_dependencies()`
enjeksiyon nesnelerinde zaten yapıldığı gibi), sonra `web_server.py`'deki ~15+10 wrapper
fonksiyonu silin. Bu, refactor planında zaten %80 tamamlanmış — en yüksek kaldıraçlı adım.

### 2.3 `core/db/monolith.py` — SQLite/PostgreSQL şema drift riski (🆕)

`Database` sınıfı (satır 216, 60 metod) hâlâ auth/session/marketing/coverage/quota gibi
birbirinden bağımsız domain'leri tek facade'da topluyor (planda izleniyor). **Yeni ve
somut risk:** `_init_schema_sqlite()` (satır 467-659, ~192 satır) 14 `CREATE TABLE`
ifadesini elle yazılmış tek bir SQL string'i içinde tutarken, `_init_schema_postgresql()`
(satır 667-701) tablo tanımlamıyor — Alembic migrasyonlarını çalıştırıyor. **Bu, SQLite
şemasının Alembic migration geçmişiyle senkron kalacağını garanti eden hiçbir otomasyon
olmadığı anlamına geliyor** — PostgreSQL için yeni bir Alembic migration'ı, SQLite string'ine
elle yansıtılmazsa hiçbir test/CI bunu yakalamaz.

**Öneri:** (a) SQLite bootstrap şemasını aynı Alembic migration zincirinden üretin
(Alembic SQLite'ı destekler), veya (b) en azından iki tablo/kolon kümesini karşılaştıran
bir CI kontrolü ekleyin.

### 2.4 `core/router.py` ve `core/rag/backends/pgvector.py` — nosec B608 kullanımı GÜVENLİ

İki dosyada da `# nosec B608` ile işaretli f-string SQL'ler incelendi: tablo/sütun adları
her zaman `assert_safe_sql_identifier()`/`_reject_if_invalid_pg_table()` ile (regex:
`^[A-Za-z_][A-Za-z0-9_]*$`) doğrulanmış sabit değerler; gerçek veri değerleri her zaman
bind-parameter (`?`, `:param`) olarak geçiyor. **Bu suppression'lar meşru** — merkezi bir
`core/db_components/dialect.py` doğrulama yardımcısı tutarlı biçimde kullanılıyor, ve
`tests/unit/test_bandit_comments.py` global bir B608 skip eklenmesini engelliyor. Ekstra
güvence için: her `# nosec B608` satırının aynı dosyada `core.db_components.dialect`
import ettiğini doğrulayan hafif bir AST meta-testi eklenebilir.

### 2.5 `core/doctor/__init__.py` — repo'nun en büyük dosyası, "sahte" alt paket (🆕)

**1943 satır — taranan tüm Python dosyaları arasında en büyüğü**, 49 fonksiyon, 16
`check_*` fonksiyonu. `core/doctor/checks/` alt paketi (`database.py`, `gpu.py`, `rag.py`,
`redis.py`, `security.py`) gerçek bir ayrıştırma **gibi görünüyor** ama değil — her biri
tek satırlık pass-through:

```python
# core/doctor/checks/database.py
import core.doctor as _doctor
def check_database_env() -> DoctorCheck:
    return _doctor.check_database_env()
```

Tüm 10 fonksiyon aynı deseni izliyor; gerçek mantığın %100'ü hâlâ `__init__.py`'de.
`REFACTOR_PLAN.md`'nin `core/doctor.py` satırı `models.py`/`reporting.py` ayrıştırmasından
bahsediyor ama bu spesifik "sahte checks/ alt paketi" nüansını içermiyor — **plana bu
detayın eklenmesi önerilir**. Ya extraction gerçekten tamamlanmalı (mantık `checks/*.py`'ye
taşınıp `__init__.py` geriye-uyumlu import etmeli) ya da `checks/` paketi kaldırılmalı;
şu an okunabilirlik açısından net negatif.

### 2.6 `agent/` paketi — genelde iyi ayrıştırılmış, birkaç büyük rol dosyası

`agent/roles/coverage_agent.py` ve `agent/roles/reviewer_agent.py` gerçek delegasyon
gösteriyor (`agent/roles/coverage/{analyzer,batch_heal,generator}.py`,
`agent/roles/reviewer/judge.py`) — bu, §2.5'teki sahte ayrıştırmanın tam tersi, olumlu bir
kontrast. `agent/sidar_agent.py` (1162 satır, 47 metod) ve `agent/swarm.py` (1147 satır)
orkestratör rolü gereği büyük kalıyor; ikisi de zaten planda.

### 2.7 `core/ci_remediation.py` — güvenlik-kritik allowlist, genel amaçlı string şablonlamayla iç içe (🆕 nüans)

1318 satırlık dosya CI log ayrıştırma, **komut-güvenlik allowlisti**
(`_is_allowed_ruff_command`, `_is_allowed_validation_command`, satır 167-267 —
otonom self-heal döngüsünün hangi shell komutlarını çalıştırabileceğini kontrol eden
güvenlik-kritik mantık), prompt şablonlama ve orkestrasyonu tek dosyada topluyor. Plan
bu dosyayı `context/payload/plan/validation` modüllerine bölmeyi öngörüyor ama
allowlist'in özellikle **izole bir güvenlik incelemesi** için ayrı bir modüle
(`core/ci_remediation/command_safety.py`) çıkarılması gerektiğini vurgulamıyor — bu,
otonom kod yürütmeyi kontrol eden mantığın 1300 satırlık genel amaçlı bir dosyada
"kaybolma" riskini azaltır.

### 2.8 `main.py` vs `cli.py` — isimlendirme kafa karışıklığı (🆕)

`main.py` (1235 satır) aslında **interaktif kurulum sihirbazı/launcher**'dır (banner,
doctor preflight, mod/sağlayıcı seçimi, sonra `web_server.py`/`cli.py`'yi
`subprocess.Popen` ile başlatır); `cli.py` (459 satır) gerçek REPL giriş noktasıdır
(`SidarAgent`'ı doğrudan kurar). Fonksiyonel çakışma yok, ama isimlendirme bir okuyucunun
beklentisini karşılamıyor. **Öneri:** `main.py` → `launcher.py` (veya `setup_wizard.py`)
olarak yeniden adlandırılabilir; düşük riskli, yüksek netlik kazancı.

---

## 3. Installer, script'ler ve CI altyapısı

### 3.1 `install_sidar.sh` (92KB) + `scripts/install_modules/` (38 dosya, 13.524 satır)

Ayrım genel olarak temiz, ancak **kasıtlı bir çift-kaynak riski** var: `install_sidar.sh`
hem modül hash manifestinin tam bir kopyasını (`EMBEDDED_MODULE_HASHES_MANIFEST`, satır
596-634) hem de pinlenmiş kaynak commit'ini (satır 182) doğrudan gömüyor — bu, tek bir
indirilen `install_sidar.sh`'nin, yerel modül ağacı bulunamadığında indirdiği modülleri
kendi kendine doğrulayabilmesi için kasıtlı. Ama her modül değişikliği
`scripts/sync_install_module_hashes.sh`'nin çalıştırılmasını gerektiriyor, aksi halde
`make check-install-manifests` **yalnızca CI'da** başarısız oluyor (`.pre-commit-config.yaml`
bu kontrolü içermiyor). **Öneri:** `scripts/sync_install_module_hashes.sh --check`'i
pre-commit hook'una ekleyin, böylece drift push öncesi yakalanır.

**Remote module fallback (supply-chain) değerlendirmesi:** Bu tarafta tasarım gerçekten
sağlam — pinlenmiş commit SHA zorunluluğu (`validate_remote_module_trust_root`, fail-closed),
her modül için ayrı SHA-256 doğrulaması (embedded manifestten, aynı güvenilmeyen kanaldan
değil), üstel geri çekilme + `Retry-After` desteği, UID-sahiplik kontrollü ve symlink
reddeden cache, ve üçüncü parti script'ler (Ollama/uv/Volta/NVM) için `/dev/tty` üzerinden
interaktif TOFU inceleme akışı. Zayıf nokta kriptografi değil, **karmaşıklık** —
~700+ satır tek dosyada. Bu blok kendi `scripts/install_modules/utils/remote_module_fetch.sh`
dosyasına çıkarılabilir.

### 3.2 `run_tests.sh` — 663 satır + `scripts/test_gates/*.sh` (2680 satır, 10 dosya)

Toplam orkestrasyon yüzeyi ~3300 satır ama makul biçimde bölünmüş (coverage, benchmark,
frontend, bats, environment). **Konfigürasyon yüzeyi büyük:** `run_tests.sh`'in kendisinde
**69 farklı `${VAR:-...}` env-var bayrağı** var (yardımcı script'lerdeki fazlasıyla
birlikte). `--help` çıktısı yok, bilinmeyen `SIDAR_*`/`BENCHMARK_*`/`COVERAGE_*`
değişkenlerini reddeden bir şema doğrulaması yok — yazım hataları sessizce varsayılana
düşer.

### 3.3 `Makefile` — `ci-parity` hedefi yanıltıcı (🆕)

`ci-parity` = `$(MAKE) dev-full` (satır 79-83) — `TEST_PROFILE=ci` **ayarlamıyor**, yani
adına rağmen gerçek CI profiliyle (`base-quality-gates`'in yaptığı gibi) aynı şeyi
doğrulamıyor; `dev-full`'ın fonksiyonel bir takma adı. **Öneri:** `ci-parity`'yi
`base-quality-gates`'i çağıracak şekilde yeniden tanımlayın veya kaldırın.

### 3.4 Coverage gate: `fail_under = 100` (branch coverage) — dengeli değerlendirme

**Ratchet'li** (tek yönlü artan) bir %100 hedefi, gün geçtikçe zaten %100'e ulaşmış bir
codebase için savunulabilir bir uygulama — geri dönüşü önlüyor ve ekip zaten
`COVERAGE_FAIL_UNDER_CAMPAIGN` gibi kaçış valfleri eklemiş. Ama `branch=true` +
`fail_under=100` yapısal olarak **her yeni `if`/`except`/ternary dalının sıfır tolerasla
test edilmesini** zorunlu kılıyor — bu, gerçekçi olmayan `except OSError:` gibi savunma
dallarını test etmek için değersiz testler yazma veya `# pragma: no cover`'ı aşırı
kullanma eğilimini teşvik edebilir. **Öneri:** `pragma: no cover` kullanım sayısının
LOC'tan daha hızlı büyümediğini kontrol eden bir periyodik (nightly) uyarı ekleyin — bu,
%100 kapının gerçek test değeri yerine "test tiyatrosu" üretmeye başlayıp başlamadığının
iyi bir göstergesi olur.

### 3.5 Benchmark gate — tasarım sağlam, ama tek nokta arıza riski var (🆕 detay)

CI, baseline'ı laptop'ta üretilip commit edilen bir JSON yerine **CI runner'ının kendisinde**
seed ediyor (`.github/workflows/ci.yml`, `benchmark-baseline-seed.yml`,
`benchmark-baseline-keepalive.yml`) — heterojen donanım için doğru karar, ve
`BENCHMARK_BASELINE_MAX_AGE_DAYS` bayatlık kontrolü mantıklı.

**Ancak `production-readiness` (zorunlu branch-protection kontrolü) `benchmark-compare`'e
bağımlı, ve o da tek bir GitHub Actions cache namespace'ine bağımlı.** Somut arıza
senaryoları: (1) cache 7 günlük hareketsizlik veya 10GB toplam limit nedeniyle tahliye
edilirse, (2) self-hosted `[self-hosted, linux, benchmark]` runner yeniden
sağlanır/adlandırılırsa (cache key `runner.name` içeriyor) — **her iki durumda da kodla
hiçbir ilgisi olmayan bir PR bile `production-readiness`'te bloklanır**, ta ki biri manuel
`seed_benchmark_baseline=true` dispatch'ini çalıştırana kadar. Ekip bunu bilinçli bir
"fail-closed > sessizce shared runner'a düşme" tasarım kararı olarak belgelemiş
(`docs/CI_REQUIRED_CHECKS.md`) ve ayrıntılı bir kurtarma runbook'u var
(`docs/TESTING.md`) — yani bu tamamen gözden kaçmış değil, ama iyileştirme fırsatı var:

- **`benchmark-baseline-keepalive.yml` muhtemelen çalışmıyor (🆕, doğrulanmalı):** cache
  restore-key formatı (satır 31-35: `benchmark-baseline-${{ runner.os }}-py311-...`)
  sistemdeki **her diğer** okuma/yazma noktasından (`ci.yml`'in `seed-benchmark-baseline`
  ve `benchmark-compare` job'ları, `benchmark-baseline-seed.yml`) eksik — onlar
  `runner.name` segmentini de içeriyor. GitHub Actions cache restore-keys yalnızca **katı
  önek eşleşmesiyle** çalıştığından, keepalive workflow'unun restore-key'i gerçek cache
  key'inin öneki olamaz — yani twice-weekly "canlı tutma" işlemi muhtemelen hiçbir zaman
  gerçek cache'e dokunmuyor. Gerçek workflow çalışma geçmişiyle doğrulanmalı; doğrulanırsa
  key formatını diğer tüm okuyucu/yazıcılarla hizalayın.
- **Öneri:** Yalnız restore değil, periyodik gerçek **re-seed** eden bir zamanlanmış job
  ekleyin (cache kendini onarsın, bir PR'ın kırmızı görünmesini beklemeden); eksik baseline
  için proaktif bir uyarı (issue açma) ekleyin — şu an tamamen reaktif (bir PR kırmızı
  olana kadar kimse fark etmiyor).
- `benchmark-baseline-seed.yml` ve `ci.yml`'in kendi `seed-benchmark-baseline` job'u
  neredeyse birebir aynı mantığı iki yerde tutuyor (farklı pinlenmiş action sürümleriyle
  bile) — `workflow_call` ile birleştirilebilir.

### 3.6 GPU-gated testler — zaten doğru tasarlanmış

`ENABLE_GPU_TESTS=auto` yalnızca donanım algılanınca açılıyor; `RUN_GPU_STRESS` varsayılan
kapalı ve yalnızca `dev-full-gpu` hedefi, self-hosted GPU runner'lı CI job'u ve ayrı bir
nightly workflow'da etkin. **Kullanıcının yerel koşusunda GPU testlerinin her tam koşuda
~6 dakika sürmesinin nedeni, geliştirme makinesinde gerçek bir GPU olması** (`auto` →
açık çözümleniyor) — bu bir tasarım kusuru değil. **Öneri:** Hızlı bir varsayılan
geliştirme döngüsü isteyen GPU'lu makineler için `ENABLE_GPU_TESTS=0` override'ının
`AGENTS.md`/`README.md`'de belgelenmesi faydalı olur.

### 3.7 `.github/workflows/` (14 dosya) — CodeQL eksik (🆕)

Dependabot **kapsamlı ve iyi yapılandırılmış** (5 ekosistem: uv/npm/github-actions/
docker/docker-compose). Branch-protection kendi kendini haftalık denetliyor
(`branch-protection-audit.yml`) — çoğu repodan daha iyi. **Ama hiçbir yerde CodeQL
(veya Semgrep) yok** — SAST kapsamı Bandit (Python, regex-tabanlı) + `npm audit`
(yalnızca bağımlılık, statik kod analizi değil) ile sınırlı. Ne Python'da cross-file
taint-flow / auth-bypass mantığı ne de React/TS tarafında XSS/prototype-pollution gibi
JS-özel zafiyet sınıfları için semantic tarama yok. **Öneri:** GitHub'ın ücretsiz CodeQL
default setup'ını hem `python` hem `javascript-typescript` için, mevcut
`frontend-security-review.yml` ile aynı kadansta (haftalık + PR'da) ekleyin.

### 3.8 Secrets yönetimi — sağlam, bir gerçek açık var

`.sidar_keys.env` deseni (repo dışında, `chmod 600`), iki katmanlı opt-in materializasyon
(`SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV`, `SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV`), ve **tüm**
installer çıktısına global olarak uygulanan `mask_install_log_stream()` — iyi tasarlanmış.
**Gerçek açık:** maskeleme regex'i sabit bir anahtar-adı allowlisti'ne
(`SIDAR_INTERNAL_SECRET_ENV_KEYS`/`SIDAR_USER_SECRET_ENV_KEYS`) dayanıyor; ileride
eklenecek yeni bir secret-taşıyan env var (yeni bir entegrasyonun API anahtarı gibi) bu
diziye eklenmeyi unutulursa maskelenmeden yazdırılabilir. **Öneri:** `.env.example`/
`.env.advanced.example` içindeki `*_TOKEN|*_KEY|*_SECRET|*_PASSWORD` desenine uyan
anahtarları `SIDAR_USER_SECRET_ENV_KEYS` ile karşılaştırıp eksik olanı CI'da fail eden
bir birim testi ekleyin.

---

## 4. Frontend (`web_ui_react/`)

### 4.1 TypeScript migrasyonu — tamamlanmaya çok yakın, ama anlatım eski (🆕 nüans)

Kurulum logundaki sayılar doğru (`js=9, jsx=20, ts=10, tsx=22`), ama önemli nüans:
**kalan 29 "untyped" dosyanın tamamı test dosyası** (`*.test.jsx`, `*.test.js`,
`setup.js`) — gerçek uygulama kodunun her satırı (tüm bileşenler, tüm hook'lar,
`SwarmFlowPanel`, `ChatMarkdownRenderer`, `TenantAdminPanel` dahil) zaten `.ts`/`.tsx`.
`docs/development/frontend-typescript-migration.md` bu ilerlemeyi doğru ve ayrıntılı
kaydediyor. Ama `tsconfig.json`'daki yorum ve `typescript-migration-baseline.json`
(2027-03-31 hedefli çok-aylık kampanya anlatımı) hâlâ "ağaç ağırlıklı .jsx/.js" diyor —
bu artık gerçeği yansıtmıyor. **Öneri:** `typescript-migration-baseline.json` ve
`tsconfig.json` yorumunu "bileşen migrasyonu tamamlandı; kalan kapsam = test dosyaları"
olarak güncelleyin ve test dosyası dönüşümünün gerçekten önceliklendirilmeye değip
değmediğine karar verin.

### 4.2 ESLint kapsam hatası — a11y kuralları fiilen çalışmıyor (P0, 🆕)

`eslint-plugin-jsx-a11y` kurulu ve `eslint.config.js`'e dahil edilmiş (bilinçli bir
a11y-lint rollout, hatta `GraphView.jsx`'teki bir `eslint-disable` yorumuna referans
veriyor). **Ama** kural bloğu `files: ["src/**/*.{js,jsx}"]` ile sınırlı ve `lint`
script'i (`eslint src --ext .js,.jsx ...`) yalnızca `.js`/`.jsx` uzantılarını tarıyor —
`@typescript-eslint/parser` da kurulu değil. §4.1'deki bulgu nedeniyle **artık tüm
gerçek bileşenler `.tsx`** — yani `jsx-a11y`/`react`/`react-hooks` kuralları bugün
**fiilen sıfır production kodunu** taramıyor, yalnızca test dosyalarını. Referans verilen
`GraphView.jsx`'teki `eslint-disable` yorumu artık `GraphView.tsx:82`'de duruyor — dosya
artık lint glob'unun dışında olduğu için bu satır **etkisiz**: altındaki a11y sorunu
regresse olsa bile hiçbir uyarı tetiklenmez. Bu, geçen `lint` kapısının sahte bir güven
verdiği somut bir durum.

**Öneri (bu incelemenin en yüksek öncelikli tek maddesi):** `eslint.config.js`'in
`files` glob'unu `src/**/*.{js,jsx,ts,tsx}` yapın, `@typescript-eslint/parser` +
`typescript-eslint` flat-config preset'ini ekleyin, `lint` script'inin `--ext`'ini
`ts,tsx` içerecek şekilde genişletin. Bu saf bir kapı-doğruluğu düzeltmesi — kaynak
değişikliği gerektirmez, ama etkinleştirdikten sonra 22 dosyadaki (dahil `GraphView.tsx`,
`SwarmFlowPanel.tsx`, tüm admin panelleri) yeni bulgular için yeniden denetim gerekir.

### 4.3 CI'da yalnızca smoke E2E çalışıyor (🆕)

Repoda gerçekte **8 Playwright spec dosyası / 10 test** var — her isimlendirilen panel
(SwarmFlowPanel, TenantAdminPanel, OperationsQaPanel, PluginMarketplacePanel,
AgentManagerPanel, PromptAdminPanel, P2PDialoguePanel, VoiceAssistantPanel) için özel
bir spec mevcut. Ama `.github/workflows/ci.yml:385` yalnızca `test:e2e:smoke`'u (2 test)
çalıştırıyor — `test:e2e:critical` ve tam `test:e2e` `package.json`'da tanımlı ama hiçbir
workflow'dan çağrılmıyor. **Sonuç:** TenantAdminPanel'in RBAC-yazma akışında,
PluginMarketplacePanel'in kurulum akışında veya SwarmFlowPanel'in HITL rerun akışında
bir regresyon, birim testleri backend/websocket'i mock'ladığı için **CI'da hiç
yakalanmadan** main'e merge olabilir. **Öneri:** `test:e2e:critical`'i (en azından
`web_ui_react/src/components/*Panel*`'e dokunan PR'larda) CI'a bağlayın — spec'ler zaten
var, bu bir wiring değişikliği.

### 4.4 Kopyalanmış `errorMessage` helper'ı (🆕)

Aynı "bilinmeyen hatadan okunabilir mesaj çıkar" mantığı **6 dosyada 3 farklı imzayla**
bağımsız yeniden yazılmış: `AgentManagerPanel.tsx:63-65`, `OperationsQaPanel.tsx:28-29`,
`PluginMarketplacePanel.tsx:54-56`, `PromptAdminPanel.tsx:34-36`,
`TenantAdminPanel.tsx:14-15`, `useSwarmFlowController.ts:104` (inline). **Öneri:** `lib/api.ts`
(veya yeni `lib/errors.ts`) içinde tek bir `toErrorMessage(error: unknown, fallback?: string): string`
çıkarın, 6 çağrı noktasını buna yönlendirin.

### 4.5 Tekrarlanan "yükle-hata-yenile" iskeleti (🆕)

`PluginMarketplacePanel.tsx`, `PromptAdminPanel.tsx`, `TenantAdminPanel.tsx`,
`OperationsQaPanel.tsx` — dördü de aynı şekli elle kuruyor: `items`/`loading`/`error`
için `useState`, `fetchJson` çağıran bir `useCallback`, mount'ta tetikleyen bir
`useEffect`, elle bağlanmış bir "Yenile" butonu. Bu, `useSwarmFlowController.ts` (swarm
için) ve `useChatStore.ts`/`useWebSocket.ts` (chat için) zaten yaptığı gibi paylaşılan
bir hook'a çıkarılabilecek, 4 kez elle satır satır yazılmış bir `useAsyncResource`.
**Öneri:** `useAsyncResource<T>(loader, deps)` hook'u ekleyin (`{ data, loading, error,
reload }` döndüren) — her paneli ~15-20 satır küçültür.

### 4.6 Bundle — `ChatMarkdownRenderer` için özel bütçe yok (🆕)

`ChatMarkdownRenderer` zaten doğru lazy-load ediliyor (155KB raw/46KB gzip, en büyük
vendor-olmayan chunk). `scripts/check-bundle-budget.mjs` yalnızca `react-dom-*`
chunk'larına ve toplam JS/gzip bütçesine karşı kapı koyuyor — bu chunk'a özel bir tavan
yok, yani yanlışlıkla eklenen yeni bir remark plugin'i veya lazy-olmayan bir import,
toplam bütçe aşılmadığı sürece hiçbir gate'i tetiklemeden büyüyebilir. **Öneri:**
`react-dom` chunk'ına benzer isimlendirilmiş bir chunk bütçesi ekleyin; ayrıca
`react-markdown`/`remark-gfm`'i `rehypeSidarHighlight.ts`'den ayrı bir manual chunk'a
bölmek, Sidar'ın kendi highlight config'i değiştiğinde vendor markdown kodunun cache'te
kalmasını sağlar.

---

## 5. Zaten planlanmış / izlenen konular (çapraz referans)

Aşağıdakiler `docs/REFACTOR_PLAN.md` ve `docs/TEST_OPTIMIZATION_PLAN.md`'de zaten
izleniyor; bu incelemede doğrulandı, tekrar açılmasına gerek yok — yalnızca durum notu:

- `web_server.py`, `main.py`, `core/db/monolith.py`, `core/rag/__init__.py`, `config.py`,
  `install_sidar.sh`, `run_tests.sh`, `managers/code_manager.py`,
  `managers/browser_manager.py`, `agent/sidar_agent.py`, `agent/swarm.py`,
  `agent/roles/coverage_agent.py`, `agent/roles/reviewer_agent.py`, `core/llm_client.py`,
  `core/doctor.py`, `core/ci_remediation.py` — tümü tabloda, hedef modül sınırları ve
  "ilk düşük riskli adım" tanımlı.
- `SEC-PLUGIN-001` (P0 güvenlik maddesi) — plugin yürütmesinin container sınırına
  taşınması, hedef değerlendirme 2026-08-15, hedef kapanış 2026-09-30. Bu, genel refactor
  sıralamasının önünde tutulan tek madde.
- `managers/github_manager.py` — bilinçli olarak refactor listesine **eklenmedi**;
  25 `except Exception` bloğu PyGithub/`requests` sınırını saran kasıtlı bir adapter
  deseni, biriken borç değil (bu incelemede tekrar değerlendirilmedi, gerekçe makul
  bulundu).
- CI/test altyapısı için 6 madde zaten değerlendirilmiş (gpu-inference-policy-gate
  tasarım kararı, tek test job'u, benchmark cache `run_id`, workflow örtüşmesi, ruff debt
  ratchet tarihleri) — bu incelemenin CI bulguları (§3.5, §3.7) bunlarla **çakışmıyor**,
  farklı, önceden değerlendirilmemiş konulara odaklanıyor.
- Frontend refactor backlog'u (`api.js` bölünmesi, `useWebSocket.js` dispatch-map,
  `useVoiceAssistant.js` bölünmesi, `routerShim.jsx` sınırlaması) — bu incelemenin
  frontend bulguları (§4) bunlarla çakışmıyor, farklı bir katmana (ESLint kapsamı, CI
  E2E kapsamı, kopyalanmış hata/fetch helper'ları) odaklanıyor.

**Doküman tutarlılığı notu (🆕, bu oturumda doğrulandı):** `TEST_OPTIMIZATION_PLAN.md`
(satır 38, 80) `core/vision.py` ve `core/voice.py`'nin coverage `omit` listesinde
olduğunu söylüyor; ancak `pyproject.toml:516-533`'teki gerçek `omit` listesi bu iki
dosyayı **içermiyor** (her iki dosya da hâlâ mevcut ve aktif olarak kullanılıyor —
`web/routes/ws_voice.py`, `web_server.py`, `managers/youtube_manager.py`). Bu, doküman
ile kod arasında gerçek, doğrulanmış bir sürüklenme; `REFACTOR_PLAN.md`'nin aksine bu
doküman kodla senkron tutulduğunu doğrulayan bir test içermiyor. **Öneri:** ya
`TEST_OPTIMIZATION_PLAN.md`'yi güncelleyin ya da `pyproject.toml`'a bu iki dosyayı
gerçekten omit-listesine ekleyin (hangisi doğruysa).

---

## 6. Kullanıcının paylaştığı kurulum/test loguna özel notlar

- **`install_sidar.sh` uçtan uca sorunsuz çalıştı**, tüm pre-flight kontrolleri
  (WSL2/NVIDIA/Ollama/Docker) geçti, 108 Python paketi + React bağımlılıkları kuruldu,
  RAG/GraphRAG seed'i 27 dosya + 76 entity node + 131 edge ile tamamlandı — kurulum
  betiğinin sağlamlığı için iyi bir kanıt.
- **`make production-readiness` sonunda "Release hazır: Hayır" görülmesi normaldir** —
  yerel `production_ready` alanı yalnız CPU/standart kalite kapılarının kanıtıdır; asıl
  merge/release kararı GitHub Actions'taki `Production readiness aggregate` zorunlu
  kontrolüne bağlıdır (§3.5'teki benchmark-baseline SPOF riski de bu kapıyı etkiler).
  PR şablonu (`.github/PULL_REQUEST_TEMPLATE.md`) bu ayrımı zaten net biçimde
  vurguluyor.
- **GPU benchmarklarının her tam koşuda ~6 dakika sürmesi**, geliştirme makinesinde
  gerçek bir GPU olması nedeniyle `ENABLE_GPU_TESTS=auto`'nun otomatik açılmasından
  kaynaklanıyor (§3.6) — bir tasarım kusuru değil, ama hızlı iterasyon isteyen
  GPU'lu geliştiriciler için `ENABLE_GPU_TESTS=0` override'ının belgelenmesi faydalı
  olur.
- `make benchmark-seed` → `make production-readiness` sırası doğru kullanılmış: ilk koşu
  `.benchmarks/*_baseline.json`'ı `BENCHMARK_COMPARE_REQUIRED=0` ile oluşturdu, ikinci
  koşu `--benchmark-compare-fail=mean:10%`/`mean:25%` ile gerçek karşılaştırmayı
  uyguladı ve geçti — yerel benchmark akışı belgelenen tasarıma göre çalışıyor.
- Kurulumda görünen `.env` içindeki "0/18 API anahtarı dolu" mesajı **beklenen ve güvenli**
  davranıştır — gerçek anahtarlar bilinçli olarak `.sidar_keys.env` overlay'inde tutuluyor
  (§3.8); bu bir yapılandırma hatası değildir.

---

## 7. Sonuç

Sidar codebase'i, otomatik kalite kapıları açısından (coverage, lint, SAST-regex,
bundle budget, E2E smoke) olağanüstü sağlıklı ve bunu **kendi disiplini** ile
sürdürüyor — `REFACTOR_PLAN.md`/`TEST_OPTIMIZATION_PLAN.md` gibi kod ile senkron
tutulan (bazıları test ile zorlanan) yaşayan dokümanlarla mimari borcu açıkça takip
etmesi, çoğu projeden daha olgun bir mühendislik pratiği. Bu incelemenin kattığı değer,
o kapıların **göremediği** katmanlarda: (1) frontend a11y/lint kapsamının fiilen boşalmış
olması, (2) CI'ın kritik panel E2E'lerini hiç çalıştırmaması, (3) production-readiness
kapısının tek bir cache namespace'ine bağımlı tek-nokta-arıza riski, (4) semantic SAST
(CodeQL) eksikliği, ve (5) birkaç somut kod tekrarı/ölü kod/doküman sürüklenmesi
örneği. §1'deki öncelik tablosu, bunları en yüksek kaldıraçlı ilk adımdan başlayarak
sıralar.
