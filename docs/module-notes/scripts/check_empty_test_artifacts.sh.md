# `scripts/check_empty_test_artifacts.sh`

- **Kaynak dosya:** `scripts/check_empty_test_artifacts.sh`
- **Not dosyası:** `docs/module-notes/scripts/check_empty_test_artifacts.sh.md`
- **Kategori:** CI kalite kapısı / test hijyeni
- **Çalışma tipi:** Bash (`set -euo pipefail`)

## 1) Ne işe yarar?

Bu script, `tests/` dizini altında **0 bayt (boş) test artifact dosyası** olup olmadığını denetler.

- Boş dosya bulunursa:
  - `❌ Empty test artifact(s) found:` mesajı basar,
  - dosya yollarını listeler,
  - `exit 1` ile pipeline’ı fail eder.
- Boş dosya yoksa:
  - `✅ No empty test artifacts found` mesajı basar,
  - başarılı şekilde biter.

## 2) Nerede kullanılır?

- CI kalite kapısı olarak kullanılır; `PROJE_RAPORU.md` içinde “Boş test artifact engeli” maddesinde doğrudan referanslanır.
- Amaç, yanlışlıkla repoya eklenen boş test dosyalarının kaliteyi düşürmesini engellemektir.

## 3) Çalışma mantığı

Script tek bir kontrol etrafında çalışır:

```bash
empty_files=$(find tests -type f -size 0 -print)
```

- `find tests -type f -size 0` ile boş dosyalar bulunur.
- Sonuç değişkeni boş değilse hata verilir; boşsa başarı mesajı basılır.

## 4) Kullanım örnekleri

### Örnek A — Normal kontrol

```bash
bash scripts/check_empty_test_artifacts.sh
```

Örnek başarılı çıktı:

```text
✅ No empty test artifacts found
```

### Örnek B — CI içinde kalite kapısı

```bash
bash scripts/check_empty_test_artifacts.sh && echo "quality_gate=pass"
```

- Script `0` dönerse sonraki adımlar devam eder.
- Script `1` dönerse job fail olur.

## 5) Bağımlılıklar

- Bash
- `find`

Ek Python paketi veya servis bağımlılığı yoktur.

## 6) Sınırlamalar / notlar

1. Script yalnızca `tests/` altında arama yapar.
2. Boş olmayan fakat anlamsız/yanlış içerik barındıran dosyaları tespit etmez.
3. Çıktı formatı sade metindir; JSON üretmez.
