# Coverage Agent ile Eksik Testleri Otomatik Üretme Rehberi

Bu rehber, projedeki `coverage_agent` kullanılarak coverage açığına göre **mevcut ana test dosyasını güncelleme / doldurma** akışını adım adım anlatır.

## 1) Ön koşullar

- Proje kökünde ol:
  - `cd ~/Sidar`
- Testlerden sonra `coverage.xml` üretilmiş olmalı.
- Backend tarafında coverage hedefi `.coveragerc` içindeki güncel `fail_under` değeri veya açıkça verilen `COVERAGE_FAIL_UNDER` ile aktiftir.

> Not: Gönderdiğin çıktıda backend toplam coverage `%40.11`, frontend `%91.55` görünüyor. Sorun backend tarafındaki coverage açığıdır.

## 2) Coverage Agent'i nasıl tetiklersin?

Supervisor yönlendirmesi şu anahtar kelimeleri görünce görevi coverage ajanına yollar:
- `coverage`, `kapsama`, `pytest`, `eksik test`, `test yaz`, `test üret`, `qa`

Bu yüzden doğrudan aşağıdaki gibi komutlar verebilirsin:

```bash
uv run python cli.py -c 'coverage açığını analiz et ve eksik test üret'
```

veya interaktif modda:

```bash
uv run python cli.py
# sonra prompt:
coverage.xml üzerinden eksik testleri üret
```

## 3) En güvenilir (deterministik) akış: tool-prefix komutları

`CoverageAgent.run_task()` özel prefix komutlarını doğrudan destekler. En iyi pratik bu 3 aşamalı akıştır:

### Aşama A — Coverage raporunu analiz et

```bash
uv run python cli.py -c 'analyze_coverage_report|{"coverage_xml":"coverage.xml","coveragerc":".coveragerc","limit":10}'
```

Bu komut sana şunları döndürür:
- `findings[]` (hedef dosyalar)
- her bulgu için `target_path`
- önerilen test yolu (`suggested_test_path`)

### Aşama B — Seçtiğin dosya için test kodu üret

Örnek: `core/llm_client.py` için test ürettirme

```bash
uv run python cli.py -c 'generate_missing_tests|{"coverage_finding":{"target_path":"core/llm_client.py","missing_lines":[235,236],"missing_branches":["240:50% (1/2)"]},"coveragerc":{"run":{"include":"core/*"},"report":{"omit":"tests/*"}}}'
```

> Kritik kural (fixture uyumu): `generate_missing_tests` promptuna mutlaka ortak fixture kullanım direktifi ekleyin.  
> Aksi halde Coverage Agent kendi ad-hoc mock sınıflarını üretmeye çalışabilir ve proje test standardından sapar.

Önerilen direktif (hazır kopyala/yapıştır):

```text
Eksik testleri üretirken unittest.mock yerine conftest.py içinde bulunan fake_llm_response, fake_event_stream, agent_factory, fake_social_api ve fake_db_session fixture'larını kullan. Kendi mock objeni oluşturma.
```

Pratik örnek:

```bash
uv run python cli.py -c 'generate_missing_tests|{"coverage_finding":{"target_path":"core/llm_client.py","missing_lines":[235,236],"missing_branches":["240:50% (1/2)"]},"extra_instructions":"Eksik testleri üretirken unittest.mock yerine conftest.py içinde bulunan fake_llm_response, fake_event_stream, agent_factory, fake_social_api ve fake_db_session fixture'larını kullan. Kendi mock objeni oluşturma.","coveragerc":{"run":{"include":"core/*"},"report":{"omit":"tests/*"}}}'
```

### Aşama C — Üretilen testi hedef dosyaya yaz
Geçici veya ad-hoc (örn: `_coverage_x.py`) dosyalar oluşturmak proje kurallarına aykırıdır. Üretilen testi her zaman mevcut ana test dosyasına **append (ekleme)** yaparak yazdırın.

