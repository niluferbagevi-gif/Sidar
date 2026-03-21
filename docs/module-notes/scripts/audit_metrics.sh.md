# `scripts/audit_metrics.sh`

- **Kaynak dosya:** `scripts/audit_metrics.sh`
- **Not dosyası:** `docs/module-notes/scripts/audit_metrics.sh.md`
- **Kategori:** Repo denetim / metrik üretimi (operasyonel yardımcı script)
- **Çalışma tipi:** Bash (`set -euo pipefail` ile katı hata modu)

## 1) Bu script ne işe yarar?

`scripts/audit_metrics.sh`, verilen bir kök dizin altında belirli dosya uzantıları için:

- dosya sayısını,
- toplam satır sayısını,
- ve tüm uzantıların genel toplamını

üretir. Script iki çıktı formatını destekler:

- `markdown` (varsayılan): İnsan okuyabilir tablo.
- `json`: CI/otomasyon için makinece parse edilebilir çıktı.

Hedeflenen uzantılar script içinde sabit bir dizi olarak tanımlıdır:

```bash
exts=(py js css html md)
```

## 2) Girdi parametreleri

Script en fazla iki positional argüman alır:

1. `root` (opsiyonel): Taranacak kök dizin. Varsayılan `.`
2. `format` (opsiyonel): `markdown` veya `json`. Varsayılan `markdown`

Örnek:

```bash
./scripts/audit_metrics.sh . markdown
./scripts/audit_metrics.sh /workspace/sidar_project json
```

## 3) Çalışma mantığı (detay)

Script iki yardımcı fonksiyonla ilerler:

### `count_files(ext)`

- Git deposu içindeyse `git ls-files "*.${ext}"` ile yalnızca takipli dosyaları listeler.
- Git dışında çalışırsa fallback olarak `find` ile `.git` harici dosyaları tarar.
- Sonucu `wc -l` ile sayar.

### `count_lines(ext)`

- Aynı uzantı için dosya listesini toplar.
- Satır sayısını Python ile her dosyayı UTF-8 okuyarak hesaplar.
- Böylece boşluklu dosya adlarında shell ayrıştırma riski azaltılır.

Ardından script:

- her uzantı için `files` ve `lines` değerini hesaplar,
- `total_files` ve `total_lines` değişkenlerinde genel toplamları biriktirir,
- seçilen formata göre çıktıyı basar.

## 4) Nerede / nasıl kullanılıyor?

Bu script, depoda **repo hijyeni ve metrik standardizasyonu** için referans alınır.

### Dokümantasyonda açık referanslar

- `README.md` içinde tek komutla JSON/Markdown metrik üretimi için doğrudan önerilir.
- `PROJE_RAPORU.md` içinde:
  - kalite kapısı tablosunda “Repo metrik/audit üretimi” maddesinde,
  - kod satır sayısı ölçüm notunda,
  - operasyonel script envanterinde
  doğrudan kaynak olarak listelenir.

> Not: Bu script doğrudan başka bir script tarafından çağrılmak zorunda değildir; dökümantasyonda “standart ölçüm aracı” olarak konumlanmıştır.

## 5) Kullanım örnekleri ve örnek sonuçlar

Aşağıdaki örnekler mevcut repo kökünde (`/workspace/Sidar`) alınmıştır.

### Örnek A — Varsayılan markdown çıktı

Komut:

```bash
bash scripts/audit_metrics.sh
```

Örnek çıktı:

```markdown
# Audit Metrics

| Uzantı | Dosya Sayısı | Satır Sayısı |
|---|---:|---:|
| .py | 229 | 74280 |
| .js | 11 | 3231 |
| .css | 3 | 2850 |
| .html | 4 | 745 |
| .md | 97 | 8441 |
| **Toplam** | **344** | **89547** |
```

### Örnek B — JSON çıktı (CI/otomasyon)

Komut:

```bash
bash scripts/audit_metrics.sh . json
```

Örnek çıktı:

```json
{"root":".","generated_at":1774059294,"tracked":true,"metrics":{"py":{"files":229,"lines":74280},"js":{"files":11,"lines":3231},"css":{"files":3,"lines":2850},"html":{"files":4,"lines":745},"md":{"files":97,"lines":8441}},"totals":{"files":344,"lines":89547}}
```

> `generated_at` alanı Unix epoch (saniye) olduğundan her çalıştırmada değişir.

## 6) Bağımlılıklar

Bu script herhangi bir Python paketi istemez; POSIX kullanıcı alanı araçlarıyla çalışır.

- Bash
- Git (`git ls-files`, takipli dosyaları saymak için)
- Python 3
- `find` (Git dışı fallback için)
- `wc`
- `tr`
- `date`

Ayrıca shell davranışı için `set -euo pipefail` kullanır:

- `-e`: Komut hatasında çık
- `-u`: Tanımsız değişken kullanımında hata
- `-o pipefail`: Pipe zincirinde herhangi bir adım hata verirse pipeline hatalı kabul edilir

## 7) Sınırlamalar ve dikkat edilmesi gerekenler

1. **Uzantı listesi sabittir** (`py/js/css/html/md`). Başka uzantılar (örn. `ts`, `yaml`) sayılmaz.
2. **Takipsiz dosyalar:** Git modunda yalnızca takipli dosyalar sayıldığı için henüz commit edilmemiş yeni dosyalar rapora girmez.
3. **`.git` hariç tutulur**, ancak Git dışı fallback modunda diğer vendor/cache klasörleri için özel hariç tutma yoktur.
4. **JSON escape** mantığı minimaldir; `root` gibi alanlarda sıra dışı karakterler varsa ek kaçış ihtiyacı doğabilir.

## 8) Diğer scriptlerle ilişki

- `scripts/collect_repo_metrics.sh`: Daha dar kapsamda yalnızca Python/Markdown dosya ve satır metrikleri üretir.
- `scripts/audit_metrics.sh`: Çoklu uzantı + markdown/json format desteğiyle audit raporu üretir.

Bu nedenle `audit_metrics.sh`, raporlama/denetim çıktısı için; `collect_repo_metrics.sh` ise hızlı key-value metrik çıkarımı için daha uygun bir yardımcıdır.