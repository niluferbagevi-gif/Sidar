# `web/routes/__init__.py` — Route Modülleri Paket Kökü

- **Kaynak dosya:** `web/routes/__init__.py`
- **Not dosyası:** `docs/module-notes/web/routes/__init__.py.md`

**Amaç:** Tüm `web/routes/*.py` router fabrikalarının paylaştığı
`LegacyExportRouter` sınıfını tanımlar.

**Özellikler:**
- `LegacyExportRouter(APIRouter)` — geriye dönük uyumluluk hook'ları için
  tipli `legacy_exports: dict[str, Any]` kayıt defteri taşıyan `APIRouter`
  alt sınıfı; her router fabrikası bunu döndürür.