Örnek:
```bash
uv run python cli.py -c 'write_missing_tests|{"suggested_test_path":"tests/unit/core/test_llm_client.py","generated_test":"def test_x():\n    assert True","append":true}'
```

---

## 4) Tek komutta (otomatik) akış

Aşağıdaki gibi tek prompt da verebilirsin; agent pytest çalıştırır, bulgu çıkarır, test üretir ve önerilen dosyaya yazar:

```bash
uv run python cli.py -c '{"command":"./run_tests.sh","cwd":"."}'
```

Bu mod hızlıdır ama kontrol seviyesi düşüktür. Kontrollü ve kural uyumlu ilerlemek için 3 aşamalı prefix akışı daha doğrudur.


## 4.1) Coverage hedefleri operasyonel olarak ayrıdır

Coverage yüzdeleri tek bir kapı gibi okunmamalıdır. Sidar'da dört ayrı operasyonel
profil vardır:

| Operasyon | Varsayılan eşik/hedef | Komut | Anlamı |
| --- | --- | --- | --- |
| Günlük local kalite kapısı | `.coveragerc` / `COVERAGE_FAIL_UNDER_LOCAL` / `COVERAGE_FAIL_UNDER` (güncel repo gate: `%90`, ratchet cap `%99`) | `./run_tests.sh` | Geliştiricinin günlük smoke + unit kalite kapısıdır; stabil ve ulaşılabilir tabandır, başarısızsa değişiklik merge/PR öncesi düzeltilir. |
| CI zorunlu gate | CI ortamında `TEST_PROFILE=ci` + `COVERAGE_FAIL_UNDER_CI` (varsayılan `.github/workflows/ci.yml` içinde `%95`) | `CI=true TEST_PROFILE=ci ./run_tests.sh` | Lokal tabanın üzerine merge engelleyici sıkı eşik bindirir; otonom `%99.8` hedefiyle karıştırılmaz. |
| Otonom coverage iyileştirme hedefi | `AUTONOMOUS_LOOP_COVERAGE_PROFILE=short` ile `%99.8` | `./autonomous_loop.sh` | Testler geçse bile kalan coverage açığını kapatmak için self-heal/CoverageAgent döngüsünü tetikleyen ayrı hedeftir. |
| Coverage kampanyası | Planlı/manual hedef (`full`, `file` veya override) | `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign ... ./autonomous_loop.sh` | Sprint/borç kapatma çalışmasıdır; günlük local gate değildir. |

`./autonomous_loop.sh`, CI kalite kapısını değiştirmez; `run_tests.sh` ve `.coveragerc`
üzerindeki eşikler aynen korunur. Loglarda artık `local gate` ve `otonom hedef` ayrı
yazılır: testler güncel local gate eşiğini geçtiği halde `%99.8` hedefi altında kalmak **local/CI
başarısızlığı değil**, yalnızca otonom iyileştirme döngüsünün devam edeceği anlamına gelir.

> Operasyon notu: `%100.00` ölçüm görüldüğünde bile günlük local/CI ratchet cap `%99`
> bilinçli olarak korunur. `Coverage gate ratcheted: %90 -> %99 (measured=%100.00)`
> çıktısı, refactor dönemi için doğru güvenlik tamponudur; `%100` gate yalnız
> `COVERAGE_CAMPAIGN=1`, `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign` veya
> bilinçli `COVERAGE_STRICT_LOCAL_RATCHET=1` opt-in'i ile denenmelidir.

Otonom döngünün kendi iyileştirme hedefi maliyet/iterasyon kontrolü için profillenebilir:

| Profil | Komut | Hedef | Kullanım amacı |
| --- | --- | --- | --- |
| Kısa kampanya | `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign AUTONOMOUS_LOOP_COVERAGE_PROFILE=short ./autonomous_loop.sh` | `%99.8` | Planlı coverage kampanyasında varsayılan otonom iyileştirme hedefidir; günlük local gate ile aynı şey değildir. |
| Tam kampanya | `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign AUTONOMOUS_LOOP_COVERAGE_PROFILE=full ./autonomous_loop.sh` | `%100` | Bilinçli olarak tam coverage hedeflenen uzun/planlı coverage kampanyalarında kullanılır. |
| Dosya | `AUTONOMOUS_LOOP_COVERAGE_PROFILE=file AUTONOMOUS_LOOP_COVERAGE_TARGET_FILE=agent/roles/coverage_agent.py AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign ./autonomous_loop.sh` | hedef dosyada `%100` | Belirli bir dosyayı kapatmaya odaklanır; toplam coverage yerine `coverage.json` içindeki dosya özetini okur. |

