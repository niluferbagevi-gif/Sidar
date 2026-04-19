# install_sidar.sh

- **Kaynak dosya:** `install_sidar.sh`
- **Not dosyası:** `docs/module-notes/install_sidar.sh.md`
- **Amaç:** Kabuk scripti.
- **Durum:** İncelendi ve `docs/module-notes` altında dokümante edildi.

## Son güncellemeler (v5.2.2)

- Etkileşimsiz kurulum için yeni bayraklar eklendi:
  - `--non-interactive`
  - `--yes`
  - `--headless` (GUI adımlarını atlayan etkileşimsiz profil)
- Etkileşimsiz modda tüm onay soruları otomatik varsayılan yanıtla ilerler.
- Conda uyarı gürültüsünü azaltmak için `notify_outdated_conda=false` ayarı otomatik uygulanır.
- React build sonrası `npm audit --audit-level=moderate` kontrolü eklenmiştir.
