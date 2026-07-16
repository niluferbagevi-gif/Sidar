# install_sidar.sh modüler geliştirme notu

Bu repo, kurulum betiğini geliştirme aşamasında modüler tutmak için şu yapıyı kullanır:

- `install_sidar.sh`: repo checkout içinden çalıştırılan ana giriş betiği
- `scripts/install_modules/*.sh`: fonksiyon bazlı modüller
- `scripts/tools/bundle_install_sidar.sh`: release için tek dosya bundle üretici

## Bundle üretimi

```bash
bash scripts/tools/bundle_install_sidar.sh
```

Komut sonunda tek dosyalık dağıtım çıktısı:

- `dist/install_sidar.sh`

Bu yaklaşım ile:

- PR incelemeleri modül bazında küçülür,
- bakım/debug kolaylaşır,
- dağıtımda tek dosya avantajı korunur.


## Modularization roadmap / TODOs

- [ ] **Ollama install step extraction (A/Sorun 2):** İlk taşıma
  `scripts/install_modules/phases/03_runtime_ollama.sh` içindeki
  `_ollama_install_step` ile başlatıldı ve uzak betik doğrulaması
  `scripts/install_modules/utils/remote_script.sh` altında ortaklaştırıldı. Bu TODO,
  kalan takip işlerini görünür tutar: Ollama kurulum adımının monolitik
  `install_sidar.sh` içindeki legacy yardımcı fonksiyon bağımlılıkları azaltılmalı,
  phase modülü tek başına test edilebilir hale getirilmeli ve release bundle üretimi
  sonrasında bu sınırın korunması CI dokümantasyonunda açıkça izlenmelidir.
- [ ] **Bootstrap facade inceltme (2026-07-16 durum notu):** `install_sidar.sh`
  hâlâ remote module bootstrap, embedded manifest/hash doğrulama ve fallback cache
  orchestration sorumluluklarını taşıyor. UID-scoped `mktemp -d` cache, symlink/owner guard ve
  TOFU dokümantasyonu eklendi; sıradaki düşük riskli adım bu bootstrap/hash guard
  akışını `scripts/install_modules/bootstrap.sh` gibi ayrı bir modüle taşırken raw
  fallback modül indirme testlerini korumaktır.

## Cross-module değişken lint sözleşmesi

`install_sidar.sh` ve `scripts/install_modules/` altındaki faz/yardımcı modüller
aynı Bash sürecinde `source` edilerek çalışır. Bu nedenle ana betikte hazırlanan
bazı durum değişkenleri, ShellCheck'in tek dosya analizinde okunmuyor gibi görünse
de sourced modüller tarafından tüketilir. Yeni modülerleştirme veya taşıma
çalışmalarında bu değişkenler için aşağıdaki kural zorunludur:

- Cross-module okunan her değişkenin ilk atamasının hemen üstüne tek satırlık
  `# shellcheck disable=SC2034` yorumu eklenmelidir.
- Yorum, değişkeni okuyan sourced modül yolunu açıkça belirtmelidir; örn.
  `scripts/install_modules/phases/12_alembic.sh reads this sourced state`.
- Aynı değişken runtime içinde başka dallarda tekrar atanıyor ve ShellCheck aynı
  atama noktasında SC2034 üretiyorsa, ilgili atamanın hemen üstünde de aynı
  kapsamı açıklayan dar yorum kullanılmalıdır.
- Sadece SC2034'ü susturmak için değişken `export` edilmemelidir; `export` yalnız
  gerçekten child process ortamına aktarılması gereken değerlerde tercih edilir.
- Yeni faz veya yardımcı modül eklendiğinde, ana betikte hazırlanan cross-module
  state değişkenleri için bu dosyadaki sözleşme ve ilgili yorumlar PR içinde
  birlikte güncellenmelidir.

Örnek:

```bash
# shellcheck disable=SC2034  # scripts/install_modules/phases/12_alembic.sh reads this sourced state.
MIGRATION_DOCKER_POLICY="auto"
```

## DB credential hardening sorumluluk sınırı

Veritabanı parola güçlendirme akışının canonical implementation'ı
`scripts/install_modules/utils/db_credentials.sh` içindedir. Kök `install_sidar.sh`
dosyasındaki aynı isimli fonksiyon, eski monolitik/source test akışları ve geçiş
dönemi için tutulan uyumluluk katmanıdır; workspace fazı çalışırken
`scripts/install_modules/phases/04_workspace.sh` ilgili utility dosyalarını tekrar
source ederek modüler implementation'ı etkin hale getirir.

