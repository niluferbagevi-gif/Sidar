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

- `find "$root" -type f -name "*.${ext}"` ile eşleşen dosyaları bulur.
- `.git` altını `-not -path "*/.git/*"` ile hariç tutar.
- Sonucu `wc -l` ile sayar.

### `count_lines(ext)`

- Aynı filtre ile dosya listesini toplar.
- Dosya yoksa güvenli şekilde `0` döner.
- Dosyalar varsa `wc -l` toplam satırını üretir.

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

Aşağıdaki örnekler mevcut repo kökünde (`/workspace/sidar_project`) alınmıştır.

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
| .py | 132 | 34226 |
| .js | 4 | 1904 |
| .css | 1 | 1684 |
| .html | 1 | 572 |
| .md | 87 | 4282 |
| **Toplam** | **225** | **42668** |
```

### Örnek B — JSON çıktı (CI/otomasyon)

Komut:

```bash
bash scripts/audit_metrics.sh . json
```

Örnek çıktı:

```json
{"root":".","generated_at":1773461720,"metrics":{"py":{"files":132,"lines":34226},"js":{"files":4,"lines":1904},"css":{"files":1,"lines":1684},"html":{"files":1,"lines":572},"md":{"files":87,"lines":4282}},"totals":{"files":225,"lines":42668}}
```

> `generated_at` alanı Unix epoch (saniye) olduğundan her çalıştırmada değişir.

## 6) Bağımlılıklar

Bu script herhangi bir Python paketi istemez; POSIX kullanıcı alanı araçlarıyla çalışır.

- Bash
- `find`
- `wc`
- `awk`
- `tail`
- `tr`
- `date`

Ayrıca shell davranışı için `set -euo pipefail` kullanır:

- `-e`: Komut hatasında çık
- `-u`: Tanımsız değişken kullanımında hata
- `-o pipefail`: Pipe zincirinde herhangi bir adım hata verirse pipeline hatalı kabul edilir

## 7) Sınırlamalar ve dikkat edilmesi gerekenler

1. **Uzantı listesi sabittir** (`py/js/css/html/md`). Başka uzantılar (örn. `ts`, `yaml`) sayılmaz.
2. **Boşluk içeren dosya adları:** `count_lines` fonksiyonunda `wc -l $files` yaklaşımı kullanıldığından sıra dışı dosya adlarında risk olabilir.
3. **`.git` hariç tutulur**, ancak diğer vendor/cache klasörleri için özel hariç tutma yoktur.
4. **JSON escape** mantığı minimaldir; `root` gibi alanlarda sıra dışı karakterler varsa ek kaçış ihtiyacı doğabilir.

## 8) Diğer scriptlerle ilişki

- `scripts/collect_repo_metrics.sh`: Daha dar kapsamda yalnızca Python/Markdown dosya ve satır metrikleri üretir.
- `scripts/audit_metrics.sh`: Çoklu uzantı + markdown/json format desteğiyle audit raporu üretir.

Bu nedenle `audit_metrics.sh`, raporlama/denetim çıktısı için; `collect_repo_metrics.sh` ise hızlı key-value metrik çıkarımı için daha uygun bir yardımcıdır.