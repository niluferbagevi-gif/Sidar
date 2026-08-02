# Frontend TypeScript geçiş kampanyası

## Sahiplik ve takvim

- **Sahip:** Frontend bakım ekibi
- **Başlangıç envanteri:** 2026-07-30
- **İlk ilerleme değerlendirmesi:** 2026-09-30
- **Hedef tamamlanma:** 2027-03-31
- **Takvim kaydı:** `docs/reminders/frontend-typescript-review-2026-09-30.ics`

Başlangıçta `web_ui_react/src` altında 16 `.js`, 42 `.jsx`, 1 `.ts` ve 0 `.tsx`
dosyası vardı. İlk dilimde `src/hooks/useFormState.ts` de TypeScript'e taşındı;
İlk state/logic dilimlerinden sonra `useSwarmFlowController.ts` de paylaşılan swarm
graph tiplerini kullanacak şekilde taşınmış; ratchet envanteri 14 `.js`, 42 `.jsx`,
4 `.ts` ve 0 `.tsx` seviyesine sıkılaştırılmıştır. İlk React dilimi olarak
`src/lib/routerShim.tsx`, router context ve bileşen prop sözleşmeleri açık tiplerle
taşınmış; güncel ratchet 14 `.js`, 41 `.jsx`, 4 `.ts` ve 1 `.tsx` olmuştur.
Kök route, lazy panel ve admin erişim sözleşmelerini taşıyan `src/App.tsx` dilimiyle
envanter 14 `.js`, 40 `.jsx`, 4 `.ts` ve 2 `.tsx` seviyesine ilerletilmiş; ratchet
54 untyped / 6 typed olarak yeniden sıkılaştırılmıştır. WebSocket protokolünün
`room_state`, `presence`, `assistant_*` ve legacy mesaj ayrıştırmasını kapsayan
`src/hooks/useWebSocket.ts` geçişiyle güncel envanter 13 `.js`, 40 `.jsx`, 5 `.ts`
ve 2 `.tsx`; ratchet ise 53 untyped / 7 typed seviyesine gelmiştir. REST istemci
çekirdeğinin `src/lib/api.ts` geçişi; generic `fetchJson<T>`, token principal,
HITL, coverage ve operasyon endpoint sözleşmelerini TypeScript kapısına almış;
güncel envanteri 12 `.js`, 40 `.jsx`, 6 `.ts`, 2 `.tsx` ve ratchet'i
52 untyped / 8 typed seviyesine ilerletmiştir. Chat ve stream state machine'i
`src/hooks/useChatStore.ts` olarak WebSocket mesaj sözleşmelerine bağlanmış;
güncel envanter 11 `.js`, 40 `.jsx`, 7 `.ts`, 2 `.tsx` ve ratchet
51 untyped / 9 typed seviyesine gelmiştir. CRUD/API yoğun ilk panel dalgasında
`TenantAdminPanel.tsx` ve `OperationsQaPanel.tsx`; RBAC/audit kayıtları, HITL,
coverage, Poyraz form state'i ve hata sınırlarını açık tiplerle taşımış; güncel
envanteri 11 `.js`, 38 `.jsx`, 7 `.ts`, 4 `.tsx` ve ratchet'i
49 untyped / 11 typed seviyesine ilerletmiştir. Typed swarm controller'ın graph
verisi, positioned edge'leri, node aksiyonları ve klavye/fare olaylarını tüketen
son halka `components/panels/swarm/GraphView.tsx` olarak taşınmış; güncel envanter
11 `.js`, 37 `.jsx`, 7 `.ts`, 5 `.tsx` ve ratchet 48 untyped / 12 typed'dır.
En büyük hook olan `hooks/useVoiceAssistant.ts`; duplex voice state machine,
MediaRecorder/Web Audio kaynakları, istemci komutları ve sunucu mesaj alanlarını
tipleyip gelen JSON'u runtime alan doğrulamasından geçirmiş; güncel envanter
10 `.js`, 37 `.jsx`, 8 `.ts`, 5 `.tsx` ve ratchet 47 untyped / 13 typed'dır.
İlk leaf component diliminde `components/ChatInput.tsx` gönderim callback'i, textarea
ref'i ve klavye olayını; `components/PanelErrorBoundary.tsx` ise children, hata state'i
ve React error-boundary lifecycle sözleşmesini açık tiplerle taşımıştır. Envanter
10 `.js`, 35 `.jsx`, 8 `.ts`, 7 `.tsx` ve ratchet 45 untyped / 15 typed seviyesine
gelerek 2026-09-30 ara hedefini zamanından önce karşılamıştır.
İkinci leaf component diliminde `ChatMessage.tsx`, `ChatWindow.tsx`, `StatusBar.tsx`,
`VoiceAssistantPanel.tsx` ve `P2PDialoguePanel.tsx` taşınmıştır. Mesaj modeli,
timestamp normalizasyonu, DOM ref'i, WebSocket durum prop'ları ve voice view-model
sözleşmeleri artık TypeScript tarafından doğrulanır. Envanter 10 `.js`, 30 `.jsx`,
8 `.ts`, 12 `.tsx`; ratchet ise 40 untyped / 20 typed seviyesine sıkılaştırılmıştır.
Saf swarm graph oluşturma katmanı
`src/lib/swarmFlowGraph.ts` olarak taşınmış ve controller ile paylaşılan dış API tipleri
tanımlanmıştır.
İlk kritik admin paneli diliminde `components/PromptAdminPanel.tsx`; prompt listeleme,
form alanları, aktivasyon cevabı ve bilinmeyen API hata değerlerini açık tiplerle
daraltmıştır. Güncel envanter 10 `.js`, 29 `.jsx`, 8 `.ts`, 13 `.tsx`; ratchet ise
39 untyped / 21 typed seviyesindedir.
`components/SwarmFlowPanel.tsx` geçişi typed controller ve graph katmanlarının React
orkestrasyon sınırını da TypeScript kapısına almış; execution mode artık
`"parallel" | "pipeline"` union'ı olarak korunmaktadır. Güncel envanter 10 `.js`,
28 `.jsx`, 8 `.ts`, 14 `.tsx`; ratchet 38 untyped / 22 typed seviyesindedir.
`components/AgentManagerPanel.tsx` geçişi multipart plugin kayıt formunu ve backend
cevap doğrulamasını typed sınıra almıştır. Başarılı görünen malformed JSON artık
runtime alan kontrolünden geçmeden UI state'ine yazılmaz. Güncel envanter 10 `.js`,
27 `.jsx`, 8 `.ts`, 15 `.tsx`; ratchet 37 untyped / 23 typed seviyesindedir.
`components/PluginMarketplacePanel.tsx` geçişi katalog ve install/reload/remove aksiyon
kontratlarını typed sınıra almıştır. Katalog JSON'u `unknown` olarak karşılanıp malformed
öğeler UI state'ine girmeden elenir. Güncel envanter 10 `.js`, 26 `.jsx`, 8 `.ts`,
16 `.tsx`; ratchet 36 untyped / 24 typed seviyesindedir.
`checkJs: false` olduğu için `npm run typecheck`, JavaScript/JSX
bileşen ağacına tam tip güvencesi sağlamaz. Yaklaşık 2974 mevcut hatayı tek seferde
kalite kapısına taşımak yerine geçiş aşağıdaki ratchet ve küçük domain dilimleriyle
yürütülür.

