# Frontend TypeScript geçiş kampanyası

## Sahiplik ve takvim

- **Sahip:** Frontend bakım ekibi
- **Başlangıç envanteri:** 2026-07-30
- **İlk ilerleme değerlendirmesi:** 2026-09-30
- **Hedef tamamlanma:** 2027-03-31
- **Takvim kaydı:** `docs/reminders/frontend-typescript-review-2026-09-30.ics`

Başlangıçta `web_ui_react/src` altında 16 `.js`, 42 `.jsx`, 1 `.ts` ve 0 `.tsx`
dosyası vardı. İlk dilimde `src/hooks/useFormState.ts` de TypeScript'e taşındı;
İlk state/logic dilimlerinden sonra ratchet envanteri 15 `.js`, 42 `.jsx`, 3 `.ts`
ve 0 `.tsx` gösterir. Saf swarm graph oluşturma katmanı
`src/lib/swarmFlowGraph.ts` olarak taşınmış ve dış API tipleri tanımlanmıştır.
`checkJs: false` olduğu için `npm run typecheck`, JavaScript/JSX
bileşen ağacına tam tip güvencesi sağlamaz. Yaklaşık 2974 mevcut hatayı tek seferde
kalite kapısına taşımak yerine geçiş aşağıdaki ratchet ve küçük domain dilimleriyle
yürütülür.

## Zorunlu ratchet

`typescript-migration-baseline.json`, en fazla 57 untyped (`.js` + `.jsx`) ve en az
3 typed (`.ts` + `.tsx`) kaynak dosyasına izin verir. `npm run typecheck:inventory`:

- `.js`/`.jsx` toplamındaki net artışı fail-closed reddeder;
- mevcut `.ts`/`.tsx` dosyalarının silinmesi veya untyped biçime döndürülmesini reddeder;
- `.jsx` → `.tsx` dönüşümlerinde doğal olarak geçer.

Ölçülen ilerleme baseline değerlerini yalnız daha sıkı yönde değiştirebilir:
`maximum_untyped_files` düşürülür ve `minimum_typed_files` artırılır. Sayıları gevşeten
değişiklikler kampanya sahibinin açık onayını gerektirir.

## Aşamalar ve kapılar

1. **2026-09-30 — altyapı ve düşük bağımlılıklı hook'lar:** ortak API tipleri ile saf
   hook/helper dosyalarını taşı; `npm run typecheck`, lint ve ilgili Vitest testlerini çalıştır.
2. **2026-12-15 — veri ve orchestration katmanı:** `src/lib` ve state/controller hook'larını
   taşı; API response tiplerini runtime doğrulamanın yerine geçecek şekilde kullanma.
3. **2027-02-15 — React bileşenleri:** leaf bileşenlerden başlayıp props/event/ref tiplerini
   ekleyerek `.tsx`'e geç; her dilimde component testleri ve accessibility lint korunur.
4. **2027-03-31 — kapı aktivasyonu:** untyped kaynak kalmadığında `allowJs` ve `checkJs`
   compatibility ayarlarını kaldır; envanter ratchet'ini tam TypeScript kapısıyla değiştir.

Her taşıma PR'ı dönüştürülen dosyaları, baseline'ın eski/yeni değerini ve çalıştırılan
Vitest kapsamını listelemelidir. `any`, geniş `unknown` cast'leri veya toplu `@ts-ignore`
kullanımı dosya uzantısını değiştirmek için kabul kriteri değildir.
