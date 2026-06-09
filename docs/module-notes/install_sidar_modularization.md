# install_sidar.sh modüler geliştirme notu

Bu repo, kurulum betiğini geliştirme aşamasında modüler tutmak için şu yapıyı kullanır:

- `install_sidar.sh`: repo checkout içinden çalıştırılan ana orkestratör ve dağıtım girişi
- `install/*.sh`: insan incelemesi ve dış otomasyonlar için kararlı faz alias dosyaları
- `scripts/install_modules/phases/*.sh`: faz uygulamalarının tek doğruluk kaynağı
- `scripts/install_modules/utils/*.sh`: fonksiyon bazlı yardımcı modüller
- `scripts/tools/bundle_install_sidar.sh`: release için tek dosya bundle üretici


## Faz alias sözleşmesi

Öncelikli mimari hedef, büyük `install_sidar.sh` dosyasının iş mantığını fazlara ayırıp
ana betiği yalnızca orkestratör/dağıtım giriş noktası olarak tutmaktır. Bu sözleşme
şu şekilde uygulanır:

- `install/01_context.sh`, `install/04_workspace.sh` gibi kök faz alias'ları dışarıdan
  okunabilir kararlı yollar sağlar.
- Alias dosyaları iş mantığı içermez; ilgili `scripts/install_modules/phases/*.sh`
  dosyasını kaynaklar.
- Yeni veya büyüyen kurulum adımları önce `scripts/install_modules/phases/` veya
  `scripts/install_modules/utils/` altına taşınmalı, `install_sidar.sh` içinde yalnızca
  faz çağrısı / bundle uyumluluğu kalmalıdır.

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
