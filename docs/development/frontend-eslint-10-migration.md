# Frontend ESLint 10 geçiş planı

## Durum

Frontend `npm audit`, aynı bağımlılık zincirinden yayılan yedi `high` kayıt gösterir:

`eslint` / ESLint yapılandırma paketleri ve React lint eklentileri → `minimatch` →
`brace-expansion` → `GHSA-mh99-v99m-4gvg`.

Bu kayıtlar yedi bağımsız güvenlik açığı değildir. Sidar, `brace-expansion` sürümünü
upstream güvenlik backport'unu içeren tam `1.1.17` sürümüne sabitler. npm advisory
aralığı bu backport'u tanımadığı sürece `scripts/npm_audit_safe.js`, yalnız aşağıdaki
koşulların tümü sağlanırsa bu tek advisory zincirini geçici olarak kabul eder:

1. Advisory kaynak kimliği tam olarak `1124334` olmalıdır.
2. Lockfile içindeki bütün `brace-expansion` örnekleri tam olarak `1.1.17` olmalıdır.
3. Bütün raporlanan paketler yalnızca bu advisory zincirine ulaşmalıdır.
4. İlişkisiz herhangi bir `high` veya `critical` bulgu kalite kapısını kapatmalıdır.

Dolayısıyla bu istisna genel bir `npm audit` susturması değildir. Paket üretim
bundle'ına dahil olmayan lint araç zincirindedir ve fail-closed allowlist ile sınırlıdır.

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
**İlk yeniden değerlendirme:** 2026-09-30 veya npm advisory aralığı/plugin peer
dependency metadata'sı değiştiğinde (hangisi önce olursa).
**Takvim kaydı:** `docs/reminders/frontend-eslint-10-review-2026-09-30.ics`

Bu tarih yalnız takvim hatırlatıcısı değildir. `scripts/npm_audit_safe.js`, UTC olarak
2026-09-30 başladığında geçici allowlist'i otomatik olarak geçersiz sayar ve aynı
advisory zinciri devam ediyorsa `expired_exception` kategorisiyle fail-closed durur.
İstisna kabul edildiği her koşuda terminal çıktısı son tarihi ve kalan gün sayısını
gösterir; ayrıca `artifacts/frontend-security/npm-audit-exception.json` makine-okunur
takip artefaktını üretir. CI bakım planlaması terminal metnini ayrıştırmak yerine bu
artefaktın `exception_review_at` ve `days_remaining` alanlarını kullanabilir.
İstisnanın süresini ileri taşımak yerine aşağıdaki yeniden değerlendirme tamamlanmalı;
devam kararı gerekiyorsa güncel registry/upstream kanıtı ve yeni, sonlu bir tarih ayrı
bir bakım değişikliğinde kaydedilmelidir.

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
6. Audit raporunda advisory zinciri kaybolduğunda
   `PATCHED_BRACE_EXPANSION_*` istisnasını ve bu bakım kaydını kaldır.

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
değişmezse, istisnayı genişletmek yerine advisory kimliği, lockfile sürümleri ve upstream
backport durumu yeniden doğrulanmalıdır.
