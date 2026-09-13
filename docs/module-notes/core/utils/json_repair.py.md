# `core/utils/json_repair.py` — LLM JSON Çıktısı Onarım Yardımcıları

- **Kaynak dosya:** `core/utils/json_repair.py`
- **Not dosyası:** `docs/module-notes/core/utils/json_repair.py.md`

**Amaç:** LLM'lerin ürettiği hafif bozuk/markdown-fence'li JSON çıktısını,
sınırlı (budget'lı) ve güvenli biçimde (keyfi kod çalıştırmadan) onarmaya
çalışır; `ast.literal_eval` yalnızca güvenli literal adaylarda kullanılır.

**Özellikler:**
- `STRICT_FENCE_PATTERN`, `LOOSE_FENCE_PATTERN` — ` ```json ` code fence
  ayıklama regex'leri.
- `MAX_JSON_REPAIR_INPUT_CHARS`, `MAX_JSON_REPAIR_NESTING`,
  `MAX_JSON_REPAIR_ATTEMPTS` — DoS'a karşı sabit üst sınırlar.
- `_RepairBudget` (slotted dataclass) — direct/decoder/fenced/literal onarım
  yolları arasında paylaşılan iş bütçesini sınırlar.
- `is_safe_literal_eval_candidate(...)` — `ast.literal_eval` öncesi girdinin
  güvenli olup olmadığını doğrular.
- `repair_json_text(text)`, `repair_json_text_async(text)` (async) — üst
  düzey onarım API'si; başarısızsa `None` döner (sessiz veri uydurma yok).
