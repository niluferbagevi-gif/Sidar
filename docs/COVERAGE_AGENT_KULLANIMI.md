# Coverage Agent ile Eksik Testleri Otomatik Üretme Rehberi

Bu rehber, projedeki `coverage_agent` kullanılarak coverage açığına göre **yeni bir test dosyası (`x`) oluşturma / doldurma** akışını adım adım anlatır.

## 1) Ön koşullar

- Proje kökünde ol:
  - `cd ~/Sidar`
- Testlerden sonra `coverage.xml` üretilmiş olmalı.
- Backend tarafında coverage hedefi (`--cov-fail-under=90`) aktif.

> Not: Gönderdiğin çıktıda backend toplam coverage `%40.11`, frontend `%91.55` görünüyor. Sorun backend tarafındaki coverage açığıdır.

## 2) Coverage Agent'i nasıl tetiklersin?

Supervisor yönlendirmesi şu anahtar kelimeleri görünce görevi coverage ajanına yollar:
- `coverage`, `kapsama`, `pytest`, `eksik test`, `test yaz`, `test üret`, `qa`

Bu yüzden doğrudan aşağıdaki gibi komutlar verebilirsin:

```bash
python cli.py -c 'coverage açığını analiz et ve eksik test üret'
```

veya interaktif modda:

```bash
python cli.py
# sonra prompt:
coverage.xml üzerinden eksik testleri üret
```

## 3) En güvenilir (deterministik) akış: tool-prefix komutları

`CoverageAgent.run_task()` özel prefix komutlarını doğrudan destekler. En iyi pratik bu 3 aşamalı akıştır:

### Aşama A — Coverage raporunu analiz et

```bash
python cli.py -c 'analyze_coverage_report|{"coverage_xml":"coverage.xml","coveragerc":".coveragerc","limit":10}'
```

Bu komut sana şunları döndürür:
- `findings[]` (hedef dosyalar)
- her bulgu için `target_path`
- önerilen test yolu (`suggested_test_path`)

### Aşama B — Seçtiğin dosya için test kodu üret

Örnek: `core/llm_client.py` için test ürettirme

```bash
python cli.py -c 'generate_missing_tests|{"coverage_finding":{"target_path":"core/llm_client.py","missing_lines":[235,236],"missing_branches":["240:50% (1/2)"]},"coveragerc":{"run":{"include":"core/*"},"report":{"omit":"tests/*"}}}'
```

### Aşama C — Üretilen testi hedef dosyaya yaz

`x` dosyasını burada belirliyorsun. Örn: `tests/core/test_llm_client_coverage_x.py`

```bash
python cli.py -c 'write_missing_tests|{"suggested_test_path":"tests/core/test_llm_client_coverage_x.py","generated_test":"def test_x():\n    assert True","append":true}'
```

> `append=true` mevcut dosyaya ekler, `append=false` dosyayı yeniden yazar.

---

## 4) Tek komutta (otomatik) akış

Aşağıdaki gibi tek prompt da verebilirsin; agent pytest çalıştırır, bulgu çıkarır, test üretir ve önerilen dosyaya yazar:

```bash
python cli.py -c '{"command":"pytest --cov-fail-under=90","cwd":"."}'
```

Bu mod hızlıdır ama kontrol seviyesi düşüktür. Özellikle “`x` isimli özel dosya” istiyorsan 3 aşamalı prefix akışı daha doğru.

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
pytest -q tests/core/test_llm_client_coverage_x.py
pytest --cov-fail-under=90
```

Eğer testler geçiyor ama coverage artmıyorsa:
- yanlış modül/path hedeflenmiş olabilir,
- branch yolları tetiklenmemiş olabilir,
- `omit/include` ayarları `.coveragerc` içinde filtreliyor olabilir.

## 7) Sık yapılan hata

Coverage agent’in kendi coverage’inin `%81` olması, projenin toplam `%90` olduğu anlamına gelmez. Toplam değer tüm backend dosyalarının ağırlıklı toplamıdır.

---

## Kısa cevap (TL;DR)

Evet, `coverage_agent` ile `x` dosyası oluşturup doldurabilirsin. En iyi yöntem:
1. `analyze_coverage_report|...`
2. `generate_missing_tests|...`
3. `write_missing_tests|{"suggested_test_path":"tests/.../x.py",...}`

İstersen bir sonraki adımda senin coverage çıktına göre **ilk 3 hedef dosya + hazır komutları** birebir üretebilirim.
