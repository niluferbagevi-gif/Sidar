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

## WSL2 Docker uyumluluğu

WSL2 ortamında Docker tabanlı akışların sağlıklı çalışması için Docker Desktop içinde
ilgili Linux dağıtımı (ör. Ubuntu) adına **Settings > Resources > WSL Integration**
anahtarı açık olmalıdır. Entegrasyon kapalıysa `install_sidar.sh`, etkileşimli modda
kullanıcıyı yönlendirip doğrulama ister; `NO_INTERACTION=true` veya `AUTO_INSTALL=true`
ile çalışan CI/otomasyon modlarında ise beklemeye girmeden fail-fast davranır.

Docker CLI WSL içinde yoksa veya host sistemde kurulması gerekiyorsa kurulum
komutuna `--install-docker-cli` bayrağı eklenebilir:

```bash
./install_sidar.sh --install-docker-cli
```