## Zorunlu ratchet

`typescript-migration-baseline.json`, en fazla 36 untyped (`.js` + `.jsx`) ve en az
24 typed (`.ts` + `.tsx`) kaynak dosyasına izin verir. `npm run typecheck:inventory`:

- `.js`/`.jsx` toplamındaki net artışı fail-closed reddeder;
- mevcut `.ts`/`.tsx` dosyalarının silinmesi veya untyped biçime döndürülmesini reddeder;
- `.jsx` → `.tsx` dönüşümlerinde doğal olarak geçer.

Ölçülen ilerleme baseline değerlerini yalnız daha sıkı yönde değiştirebilir:
`maximum_untyped_files` düşürülür ve `minimum_typed_files` artırılır. Sayıları gevşeten
değişiklikler kampanya sahibinin açık onayını gerektirir.

## Aşamalar ve kapılar

Tarihlerin yalnız dokümantasyon niyeti olarak kalmaması için baseline içindeki milestone
değerleri `npm run typecheck:inventory` tarafından tarih geldiğinde fail-closed uygulanır:

| Son tarih | En fazla untyped | En az typed | Teslim odağı |
|---|---:|---:|---|
| 2026-09-30 | 45 | 15 | Düşük bağımlılıklı hook/helper ve ortak API tipleri |
| 2026-12-15 | 30 | 30 | `src/lib`, veri/state ve controller katmanı |
| 2027-02-15 | 12 | 48 | Leaf React bileşenleri ve prop/event/ref tipleri |
| 2027-03-31 | 0 | 60 | Tam `.ts/.tsx` kaynak ağacı ve compatibility kapısının kaldırılması |

Milestone zamanı geldiğinde baseline'daki genel ratchet daha gevşek kalsa bile tarihli hedef
önceliklidir. Gecikme, baseline veya tarihi ileri taşıyarak gizlenemez; sahip onayı, gerekçe ve
yeni expiry tarihi içeren ayrı bir istisna kaydı gerekir.

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
