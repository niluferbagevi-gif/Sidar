# `managers/code/git_validation.py` — Git Ref Adı Doğrulama

- **Kaynak dosya:** `managers/code/git_validation.py`
- **Not dosyası:** `docs/module-notes/managers/code/git_validation.py.md`

**Amaç:** Kullanıcı girdisi bir `git` alt süreç çağrısına argv elemanı olarak
geçirilmeden önce doğrulanacağı tek doğruluk kaynağı. `shell=False` + liste
argv zaten shell metakarakter enjeksiyonunu engeller, ancak `-` ile başlayan
bir değerin git tarafından bir ref adı yerine bir bayrak/opsiyon olarak
yorumlanmasını ("argument injection") engellemez; bu modül git'in kendi
`git check-ref-format` kurallarını yeterince yakından taklit eder.

**Özellikler:**
- `is_valid_git_ref_name(ref_name)` — `_FORBIDDEN_FRAGMENTS` (`..`, `//`, `@{`),
  `_FORBIDDEN_CHARS` (`~^:?*[\]`) ve kontrol/boşluk karakterlerini reddeder.
