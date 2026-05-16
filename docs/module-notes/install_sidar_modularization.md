# install_sidar.sh modüler geliştirme notu

Bu repo, kurulum betiğini geliştirme aşamasında modüler tutmak için şu yapıyı kullanır:

- `install_sidar.sh`: kullanıcıların çalıştırdığı ana giriş betiği
- `scripts/install_modules/*.sh`: fonksiyon bazlı modüller
- `scripts/tools/bundle_install_sidar.sh`: release için tek dosya bundle üretici

## Bundle üretimi

```bash
bash scripts/tools/bundle_install_sidar.sh
```

Komut sonunda tek dosyalık dağıtım çıktısı:

- `dist/install_sidar.sh`

`dist/` çıktısı repoya commit edilmez; `.github/workflows/publish-installer.yml` ana dala gelen kurulum değişikliklerinde bundle'ı üretir, self-contained olduğunu doğrular ve `installer-latest` release asset'i olarak yayınlar. Kullanıcı dokümantasyonunda repoyu klonlamadan kurulum için `https://github.com/niluferbagevi-gif/Sidar/releases/download/installer-latest/install_sidar.sh` URL'si tercih edilmelidir.

Bu yaklaşım ile:

- PR incelemeleri modül bazında küçülür,
- bakım/debug kolaylaşır,
- dağıtımda tek dosya avantajı korunur.
