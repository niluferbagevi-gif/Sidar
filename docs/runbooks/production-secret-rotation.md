# Production Secret Rotation Runbook

Bu runbook, installer tarafından yerel geliştirme kolaylığı için `.env` kaynaklı olarak
`.env.development`, `.env.test`, `.env.production` ve `.env.advanced` dosyalarına
senkronize edilen ortak secret'ların production ortamına taşınmadan önce ayrıştırılması
için zorunlu operasyon kontrol listesidir.

## Kapsam: production öncesi rotate edilmesi gereken 8 ortak secret

Aşağıdaki değerler installer tarafından yerel/dev/test zincirinde aynı tutulabilir. Bu
paylaşım lokal kullanım ve smoke testleri için kabul edilebilir; ancak `.env.production`
gerçek bir dağıtıma kaynak olacaksa bu 8 değer **prod'a özel, dev/test'ten farklı**
secret'larla değiştirilmelidir:

1. `API_KEY`
2. `JWT_SECRET_KEY`
3. `MEMORY_ENCRYPTION_KEY`
4. `AUTONOMY_WEBHOOK_SECRET`
5. `SWARM_FEDERATION_SHARED_SECRET`
6. `GITHUB_WEBHOOK_SECRET`
7. `GRAFANA_ADMIN_PASSWORD`
8. `METRICS_TOKEN`

## Neden zorunlu?

- `.env.test` veya lokal `.env` sızarsa aynı değerlerin production'da kullanılması JWT
  imzalama, webhook doğrulama, metrics erişimi, Grafana yönetici hesabı ve Fernet tabanlı
  bellek şifrelemesini de riske atar.
- `MEMORY_ENCRYPTION_KEY` özel olarak veri kurtarma riski taşır: eski anahtar olmadan
  önceki Fernet ile şifrelenmiş bellek kayıtları pratik olarak kurtarılamaz.
- Production secret'ları repo içindeki dotenv dosyalarından ziyade deployment secret
  manager, Kubernetes Secret, GitHub Actions environment secret, Vault/SOPS/SealedSecrets
  veya eşdeğer bir dış secret kaynağında tutulmalıdır.

## Production cutover checklist

1. **Snapshot al:** `.env`, `.env.test`, `.env.production` ve hedef secret manager
   değerlerini parola göstermeden envantere al; dosya izinlerinin `600` veya daha sıkı
   olduğunu doğrula.
2. **Yeni production değerleri üret:** Her secret için prod'a özel rastgele değer üret.
   Repo içi dry-run/staging dotenv kullanılıyorsa önerilen fail-closed komut:

   ```bash
   uv run python -m scripts.rotate_production_secrets --env-file .env.production \
     --apply --ack-memory-key-impact
   ```

   Komut sekiz değeri atomik olarak değiştirir, dosya modunu `600` yapar, hiçbir
   secret değerini loglamaz ve local/dev/test profilleriyle eşitlik veya zayıf değer
   kalırsa başarısız olur. `--ack-memory-key-impact`, 5. adımdaki veri kurtarma kararının
   kaydedildiğine dair açık operatör onayıdır. Değerleri dış secret manager'da üretecek
   ekipler için eşdeğer manuel örnekler:

   ```bash
   # URL-safe tokenlar için
   uv run python - <<'PY'
   import secrets
   for key in (
       "API_KEY",
       "JWT_SECRET_KEY",
       "AUTONOMY_WEBHOOK_SECRET",
       "SWARM_FEDERATION_SHARED_SECRET",
       "GITHUB_WEBHOOK_SECRET",
       "GRAFANA_ADMIN_PASSWORD",
       "METRICS_TOKEN",
   ):
       print(f"{key}={secrets.token_urlsafe(48)}")
   PY

   # Fernet uyumlu MEMORY_ENCRYPTION_KEY için
   uv run python - <<'PY'
   from cryptography.fernet import Fernet
   print(Fernet.generate_key().decode())
   PY
   ```

3. **Secret manager'a yaz:** Yeni değerleri production secret kaynağına ekle. Repo
   içindeki `.env.production` yalnız staging/dry-run için kullanılacaksa aynı prod
   değerleriyle güncelle; gerçek prod için dosyayı kalıcı sır deposu yapma.
4. **Dev/test ayrışmasını doğrula:** Aşağıdaki değerler production ile byte-birebir aynı
   kalmamalıdır: `.env`, `.env.development`, `.env.test`, `.env.advanced`. Değerleri
   göstermeyen doğrulama komutu:

   ```bash
   uv run python -m scripts.rotate_production_secrets --env-file .env.production
   ```
5. **MEMORY_ENCRYPTION_KEY geçişini planla:** Var olan şifreli bellek verisi korunacaksa
   eski anahtarı geçici olarak `MEMORY_ENCRYPTION_KEY_PREVIOUS` içine yaz. Birden fazla
   eski anahtar en yeniden en eskiye virgülle ayrılabilir. Yeni kayıtlar yalnız güncel
   `MEMORY_ENCRYPTION_KEY` ile şifrelenirken okumalar güncel anahtardan sonra fallback
   listesini dener. Bakım penceresinde eski kayıtları yeni anahtarla re-encrypt ettikten
   sonra fallback listesini temizle. Veri korunmayacaksa eski şifreli kayıtları arşivle
   veya kontrollü biçimde temizle.
6. **Webhook sağlayıcılarını güncelle:** GitHub/autonomy/swarm federation endpoint'lerini
   yeni webhook secret'larıyla aynı bakım penceresinde güncelle.
7. **Servisleri yeniden başlat:** Tüm web/worker pod veya container'larının aynı secret
   jenerasyonunu okuduğunu doğrula; kademeli rollout sırasında eski/yeni JWT veya webhook
   secret karışımı bırakma.
8. **Doğrula:** Health, auth, webhook signature, `/metrics` bearer token ve Grafana login
   smoke kontrollerini çalıştır. Başarısızlıkta rollback için önceki production secret
   snapshot'ına dön.

## Kabul kriteri

Production geçişi yalnızca şu koşullar sağlandığında onaylanır:

- 8 secret'ın tamamı production secret kaynağında dolu ve güçlüdür.
- Production değerleri dev/test/local dotenv zincirindeki değerlerle aynı değildir.
- `MEMORY_ENCRYPTION_KEY` için veri kurtarma/yeniden şifreleme kararı belgelenmiştir.
- Webhook, metrics ve Grafana smoke kontrolleri yeni değerlerle geçmiştir.
