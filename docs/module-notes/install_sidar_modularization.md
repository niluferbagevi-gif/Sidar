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

## Kullanıcı yönlendirmesi: çevrimiçi varsayılan dinamik modül indirme

Standart çevrimiçi kullanıcı akışında ana yöntem, kök `install_sidar.sh` dosyasının
indirilmesi ve bu betiğin eksik `scripts/install_modules/` modüllerini GitHub'dan
dinamik olarak çekmesidir. Bu yaklaşım kurulum deneyimini tek parça bir araç gibi
sunar; bakım tarafında ise yardımcı/faz dosyaları modüler kalır ve yeni kurulumlar
GitHub'daki düzeltilmiş modülleri hemen alabilir:

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

Kurumsal, offline veya interneti kısıtlı ortamlarda ağdan modül indiren varsayılan
yol yerine CI tarafından üretilen monolitik Release bundle artefaktı kullanılmalıdır:

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

Böylece hibrit dağıtım korunur: çevrimiçi standart kullanıcılar dinamik modül
indiren kök betiği kullanır; kurumsal/offline kullanıcılar ise modül indirme ihtiyacı
olmadan çalışan tek parçalık Release bundle dosyasını kullanır.

## Uzak kurulum betikleri ve SHA-256 sözleşmesi

`install_sidar.sh`, eksik `uv` veya `ollama` için resmi uzak kurulum betiklerini
çalıştırmadan önce `UV_INSTALL_SHA256` ve `OLLAMA_INSTALL_SHA256` değişkenlerini
kontrol eder. Bu değişkenler boşsa ve `ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1` açıkça
verilmemişse kurulum fail-fast durur. Amaç, `https://astral.sh/uv/install.sh` veya
`https://ollama.com/install.sh` üzerinde upstream içerik değişimi/supply-chain riski
oluştuğunda sessizce doğrulanmamış betik çalıştırmamaktır.

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

### Operatör çıkış yolları (interaktif terminal, --skip-ollama, ALLOW_UNVERIFIED)

`download_verified_script` (install_sidar.sh) eksik `*_SHA256` değişkeniyle
karşılaştığında çıkış yolu seçimini ortama göre yapar:

- **İnteraktif terminal (`NO_INTERACTION` kapalı):** İndirilen betiğin SHA-256
  değeri hesaplanır ve operatöre gösterilir; `prompt_yes_no_with_timeout_default_no`
  (varsayılan = red) ile onay istenir. Onay verilirse hash o oturum süresince
  export edilir ve kuruluma devam edilir (TOFU — Trust On First Use). Onay
  red/timeout durumunda fail-fast davranışı tetiklenir ve `remote_script_checksum_hint`
  reçetesi basılır.
- **`--ci` / `--no-interaction` modu:** İnteraktif TOFU pasiftir; checksum
  boşsa fail-fast korunur. Otomasyonda `*_SHA256` değerini önceden export
  etmek gerekir.
- **`--skip-ollama`:** `.env` içinde `AI_PROVIDER=gemini|openai|anthropic`
  ayarlandığında Ollama runtime kurulumu tamamen atlanabilir. Bayrak
  `install_sidar.sh` argv parse'ında `export SKIP_OLLAMA=true` yapar; tüketici
  `sidar_install_ollama_runtime` (scripts/install_modules/utils/ollama_runtime.sh)
  fonksiyonu erken-return ile çıkar. WSL2 + NVIDIA RTX laptop / bulut LLM
  senaryolarında bu mod kurulum süresini önemli ölçüde kısaltır ve VRAM'i
  bulut sağlayıcı çağrıları için boş bırakır.
- **`ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1`:** Doğrulama bilinçli olarak atlanır.
  Yalnız geçici/test/izole ortamlarda kullanın; hesaplanan hash uyarı satırına
  yazılır (`Gelen SHA-256: …`) ki operatör değeri manifest'e eklerken görsün.

### Ollama runtime util'ı (sidar_install_ollama_runtime)

Tarihsel olarak `install_sidar.sh:ensure_prerequisites` içinde yer alan 85
satırlık Ollama indirme + sudo orchestration + healthcheck bloğu
`scripts/install_modules/utils/ollama_runtime.sh` adında ayrı bir util'a
taşındı. Bu, post-install model provisioning'i barındıran
`utils/ollama_models.sh` ile simetrik bir isim verir ve modülarizasyon
mimarisini bir adım daha ileri taşır. Util `INSTALL_UTILITY_MODULES`
listesinde ve `sidar_source_install_utils` zincirinde kayıtlıdır; manifest
ve hash doğrulaması diğer util'larla aynı akıştan geçer.

## Auto-heal ve install_remediation politikası

`scripts/install_modules/utils/install_remediation.sh`, kurulum fazlarında
transient hataları belirli bir bütçe ile retry/resume ederken deterministik
hataları fail-fast olarak ayırır. Supply-chain ve operatör deneyimi için
özellikle önemli olan davranışlar:

- **Checksum eksikliği deterministic sayılır.** `sidar_is_deterministic_failure_signal`,
  `"checksum değeri tanımlı değil"` ve `"checksum doğrulaması başarısız"`
  desenlerini deterministic listesine alır. `sidar_retry_budget_for_failure`
  bu durumda budget'i 1'e indirir; auto-heal aynı resume'u tekrar tekrar
  tetiklemez. Gerçek transient sebepler — özellikle `"sudo: timed out"` —
  retryable kalır ve `03_runtime` fazında 3 retry hakkıyla devam eder.
- **03_runtime fazında fail-fast.** `sidar_phase_remediation_strategy` `ollama_install`
  kolundan önce checksum sinyali kontrol edilir. Eşleşirse `return 1` döner;
  resume tetiklenmez ve operatör hemen guidance görür. Sudo timeout veya
  diğer transient sebepler için mevcut `ollama -v` algılaması korunur (Ollama
  yine de kurulu olabilir → success; aksi halde retry).
- **Guidance: dört çıkış yolu.** `sidar_emit_remediation_guidance`, hem
  `03_runtime` (Ollama) hem `04_workspace` (uv) fazlarında, sinyale göre
  doğru `OLLAMA_INSTALL_SHA256` veya `UV_INSTALL_SHA256` değişkenini, kurulum
  URL'sini ve `curl | less | sha256sum` reçetesini operatöre tek paragrafta
  sunar. Alternatifler bölümünde interaktif TOFU akışı,
  `ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1` ve (yalnız `ollama_install` etiketi
  için) `--skip-ollama` ayrı maddeler olarak listelenir.
- **Retry-budget tükenmesinde de guidance.** `sidar_handle_install_failure`,
  retry limiti aşıldığında `"retry-budget-exhausted"` raporundan sonra
  `sidar_emit_remediation_guidance`'ı yine çağırır; operatör "ne yapayım?"
  diye kalmaz.

Bu kontratın kırılmadığı `tests/shell/install_sidar_functions.bats` altındaki
bats testleriyle doğrulanır: deterministic algılama, sudo timeout transient
regresyonu, fail-fast routing, guidance içeriği (OLLAMA vs UV; `--skip-ollama`
sızıntı kontrolü), retry-budget tükendiğinde guidance.

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
