# Frontend ESLint 10 geçiş planı

## Durum

**Güncelleme (2026-09-25):** `GHSA-mh99-v99m-4gvg` için tutulan geçici npm audit
istisnası 2026-09-25'te kaldırıldı. `1.1.17` backport'unu bypass eden
`GHSA-rgw5-rvv9-x895` yayınlandığında `overrides.brace-expansion` kalıcı pini gerçek
upstream düzeltmesi olan `1.1.18`'e yükseltilmişti; o tarihten beri
`npm audit --audit-level=high` sıfır bulgu raporluyor ve istisna hiç tetiklenmiyordu.
Planın çıkış ölçütü ("advisory zinciri kaybolduğunda istisnayı kaldır") karşılandığı
için `scripts/npm_audit_safe.js` içindeki `brace-expansion` allowlist'i, test saati
override'ı ve istisna artefaktı silindi. Artık istisnasız bir kapı vardır: her `high`
veya `critical` bulgu `vulnerability` kategorisiyle fail-closed durur.

`overrides.brace-expansion` kalıcı pini (`1.1.18`) korunur; `eslint-plugin-jsx-a11y` →
`minimatch@3` zinciri hâlâ `brace-expansion@1.x` çeker ve pin, bu zincirin
`GHSA-rgw5-rvv9-x895` düzeltmesini içeren sürümde kalmasını garanti eder. Pin, ancak
ESLint 10 geçişi sonrasında dependency ağacında artık gerekmediği doğrulanırsa
kaldırılabilir.

Geriye yalnız ESLint 10 sürüm geçişi kalır; bu artık bir güvenlik istisnası değil,
peer dependency desteğine bağlı bir bakım işidir. Geçmiş istisnanın ayrıntıları
`CHANGELOG.md` ve git geçmişinde tutulur.

## ESLint 10 neden hemen uygulanmıyor?

2026-07-30 doğrulamasında npm registry aşağıdaki peer dependency durumunu bildirmiştir:

- `eslint@10.8.0` güncel majör sürümdür ve Node.js `^20.19.0 || ^22.13.0 || >=24`
  gerektirir.
- `eslint-plugin-react@7.37.5`, ESLint desteğini `^9.7` ile sınırlar.
- `eslint-plugin-jsx-a11y@6.10.2`, ESLint desteğini `^9` ile sınırlar.
- `eslint-plugin-react-hooks@7.1.1`, ESLint 10'u destekler.

Bu nedenle yalnız `eslint` paketini yükseltmek desteklenmeyen peer dependency ağacı
oluşturur. `npm audit fix --force` kullanmak, React lint/a11y kalite kapılarının sessizce
bozulması veya eski eklenti sürümlerine downgrade edilmesi riskini taşır.

## Bakım işi ve çıkış ölçütleri

**Sahip:** Frontend bakım ekibi  
**2026-09-30 yeniden değerlendirmesi (2026-09-25'te yapıldı):** npm registry'de
`eslint@10.11.0`, `@eslint/js@10.0.1` ve `typescript-eslint@8.70.1` ESLint 10'u
desteklerken `eslint-plugin-react@7.37.5` (`^9.7`) ve `eslint-plugin-jsx-a11y@6.10.2`
(`^9`) hâlâ en güncel sürümlerdir ve ESLint 10'u peer dependency olarak kabul etmez.
Engel sürdüğü için geçiş ertelendi.
**Sonraki yeniden değerlendirme:** 2026-12-31 veya iki eklentiden birinin ESLint 10
destekli sürümü yayımlandığında (hangisi önce olursa).
**Takvim kaydı:** `docs/reminders/frontend-eslint-10-review-2026-12-31.ics`
**Otomatik takip:** `.github/workflows/frontend-security-review.yml`, her pazartesi
06:17 UTC'de strict audit'i çalıştırır ve güvenlik kanıtını artefakt olarak saklar.
Böylece lint araç zincirinde yeni bir advisory yayımlanırsa, PR veya push olmasa bile
en geç bir hafta içinde görünür olur; `workflow_dispatch` bakım PR'ında talep üzerine
yeniden doğrulama sağlar.

Kalıcı geçiş ayrı bir bakım PR'ında şu sırayla yapılmalıdır:

1. `eslint-plugin-react` ve `eslint-plugin-jsx-a11y` sürümlerinin ESLint 10'u resmi
   peer dependency olarak desteklediğini doğrula.
2. `eslint` ve `@eslint/js` paketlerini aynı ESLint 10 sürüm ailesine yükselt; uyumlu
   React, hooks ve accessibility eklentilerini birlikte güncelle. `package.json`
   `engines.node` aralığını ve CI Node sürümünü ESLint 10'un desteklediği sürümlerle
   eşleştir.
3. `npm install` ile lockfile'ı yeniden üret ve `overrides.brace-expansion` girdisini
   yalnız dependency ağacında artık gerekmediği doğrulanırsa kaldır.
4. Flat config/rule davranış değişikliklerini incele; kuralları geçici olarak kapatmak
   yerine kaynak kodu veya açık gerekçeli yapılandırmayı güncelle.
5. Aşağıdaki doğrulama kapılarının tamamını çalıştır.
6. Geçiş tamamlandığında bu bakım kaydını ve takvim hatırlatıcısını kaldır.

```bash
cd web_ui_react
npm ls eslint @eslint/js eslint-plugin-react eslint-plugin-react-hooks eslint-plugin-jsx-a11y
npm run lint
npm run typecheck
npm run test:coverage
npm run build
FRONTEND_NPM_AUDIT_ALLOW_NETWORK_FAILURE=0 npm run audit:high
```

`npm audit` yalnız registry metadata'sını yeniden sınıflandırırsa fakat kurulu ağaç
değişmezse, yeni bir allowlist eklemeden önce advisory kimliği, lockfile sürümleri ve
upstream backport durumu yeniden doğrulanmalı; gerekirse istisna yeni, sonlu bir tarih ve
fail-closed süre sonu ile ayrı bir bakım değişikliğinde eklenmelidir.
