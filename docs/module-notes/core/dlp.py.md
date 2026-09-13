# `core/dlp.py` — DLP (Data Loss Prevention) & PII Maskeleme

- **Kaynak dosya:** `core/dlp.py`
- **Not dosyası:** `docs/module-notes/core/dlp.py.md`

**Amaç:** Hassas verileri LLM API çağrılarından önce maskeler/temizler
(`mask_pii()` / `get_dlp_engine()`).

**Desteklenen örüntüler:** API anahtarları/token'lar (Bearer, `sk-`, `ghp_`,
AWS `AKIA...`), genel `key=value` biçimli sırlar, parolalar (`password=`,
`parola=` vb.), Türkiye TC Kimlik No (11 haneli, komşu para-birimi/ondalık
değerlerle yanlış eşleşmeyi azaltan negatif lookaround'lu regex), e-posta
adresleri, kredi kartı numaraları (Luhn algoritması isteğe bağlı), IPv4/IPv6
adresleri (özel ağ hariç tutulabilir), JWT token'ları ve genel uzun
hex/base64 sırlar. Her örüntü ayrı, derlenmiş bir regex sabiti olarak
tanımlanmış (`_RE_BEARER`, `_RE_SK_KEY`, `_RE_TCKN`, vb.), maskeleme
`_DEFAULT_MASK = "[MASKED]"` ile yapılır.
