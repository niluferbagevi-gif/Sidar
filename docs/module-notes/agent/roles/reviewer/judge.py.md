# `agent/roles/reviewer/judge.py` — Saf Reviewer Değerlendirme Yardımcıları

- **Kaynak dosya:** `agent/roles/reviewer/judge.py`
- **Not dosyası:** `docs/module-notes/agent/roles/reviewer/judge.py.md`

**Amaç:** `agent/roles/reviewer_agent.py`'nin kullandığı, LLM reviewer
çıktısını yorumlayan yan-etkisiz (side-effect-free) fonksiyonlar; `core/judge.py`'nin
(LLM-as-a-Judge) reviewer'a özel prompt/normalizasyon katmanı.

**Özellikler:**
- `coerce_review_approved(raw_approved)` — LLM'nin ürettiği çeşitli onay
  ifadelerini (`"evet"`, `"approved"`, `1`, `True` vb. — Türkçe/İngilizce
  karışık) güvenli biçimde `bool`'a çevirir; tanınmayan değerde `False`'a
  düşer (fail-closed).
- `coerce_review_weaknesses(raw_weaknesses)`,
  `derive_review_weaknesses_from_reason(reason)` — zayıflık listesini
  normalize eder/reddetme nedeninden türetir.
- `normalize_test_candidate_verdict(verdict)`,
  `candidate_preview(candidate, *, max_lines=3)`,
  `build_test_candidate_review_prompt(...)` — test adayı değerlendirme
  prompt'unu ve verdict normalizasyonunu kurar.