Bu eşleşmeyi gerçek döngüyü başlatmadan doğrulamak için aynı komutlara
`AUTONOMOUS_LOOP_PRINT_CONFIG=1` eklenebilir; betik çözümlenen operasyon profilini ve
hedef yüzdeyi loglayıp test/iyileştirme adımlarına geçmeden çıkar.

Geriye dönük uyumluluk için `AUTONOMOUS_LOOP_COVERAGE_TARGET` verilirse profil hedefini
ezer. Örneğin `AUTONOMOUS_LOOP_COVERAGE_TARGET=99.5 ./autonomous_loop.sh` doğrudan
`%99.5` otonom hedefiyle çalışır. `AUTONOMOUS_LOOP_OPERATION_PROFILE` ise hedefi
değiştirmez; loglarda çalışmanın `daily-local`, `autonomous-improvement`, `ci-required`
veya `coverage-campaign` bağlamında etiketlenmesini sağlar.

### 4.2) Coverage ratchet step neyi kontrol eder?

`COVERAGE_RATCHET_STEP`, otonom coverage hedefi değildir; `run_tests.sh` sonunda
`.coveragerc` içindeki günlük kalite kapısının kaç yüzde puanlık basamaklarla yukarı
taşınacağını belirler. `.coveragerc` aynı zamanda ratchet state dosyasıdır; repo'da
commitli olmalı ve eksik/sıfırlanmış gate durumunda `run_tests.sh` fail-closed davranmalıdır.
Hesaplama `scripts/coverage_ratchet.py` içindeki
`compute_next_gate(...)` fonksiyonunda ölçülen coverage'ı aşağıdaki formülle ulaşılan
basamağa yuvarlar ve mevcut gate'i asla düşürmez:

```python
reached_step = math.floor(measured_coverage / step) * step
```

Örnek: ölçülen coverage `%99.04`, mevcut gate `%95` ise sonuçlar şöyledir:

| `COVERAGE_RATCHET_STEP` | Yeni gate | Kullanım önerisi |
| ---: | ---: | --- |
| `5` | `%95` | Güvenli ama bu proje için kaba; `%99.04` ölçümü gate'e yansımaz. |
| `1` | `%99` | Varsayılan/günlük kullanım için önerilen denge. |
| `0.5` | `%99` | Kampanya dışı kullanımda `1` ile benzer, daha sık ratchet eder. |
| `0.1` | `%99` | Kontrollü coverage kampanyalarında geçici kullanılabilir. |
| `0.01` | `%99.04` | Önerilmez; küçük ortam/test dalgalanmalarında gate'i kırılganlaştırır. |

Bu nedenle günlük local/CI kalite kapısı için önerilen kullanım:

```bash
COVERAGE_RATCHET_STEP=1 ./run_tests.sh
```

Coverage kampanyası veya otonom ajan iyileştirme koşusunda hedefi step ile değil,
`AUTONOMOUS_LOOP_COVERAGE_TARGET` veya `AUTONOMOUS_LOOP_COVERAGE_PROFILE` ile yönetin.
`short` profil `%99.8`, `full` profil `%100` hedefler.

### 4.3) Otonom test yazım ajanı için mikro kapsam sınırı

Arkadaşınızın `%5` uyarısı, bu repodaki **ratchet step** varsayılanı için artık
uygulanmış durumda: `run_tests.sh` ve `scripts/coverage_ratchet.py` günlük gate'i
varsayılan `%1` puanlık basamaklarla yükseltiyor. Ancak otonom test yazımında ikinci
bir risk daha var: CoverageAgent'a tek denemede çok fazla eksik satır/finding vermek.

