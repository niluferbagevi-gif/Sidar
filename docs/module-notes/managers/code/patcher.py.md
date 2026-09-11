# `managers/code/patcher.py` — Yama (Patch) Uygulama Yardımcısı

- **Kaynak dosya:** `managers/code/patcher.py`
- **Not dosyası:** `docs/module-notes/managers/code/patcher.py.md`

**Amaç:** LLM'nin ürettiği "hedef blok → değiştirme bloğu" yama isteklerini
tam olarak bir kez eşleşme garantisiyle uygular; sıfır veya birden fazla
eşleşmede kullanıcıya (Türkçe) düzeltici geri bildirim mesajı üretir.

**Özellikler:**
- `apply_exact_block_patch(content, target_block, replacement_block)` —
  `content.count(target_block)` ile eşleşme sayısını kontrol eder; `0` veya
  `>1` eşleşmede `(False, açıklayıcı_mesaj)`, tam `1` eşleşmede
  `(True, yeni_içerik)` döner.
