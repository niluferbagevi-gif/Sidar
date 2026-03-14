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

Script `find + wc -l` kombinasyonu ile sayım yapar:

- `.py` ve `.md` dosya sayıları doğrudan bulunur.
- Python satır toplamı için `.py` dosyaları `-print0` + `xargs -0 cat` ile birleştirilip `wc -l` uygulanır.
- Test dosyaları `"$root/tests"` altında `test_*.py` deseniyle sayılır.

Sonuçlar şu formatta basılır:

```text
python_files=...
markdown_files=...
python_lines=...
test_files=...
```

## 5) Kullanım ve örnek çıktı

Komut:

```bash
bash scripts/collect_repo_metrics.sh
```

Örnek çıktı:

```text
python_files=132
markdown_files=87
python_lines=34226
test_files=91
```

## 6) Bağımlılıklar

- Bash
- `find`
- `wc`
- `tr`
- `xargs`
- `cat`

## 7) Sınırlamalar

1. Uzantı kapsamı yalnızca `.py` ve `.md` ile sınırlıdır.
2. `.git` gibi klasörler için ek filtre yoktur.
3. `python_lines` hesabı tüm `.py` dosyalarını dahil eder; generated/vendor ayrımı yapmaz.