Bu nedenle otonom döngü artık mikro kapsamla çalışır:

| Ayar | Varsayılan | Neyi sınırlar? |
| --- | ---: | --- |
| `AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT` | `3` | Tek CoverageAgent çağrısında ele alınacak dosya/finding sayısı. |
| `AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE` | `1` | Aynı anda işlenecek finding sayısı; context yükünü düşük tutar. |
| `AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_LINES` | `25` | Tek test adayına verilecek eksik satır sayısı. |
| `AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_BRANCHES` | `10` | Tek test adayına verilecek eksik branch sayısı. |
| `AUTONOMOUS_LOOP_EXCLUDE_FILES` | `web_server.py,main.py,gui_launcher.py,cli.py` | Yan etkili/launcher dosyalarını otonom üretim kuyruğundan çıkarır; dosya adı, repo-göreli yol, dizin prefix'i ve glob deseni desteklenir. |

Bu ayrım önemlidir:

- `COVERAGE_RATCHET_STEP=1`, günlük kalite kapısını ölçüme yaklaştırmak için dengeli
  varsayılandır.
- `%5` tek otonom test üretim denemesi için geniş/agresif kabul edilir; 21.5k+ LOC
  yüzeyinde yaklaşık bin satırlık davranış alanını aynı bağlama yükleyebilir.
- `%0.5-%1` normal otonom ilerleme için sağlıklı aralıktır.
- `%99+` gibi kritik eşiklerde, kontrollü coverage kampanyasında `COVERAGE_RATCHET_STEP=0.1`
  ve yukarıdaki mikro kapsam limitleri birlikte kullanılabilir.
- Nihai hedef yine ratchet step ile değil `AUTONOMOUS_LOOP_COVERAGE_PROFILE` veya
  `AUTONOMOUS_LOOP_COVERAGE_TARGET` ile yönetilmelidir.

Örnek kontrollü kritik eşik koşusu:

```bash
COVERAGE_RATCHET_STEP=0.1 \
AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign \
AUTONOMOUS_LOOP_COVERAGE_PROFILE=short \
AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT=3 \
AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_LINES=25 \
./autonomous_loop.sh
```

## 5) Pratik öneri (senin mevcut çıktına göre)

Senin loguna göre hızlı kazanım için düşük coverage ve nispeten izole modüllerden başla:
- `agent/__init__.py`
- `agent/core/event_stream.py`
- `agent/roles/coder_agent.py`
- `core/router.py`

Büyük dosyalar (`web_server.py`, `core/rag.py`, `core/db.py`) tek seferde yükseltmesi pahalı olduğu için ilk dalgada küçük/orta dosyalardan coverage toplamak daha verimli olur.

## 6) Doğrulama

Her üretimden sonra:

```bash
uv run pytest -q tests/unit/core/test_llm_client.py
./run_tests.sh
```

Eğer testler geçiyor ama coverage artmıyorsa:
- yanlış modül/path hedeflenmiş olabilir,
- branch yolları tetiklenmemiş olabilir,
- `omit/include` ayarları `.coveragerc` içinde filtreliyor olabilir.

## 7) Sık yapılan hata

Coverage agent’in kendi coverage’inin `%81` olması, projenin toplam coverage değerinin güncel local gate ile aynı olduğu anlamına gelmez. Toplam değer tüm backend dosyalarının ağırlıklı toplamıdır.

---

## Kısa cevap (TL;DR)

Coverage agent ile en doğru yaklaşım mevcut ana test dosyasına append ederek ilerlemektir. En iyi yöntem:
1. `analyze_coverage_report|...`
2. `generate_missing_tests|...`
3. `write_missing_tests|{"suggested_test_path":"tests/unit/.../test_<module>.py",...}`

İstersen bir sonraki adımda senin coverage çıktına göre **ilk 3 hedef dosya + hazır komutları** birebir üretebilirim.
