# `scripts/collect_repo_metrics.sh`

- **Kaynak dosya:** `scripts/collect_repo_metrics.sh`
- **Not dosyası:** `docs/module-notes/scripts/collect_repo_metrics.sh.md`
- **Kategori:** Repo metrik özeti (CI-friendly)
- **Çalışma tipi:** Bash (`set -euo pipefail`)

## 1) Ne işe yarar?

Bu script, repo için hızlı bir metrik özeti üretir:

- `python_files`: `.py` dosya sayısı
- `markdown_files`: `.md` dosya sayısı
- `python_lines`: tüm `.py` dosyalarının toplam satır sayısı
- `test_files`: `tests/` altındaki `test_*.py` dosya sayısı
- `production_python_files`: `tests/` dışındaki takipli `.py` dosya sayısı
- `production_python_lines`: üretim Python kodunun toplam satır sayısı

Çıktı `key=value` formatındadır; CI loglarında kolay okunur ve parse edilir.

## 2) Parametre

- `root` (opsiyonel): Taranacak kök dizin (`.` varsayılan)

Örnek:

```bash
bash scripts/collect_repo_metrics.sh
bash scripts/collect_repo_metrics.sh /workspace/sidar_project
```

## 3) Nerede kullanılır?

- `.github/workflows/ci.yml` içinde doğrudan çalıştırılır.
- `PROJE_RAPORU.md` içinde “Repo metrik/audit üretimi” başlığında `audit_metrics.sh` ile birlikte referanslanır.

## 4) Çalışma mantığı

Script, `git ls-files` çıktısını temel alıp Python üzerinden satır sayımı yapar:

- Git deposu içindeyse yalnızca takipli dosyalar sayılır; aksi durumda `.git` hariç dosyalar fallback olarak taranır.
- `.py` ve `.md` dosya sayıları `git ls-files` listesi üzerinden çıkarılır.
- Satır toplamları her dosyanın UTF-8 olarak okunup Python içinde sayılmasıyla hesaplanır.
- Test dosyaları `tests/test_*.py` deseniyle, üretim Python dosyaları ise `tests/` dışındaki `.py` dosyalarıyla ayrıştırılır.

Sonuçlar şu formatta basılır:

```text
python_files=...
markdown_files=...
python_lines=...
test_files=...
production_python_files=...
production_python_lines=...
```

## 5) Kullanım ve örnek çıktı

Komut:

```bash
bash scripts/collect_repo_metrics.sh
```

Örnek çıktı:

```text
python_files=229
markdown_files=97
python_lines=74280
test_files=165
production_python_files=62
production_python_lines=26900
```

## 6) Bağımlılıklar

- Bash
- Git (`git ls-files`, takipli dosya ölçümü için)
- Python 3

## 7) Sınırlamalar

1. Uzantı kapsamı yalnızca `.py` ve `.md` ile sınırlıdır.
2. Takipli dosya mantığı nedeniyle `git add` edilmemiş yeni dosyalar Git modunda bu rapora girmez.
3. `python_lines` hesabı tüm `.py` dosyalarını dahil eder; generated/vendor ayrımı yapmaz.
