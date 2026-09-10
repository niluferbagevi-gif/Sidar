# `web/middleware/access_policy.py` — Erişim Politikası Middleware Yardımcıları

- **Kaynak dosya:** `web/middleware/access_policy.py`
- **Not dosyası:** `docs/module-notes/web/middleware/access_policy.py.md`

**Amaç:** Sidar'ın web API'si için tenant-farkında erişim politikası (RBAC/ABAC
benzeri) yardımcılarını sağlar — kayıt (`serialize_policy`), denetim
kaydı (`serialize_audit_log`) serileştirmesi ve HTTP path'ini kaynak/aksiyon
çiftine eşleyen `resolve_policy_from_request()`.

**Özellikler:**
- `get_user_tenant()` — kimliği doğrulanmış principal'dan normalize edilmiş
  tenant kimliği çıkarır (varsayılan `"default"`).
- `resolve_policy_from_request()` — path'e göre kaynak türü/aksiyon eşlemesi
  yapar (`/rag/*` → `rag` okuma/yazma, `/github-*`/`/set-repo` → `github`,
  `/api/agents/register` → `agents.register`, `/api/swarm/*` → `swarm.execute`,
  `/api/operations/*` vb.) — bu eşleme, gerçek yetkilendirme kararının
  (allow/deny) hangi politika kaydına karşı değerlendirileceğini belirler.
