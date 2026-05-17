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

## Standalone dağıtım sözleşmesi

Kullanıcılar repo olmadan `wget`/`curl` ile tek dosyalık kurulum yapacaksa hedef dosya
raw repo kökündeki modüler `install_sidar.sh` değil, CI tarafından üretilen release
bundle artefaktı olmalıdır:

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

Raw modüler `install_sidar.sh` içinde uzak modülleri indiren fallback korunur; ancak
standalone kullanımda tercih edilen yol release bundle artefaktıdır. Böylece kök betik
ile `scripts/install_modules/` içeriğinin ayrı ayrı indirilmesi veya versiyon drift'i
riski kullanıcıya yansıtılmaz.
