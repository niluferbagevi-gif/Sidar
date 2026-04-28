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

## Neden `blocked` durumuna düşer? (ci_remediation.py ile hizalı kontrol listesi)

Otonom döngünün `blocked` üretmesinin en sık kök nedenleri:

1. **LLM yanıtı parse edilemez/JSON dışı gelir**
   - `normalize_self_heal_plan(...)` ham çıktıyı JSON’a çevirmeyi dener.
   - Geçerli JSON elde edilemezse payload boş kabul edilir ve operasyon listesi düşer.

2. **Aksiyon türü güvenlik filtresine takılır**
   - Sadece `action="patch"` kabul edilir.
   - `rewrite`, `replace_file`, `create` vb. aksiyonlar tamamen elenir.

3. **Dosya yolu kapsam dışı kalır (`scope_paths`)**
   - Path, önceden belirlenen `scope_paths` içinde değilse operasyon reddedilir.
   - Bu, model doğru patch önerse bile “yanlış dosya” durumunda planı boşaltabilir.

4. **Path güvenlik kuralları ihlal edilir**
   - `/` ile başlayan mutlak yol veya `..` içeren traversal denemesi reddedilir.
   - Böylece sandbox dışına taşabilecek patch’ler otomatik düşer.

5. **`target` boş veya dosyada birebir bulunamayacak kadar zayıf yazılır**
   - Normalizasyon tarafında boş `target` doğrudan elenir.
   - Uygulama aşamasında birebir eşleşmeyen `target` da patch’in fiilen uygulanamamasına yol açar.

6. **Validation komutları allowlist dışında kalır**
   - `pytest`, `python -m pytest`, `bash run_tests.sh`, `uv pip install ...` dışındaki komutlar ayıklanır.
   - Komut kalmazsa `validate` adımı `blocked` olabilir.

7. **Şüpheli dosya çıkarımı başarısız olur**
   - `build_remediation_loop(...)` içinde `suspected_targets` boşsa `patch` adımı `blocked` atanır.
   - Yani sorun bazen LLM değil, upstream loglardan dosya hedefinin çıkarılamamasıdır.

### Operasyonel öneri

- Prompt içinde **yalnız JSON şema**, **yalnız patch aksiyonu** ve **scope_paths’e birebir uyum**
  zorunluluğunu kısa/katı kurallarla tekrar edin.
- Büyük kapsamlı hata yığınını modül bazlı batch’lere bölün (`autonomous_batches` yaklaşımı).
- Önce parse/normalize başarı metriğini (kaç operasyon survive etti) izleyin;
  sonra patch doğruluğuna odaklanın.

## Hata yoğunluğu ve model kapasitesi etkisi (38 dosya / 275 mypy hatası örneği)

Yüksek hacimli tip hatalarında `blocked` oranı yalnızca JSON şema ihlallerinden değil,
**bilişsel yük + bağlam kısıtı** kombinasyonundan da yükselir:

1. **Bağlam darboğazı (prompt tarafı)**
   - `build_self_heal_patch_prompt(...)` en fazla **6 dosya snapshot’ı** taşır.
   - 38 dosyaya yayılan 275 hata için bu pencere, global kök nedeni ve dosyalar arası
     tip zincirini yakalamada yetersiz kalabilir.
   - Sonuç: model, kapsam dışına kayan veya yarım kalan operasyonlar üretebilir.

2. **Model kapasitesi sınırı (LLM tarafı)**
   - `qwen2.5-coder:3b` gibi küçük ölçekli modelde, `Missing type parameters`,
     `Incompatible types`, `no-any-return` gibi ilişkili mypy hatalarını
     tek denemede tutarlı patch planına dökmek zorlaşır.
   - Bu durum özellikle çok dosyalı tip propagasyonu gerektiren refactor’larda belirginleşir.

3. **Tek-shot plan anti-pattern’i**
   - Çok sayıda dosyayı tek patch planına sıkıştırmak; hem normalize filtrelerine takılma
     olasılığını hem de uygulanamayan `target/replacement` oranını artırır.

### Yoğun hata setleri için önerilen yürütme ayarı

- **Batch-first**: 38 dosyayı modül/dizin bazında küçük gruplara bölün (örn. 3-5 dosya).
- **Retry-local**: Her batch için `max_retries=3`; başarısız batch’i insan onay kuyruğuna aktarın.
- **Signal compression**: Prompt’a tüm logu değil, batch ile ilgili ilk 20-40 kritik mypy satırını verin.
- **Success metric**: “normalize sonrası kalan operasyon sayısı / üretilen operasyon sayısı”
  ve “uygulanabilen patch oranı” metriklerini batch bazında izleyin.