`PRE_HARDEN_DB_PASSWORD` değişkeni sadece Alembic auth-repair aşamasına eski
parolayı recovery adayı olarak aktarmak için kullanılmalıdır. Yeni kod,
bu değişkeni doğrudan set etmek yerine `db_credentials.sh` içindeki
`sidar_record_pre_harden_db_password` yardımcısını çağırmalıdır. Böylece
`scripts/install_modules/phases/12_alembic.sh` tarafından okunan recovery handoff
tek yazıcı üzerinden yönetilir; `12_alembic.sh` bu değeri üretmez veya değiştirmez,
yalnızca okur.

## Kullanıcı yönlendirmesi: varsayılan Release bundle, raw fallback son çare

Standart çevrimiçi kullanıcı akışında ana yöntem, GitHub Release üzerinden
yayınlanan tek dosyalık bundle `install_sidar.sh` artefaktının indirilmesidir.
Bundle, `scripts/tools/bundle_install_sidar.sh` tarafından üretildiği için
kurulum bootstrap aşamasında `scripts/install_modules/` altındaki modülleri
GitHub raw üzerinden tek tek indirmez; bu da 429/5xx edge throttling riskini
azaltır:

```bash
curl -fsSL https://github.com/niluferbagevi-gif/Sidar/releases/latest/download/install_sidar.sh -o install_sidar.sh
# veya: wget -O install_sidar.sh https://github.com/niluferbagevi-gif/Sidar/releases/latest/download/install_sidar.sh
chmod +x install_sidar.sh
./install_sidar.sh
```

Raw `main/install_sidar.sh` URL'i yalnız hedef ref için Release bundle henüz yoksa
son çare fallback olarak kullanılmalıdır; bu yol eksik modülleri runtime'da
indirebildiği için GitHub raw 429/5xx kısıtlarına daha açıktır:

```bash
curl -fsSL https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/main/install_sidar.sh -o install_sidar.sh
# veya: wget -O install_sidar.sh https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/main/install_sidar.sh
chmod +x install_sidar.sh
./install_sidar.sh
```

Geliştirici katkısı, test yazımı, self-healing patch/rollback incelemesi veya uzun
coverage kampanyaları için repo klonu ayrıca desteklenir ve bu senaryolarda daha
uygun çalışma şeklidir:

```bash
git clone https://github.com/niluferbagevi-gif/Sidar.git
cd Sidar
uv sync --all-extras
./install_sidar.sh
```

## Standalone / offline dağıtım sözleşmesi

Kurumsal, offline, interneti kısıtlı ve normal temiz kurulum ortamlarında ağdan
modül indiren raw fallback yerine CI tarafından üretilen monolitik Release bundle
artefaktı kullanılmalıdır:

```bash
curl -fsSL https://github.com/niluferbagevi-gif/Sidar/releases/latest/download/install_sidar.sh -o install_sidar.sh
# veya: wget -O install_sidar.sh https://github.com/niluferbagevi-gif/Sidar/releases/latest/download/install_sidar.sh
chmod +x install_sidar.sh
./install_sidar.sh --ci
```

CI akışı `.github/workflows/ci.yml` içinde `scripts/tools/bundle_install_sidar.sh`
komutunu çalıştırır, `dist/install_sidar.sh` dosyasını syntax-check'ten geçirir,
`standalone-install-sidar` artefaktı olarak yükler ve `v*` tag release'lerinde aynı
dosyayı GitHub Release asset'i olarak yayınlar.

Böylece hibrit dağıtım korunur: standart kullanıcılar Release bundle kullanır; raw fallback dinamik modül
indiren kök betiği kullanır; kurumsal/offline kullanıcılar ise modül indirme ihtiyacı
olmadan çalışan tek parçalık Release bundle dosyasını kullanır.

## Uzak kurulum betikleri ve SHA-256 sözleşmesi

`install_sidar.sh`, eksik `uv` veya `ollama` için resmi uzak kurulum betiklerini
çalıştırmadan önce `scripts/install_modules/remote_checksums.env` içindeki reviewed
default checksum değerlerini yükler, ardından `UV_INSTALL_SHA256` ve
`OLLAMA_INSTALL_SHA256` değişkenlerini kontrol eder. Shell ortamında açıkça verilen
değerler dosyadaki default değerlerden önceliklidir. Uzak betik indirme/doğrulama
yardımcıları `scripts/install_modules/utils/remote_script.sh` dosyasındadır; Ollama
kurulum adımı da `scripts/install_modules/phases/03_runtime_ollama.sh` içinde
`_ollama_install_step` olarak tutulur. Bu değişkenler boşsa ve
`ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1` açıkça verilmemişse kurulum fail-fast durur.
Amaç, `https://astral.sh/uv/install.sh` veya `https://ollama.com/install.sh` üzerinde
upstream içerik değişimi/supply-chain riski oluştuğunda sessizce doğrulanmamış betik
çalıştırmamaktır.

