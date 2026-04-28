# Mypy/Sıkı Tip Hatalarında Otonom Self-Heal Stratejisi

Bu doküman, yüksek hacimli statik tip hatalarında (`mypy` vb.) self-heal döngüsünün
sağlıklı işletimi için önerilen çalışma şeklini özetler.

## Kısa cevap

`"Dosya dosya dolaş, onar, test et, onaylanana kadar maksimum 3 kez tekrarla"` yaklaşımı
ana omurga olarak daha sağlıklıdır.

`"%90 coverage'a ulaşana kadar sınırsız tekrar"` yaklaşımı tek başına doğru değildir.
Coverage oranı bir **kalite kapısı** olmalıdır; birincil döngü kontrolü olmamalıdır.

## Neden?

- Büyük hata yığınlarında tek-shot plan üretimi bağlamı taşır ve `blocked` üretir.
- Dosya/modül bazlı chunking, model bağlamını daraltır ve patch doğruluğunu yükseltir.
- Maksimum 3 retry:
  - ikincil kırılımları toparlamak için yeterlidir,
  - halüsinasyon döngüsü riskini sınırlı tutar.
- Coverage hedefi (örn. %90), tip düzeltmelerinin test kalitesini bozmasını engelleyen
  bir doğrulama eşiğidir; fakat tek başına sonsuz retry sebebi olmamalıdır.

## Önerilen hibrit politika

1. **Planlama birimi:** Dosya/modül bazlı.
2. **Retry limiti:** Her birim için `max_retries=3`.
3. **Doğrulama sırası:** `mypy -> ilgili test subseti -> coverage kontrolü`.
4. **Geçiş koşulu:** Birim başarılıysa sonraki dosyaya geç.
5. **Durma koşulu:** 3 deneme sonunda hala başarısızsa:
   - `needs_human_intervention=true`
   - dosya insan kuyruğuna alınır.
6. **Coverage politikası:** %90 altıysa “quality gate fail” ver; ama aynı dosyada
   sınırsız döngüye girme, yine 3 deneme kuralına uy.

## Pratik not

Coverage düşüşü çoğu zaman eksik testten gelir; tip hatası fixlerini bozmak yerine
QA/Coverage ajanı ile hedefli test üretimi daha güvenli sonuç verir.
