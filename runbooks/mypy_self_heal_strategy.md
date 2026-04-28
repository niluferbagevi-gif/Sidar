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

## Kodda uygulanan güçlendirmeler (scripts/auto_heal.py)

Nisan 2026 güncellemesiyle CLI katmanında aşağıdaki iyileştirmeler eklendi:

1. **Batch retry desteği (`--batch-retries`)**
   - Her batch, ilk denemeye ek olarak konfigüre edilebilir sayıda tekrar denenir.
   - Amaç: geçici LLM planlama/formatlama sapmalarında ilk hatada akışı sonlandırmamak.

2. **Scope-odaklı log sıkıştırma (`--scope-log-lines`)**
   - Prompt’a tüm log yerine, sadece ilgili dosya yollarını içeren ve tip hatası sinyali taşıyan satırlar verilir.
   - Amaç: bağlam gürültüsünü düşürmek, parse edilebilir JSON plan üretim olasılığını artırmak.

3. **Attempt-aware diagnosis üretimi**
   - Her retry’da teşhis metnine "yalnız patch action, scope dışına çıkma, birebir target" kuralları tekrar enjekte edilir.
   - Amaç: normalize filtrelerine takılan serbest/metinsel çıktıyı azaltmak.

4. **Batch seviyesinde deneme telemetrisi**
   - Sonuç JSON’una `attempts[]` listesi eklenir (`attempt`, `status`, `summary`).
   - Amaç: `blocked` kök nedenini gözlenebilir kılmak (ilk deneme vs retry davranışı).

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

## Yüksek risk bayrağı ve onay sonrası başarısızlık ayrımı

`build_remediation_loop(...)` aşağıdaki durumlarda süreci high-risk kabul eder ve
`needs_human_approval=true` üretir:

- Hata metninde `syntaxerror`, `importerror`, `typeerror` vb. anahtar kelimeler varsa.
- `suspected_targets` sayısı eşik değeri (varsayılan: `SELF_HEAL_HITL_SCOPE_THRESHOLD=3`) üstündeyse.

Bu yüzden operatör onayı (`e`/evet) alınması, patch’in otomatik uygulanacağı anlamına gelmez.
Onay yalnızca akışın bir sonraki aşamaya geçmesine izin verir.

### Kritik ayrım: normalize red mi, uygulama red mi?

- **Normalize aşaması** (`normalize_self_heal_plan`):
  - JSON parse, aksiyon türü, path güvenliği, scope uyumu, boş `target` gibi yapısal filtreler çalışır.
  - Burada `target` için “dosyada birebir bulundu mu?” kontrolü yapılmaz; yalnızca boş olmaması aranır.

- **Patch uygulama aşaması**:
  - `target` metninin dosya içeriği ile birebir eşleşmesi pratikte bu aşamada kritik hale gelir.
  - Model yanlış/eksik `target` üretirse normalize geçmiş olsa bile patch uygulanamaz ve döngü tekrar tıkanır.

### Onay karmaşasını azaltmak için öneri

- HITL ekranında onaydan önce iki ayrı gösterge sunun:
  1. **Normalize geçiş oranı** (kaç operasyon filtrelerden geçti),
  2. **Dry-run apply oranı** (kaç operasyon dosyada birebir eşleşip uygulanabildi).
- `target` stabilitesini artırmak için modele daha kısa ve atomik patch talimatı verin
  (tek fonksiyon/tek blok değişikliği).
- Onay sonrası ilk adımda “dry-run patch” zorunlu kılın; başarısızsa doğrudan batch’i küçültün.

## Teşhis (diagnosis) yetersizliği ve planlamanın takılması

Pratikte bazı olaylarda `root_cause_hint` aşırı genel kalabilir (örn.
`one or more arguments [no-untyped-def]`). Bu, operatöre yön gösterse de
patch üretimi için yeterli deterministik bağlam sağlamaz.

`build_remediation_loop(...)` akışında:

- `diagnosis_text` ve `suspected_targets` birlikte zayıfsa döngü **`needs_diagnosis`**
  statüsünde kalabilir.
- `suspected_targets` boşsa `patch` adımı `blocked` olur; planlama bir sonraki adıma
  sağlıklı geçemez.
- Yetersiz teşhis metni, LLM’in kapsamı yanlış genişletmesine ve düşük kaliteli
  JSON plan üretmesine yol açabilir.

### Yetersiz teşhisi güçlendirme önerileri

1. **Hint’i spesifikleştirin**
   `no-untyped-def` gibi genel kodu tek başına bırakmayın; mümkünse
   `dosya:satır:kural` formatında ilk 10-20 kritik hatayı çıkarın.

2. **Hedef çıkarımını zorlayın**
   Log ayrıştırma adımında `suspected_targets` üretimi başarısızsa,
   planlama öncesi ek bir “target extraction” alt-adımı çalıştırın.

3. **Diagnosis gate ekleyin**
   Plan üretmeden önce minimum kalite eşiği tanımlayın:
   - en az 1 somut dosya yolu,
   - en az 1 uygulanabilir validation komutu,
   - en az 1 açık kök neden cümlesi.

4. **İki aşamalı prompting kullanın**
   Aşama-1: sadece teşhis/target çıkarımı,
   Aşama-2: sadece patch planı (JSON şeması).

5. **Fallback stratejisi**
   `needs_diagnosis` durumunda otomatik patch denemek yerine
   küçük batch ile “diagnosis refresh” çalıştırıp sonra planlamaya dönün.

## Ölçek baskısı: 275 hata / 38 dosya senaryosunda pratik karar ağacı

Bu ölçekte bir mypy çıktısında modelin aynı turda hem teşhis hem patch planı üretmesi
zorlaşır. Tipik sonuç:

- Model geçerli JSON şemasını üretemez (plan normalize aşamasında boşalır), veya
- Üretilen patch’lerin `target` metni dosya içeriğiyle birebir örtüşmez
  (uygulama/dry-run aşamasında başarısızlık artar).

### Önerilen müdahale sırası

1. **Kapsamı daraltın (öncelik)**
   - Tek seferde 38 dosya yerine dizin bazlı ilerleyin (örn. önce sadece `core/`).
   - Her batch için küçük ve homojen hata sınıfı seçin
     (örn. sadece `no-untyped-def` + aynı modül).

2. **Model kapasitesini yükseltin (gerekirse)**
   - Aynı prompt/akış korunarak daha yüksek kapasiteli model deneyin
     (örn. `qwen2.5-coder:7b` veya `qwen2.5-coder:14b`).
   - Özellikle çok dosyalı tip propagasyonu ve karmaşık generic hatalarında başarı artar.

3. **Başarı kriterini batch bazında ölçün**
   - JSON parse/normalize başarı oranı,
   - dry-run apply oranı,
   - batch başına kapanan mypy hata sayısı.

4. **Erken durdurma kuralı**
   - İki batch üst üste düşük apply oranı görülürse akışı durdurup
     ya batch’i küçültün ya da model kapasitesini artırın.
