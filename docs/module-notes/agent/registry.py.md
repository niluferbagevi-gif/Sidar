# `agent/registry.py` — Ajan rol kataloğu

## Amaç

Bu modül, Sidar çalışma zamanında kullanılabilen ajan rollerinin tek kayıt ve üretim
yüzeyidir. `AgentCatalog`, decorator veya programatik kayıt yoluyla rol sınıflarını
metadata ile eşler; supervisor ve swarm router bu katalog üzerinden capability tabanlı
ajan keşfi yapar.

## Temel sözleşmeler

- `AgentCatalog.register(...)`, sınıf tanımı sırasında rol adı, capability listesi,
  açıklama, sürüm ve built-in metadata'sını kaydeder.
- `AgentCatalog.register_type(...)`, çalışma zamanı ve eklenti kayıtları için aynı
  kataloğun programatik girişidir.
- `get`, `list_all`, `find_by_capability` ve `create` yolları aynı registry state'ini
  kullanır; router katmanları ayrı rol allowlist'i tutmamalıdır.
- `_import_builtin_roles()`, yerleşik rol modüllerini import ederek decorator
  kayıtlarının çalışma zamanı başlatılırken gerçekleşmesini sağlar.

## Değişiklik etkisi ve doğrulama

Yeni bir built-in rol eklenirken rol modülü, `agent/roles/__init__.py` export'u,
`_import_builtin_roles()` import listesi ve capability/router sözleşmeleri birlikte
güncellenmelidir. Eksik import rolün kaynak kodda bulunmasına rağmen katalogda görünmemesine;
yanlış `is_builtin` değeri ise eklenti ve yerleşik rol güven sınırlarının karışmasına neden
olabilir. İlgili temel regresyon yüzeyi
`tests/unit/agent/test_builtin_role_contracts.py` testleridir.

## RAG notu

Sidar doküman araması bu notu ingest ettiğinde rol keşfi için statik dosya taraması yerine
`AgentCatalog` metadata'sının kaynak kabul edilmesi gerekir. Capability veya built-in rol
listesi değiştiğinde bu not ve `AGENTS.md` birlikte güncel tutulmalıdır.
