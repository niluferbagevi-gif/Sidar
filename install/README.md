# Sidar installer phase aliases

`install/` dizini, kurulum akışını inceleyen geliştiriciler ve dış otomasyonlar için
kararlı faz giriş noktalarını tutar. Gerçek uygulama hâlâ tek doğruluk kaynağı olan
`scripts/install_modules/` altında yaşar:

- Faz uygulamaları: `scripts/install_modules/phases/*.sh`
- Fonksiyonel yardımcılar: `scripts/install_modules/utils/*.sh`
- Ana orkestratör / dağıtım girişi: `install_sidar.sh`

`install_sidar.sh` bilinçli olarak standalone dağıtım/orchestrator rolünü korur: repo
checkout içinde modülleri kaynaklar, tek dosya/offline dağıtım içinse
`scripts/tools/bundle_install_sidar.sh` tarafından bundle üretilebilir. Bu yüzden yeni
kurulum davranışı eklenirken iş mantığı önce `scripts/install_modules/phases/` veya
`scripts/install_modules/utils/` altına taşınmalı; gerekiyorsa bu dizindeki ince alias
dosyaları sadece kararlı yol sözleşmesini sürdürmelidir.

Mevcut faz alias'ları:

- `install/01_context.sh` → `scripts/install_modules/phases/01_context.sh`
- `install/02_repo.sh` → `scripts/install_modules/phases/02_repo.sh`
- `install/03_runtime.sh` → `scripts/install_modules/phases/03_runtime.sh`
- `install/04_workspace.sh` → `scripts/install_modules/phases/04_workspace.sh`
- `install/05_frontend.sh` → `scripts/install_modules/phases/05_frontend.sh`
- `install/06_services.sh` → `scripts/install_modules/phases/06_services.sh`
- `install/07_finish.sh` → `scripts/install_modules/phases/07_finish.sh`