Operatör yeni bir WSL/Ubuntu makinede önce betiği indirip incelemeli, sonra aynı
dosyadan SHA-256 üretip export etmelidir:

```bash
tmp_uv=$(mktemp)
curl -fsSL --retry 3 --retry-all-errors -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' \
  https://astral.sh/uv/install.sh -o "$tmp_uv"
less "$tmp_uv"
export UV_INSTALL_SHA256=$(sha256sum "$tmp_uv" | awk '{print $1}')
rm -f "$tmp_uv"

tmp_ollama=$(mktemp)
curl -fsSL --retry 3 --retry-all-errors -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' \
  https://ollama.com/install.sh -o "$tmp_ollama"
less "$tmp_ollama"
export OLLAMA_INSTALL_SHA256=$(sha256sum "$tmp_ollama" | awk '{print $1}')
rm -f "$tmp_ollama"
```

Hash değerlerini repoya kalıcı varsayılan olarak eklemek, upstream betikler haber
vermeden değiştiğinde yeni kurulumları yine kıracağı için bilinçli release/pin
kararı gerektirir. Air-gapped kurulumlarda tercih edilen yol, uzak betik yerine
`offline_packages/manifest.json` tarafından doğrulanan offline bundle kullanmaktır.

`ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1` yalnız geçici/test ortamlarında uzak kurulum
betikleri veya `scripts/install_modules` modül hash doğrulaması için risk kabulü
anlamına gelir. `core/memory.py` / `core/multimodal.py` çekirdek manifest
uyuşmazlığında bu bayrak çözüm değildir; normal kullanıcı güncellenmiş installer'ı
veya manifesti güncel belirli bir commit/tag'i beklemeli, geliştirici ise
`scripts/sync_install_manifest.sh` ile main branch manifest senkronizasyonunu
düzeltmelidir.

### Auto-heal: uzak betik checksum metadata eksikliği deterministik kabul edilir

`UV_INSTALL_SHA256` veya `OLLAMA_INSTALL_SHA256` tanımlı değilse `install_sidar.sh`
fail-fast durur. Bu hata; `scripts/install_modules/utils/install_remediation.sh`
içindeki `sidar_is_remote_script_checksum_missing` yardımcısı tarafından
**deterministik** olarak sınıflandırılır:

- `sidar_is_deterministic_failure_signal` 0 döner → retry bütçesi 1'e iner.
- `sidar_phase_remediation_strategy` (her fazda) `remote-script-checksum-missing`
  raporu yazıp `no-retry;manual-fix-required;missing-var=<DEĞİŞKEN>` aksiyonunu
  kaydeder ve resume planlamaz.
- `sidar_emit_remediation_guidance` operatöre eksik değişkene göre ilgili TOFU
  akışını (ilgili `*_SHA256` ve betik URL'i) hatırlatır.

Eski transient ollama_install akışı (örn. `sudo: timed out`) korunur: ollama
çalışırsa "treat-as-success", aksi halde "rerun-install-script;refresh-sudo"
stratejisi devreye girer.

## WSL2 Docker uyumluluğu

WSL2 ortamında Docker tabanlı akışların sağlıklı çalışması için Docker Desktop içinde
ilgili Linux dağıtımı (ör. Ubuntu) adına **Settings > Resources > WSL Integration**
anahtarı açık olmalıdır. Entegrasyon kapalıysa `install_sidar.sh`, etkileşimli modda
kullanıcıyı yönlendirip doğrulama ister; `NO_INTERACTION=true` veya `AUTO_INSTALL=true`
ile çalışan CI/otomasyon modlarında ise beklemeye girmeden fail-fast davranır.

Windows tarafında `powershell.exe -File` ile çağrılan
`scripts/install_modules/utils/wsl_integration_autofix.ps1`, Windows PowerShell 5.1'in
BOM'suz UTF-8 kaynak dosyalarını ANSI code page ile yorumlamasını engellemek için UTF-8 BOM ile
saklanmalıdır. Bu dosya yeniden kaydedilirken BOM kaldırılmamalıdır; aksi halde kullanıcıya görünen
Türkçe autofix hata mesajlarında mojibake oluşur.

Docker CLI WSL içinde yoksa veya host sistemde kurulması gerekiyorsa kurulum
komutuna `--install-docker-cli` bayrağı eklenebilir:

```bash
./install_sidar.sh --install-docker-cli
```
