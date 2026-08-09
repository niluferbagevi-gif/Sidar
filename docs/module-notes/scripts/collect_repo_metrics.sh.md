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
- `test_files`: `tests/` altındaki tüm `test_*.py` dosya sayısı
- `production_python_files`: `tests/` dışındaki `.py` dosya sayısı
- `production_python_lines`: `tests/` dışındaki `.py` dosyalarının toplam satır sayısı

Çıktı `key=value` formatındadır; CI loglarında kolay okunur ve parse edilir.

## 2) Parametre

- `root` (opsiyonel): Taranacak kök dizin (`.` varsayılan)

Örnek:

```bash
bash scripts/collect_repo_metrics.sh
bash scripts/collect_repo_metrics.sh /workspace/Sidar
```

## 3) Nerede kullanılır?

- `.github/workflows/ci.yml` içinde doğrudan çalıştırılır.
- `PROJE_RAPORU.md` içinde “Repo metrik/audit üretimi” başlığında `audit_metrics.sh` ile birlikte referanslanır.

## 4) Çalışma mantığı

Script varsayılan olarak `git ls-files` ile yalnız Git tarafından takip edilen dosyaları
sayar; Git komutu başarısız olursa `.git` dışındaki dosyalar için `Path.rglob()` fallback'i
kullanır. Böylece `.venv`, `node_modules` veya takip dışı artifact'ler metrikleri şişirmez.

- `.py` ve `.md` dosya sayıları takipli dosya listesi üzerinden hesaplanır.
- Python satır toplamı, takipli `.py` dosyalarının UTF-8 satır sayısı toplanarak üretilir.
- Test dosyaları `tests/` altında basename'i `test_` ile başlayan tüm `.py` dosyalarıdır;
  yalnız `tests/test_*.py` kök dosyalarıyla sınırlı değildir.
- Production Python metrikleri `tests/` dışındaki takipli `.py` dosyalarını kapsar.

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
python_files=501
markdown_files=112
python_lines=167638
test_files=218
production_python_files=260
production_python_lines=64393
```

## 6) Bağımlılıklar

- Bash
- Python 3
- Git (tercih edilir; yoksa Python fallback devreye girer)

## 7) Sınırlamalar

1. Uzantı kapsamı yalnızca `.py` ve `.md` ile sınırlıdır.
2. Git fallback modunda `.git` dışındaki takip dışı dosyalar da sayılabilir; release metrikleri
   için Git repo içinde `git ls-files` yolu tercih edilmelidir.
3. `python_lines` hesabı tüm takipli `.py` dosyalarını dahil eder; generated/vendor ayrımı
   ancak bu dosyalar Git dışında bırakılmışsa otomatik korunur.
