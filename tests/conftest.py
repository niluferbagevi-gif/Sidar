"""
Proje genelinde pytest yapılandırması.

Bu conftest.py, test çalıştırma sırasında oluşan modül izolasyon sorunlarını
önlemek için oturum başında kritik modülleri önceden yükler.

Arka plan: bazı test dosyaları (test_llm_client_runtime.py, test_package_info_extended.py,
test_rag_runtime_extended.py, vb.) sys.modules["httpx"]'i, monkeypatch kullanmadan
değiştirir ve geri yüklemez. Bu durum, test koleksiyon aşamasında çalışan modül
düzeyindeki kodu etkiler (örn. test_package_info_extended.py satır 56: PKG = _load_pkg()).

Bu modül yüklendiğinde (pytest koleksiyonundan önce) gerçek httpx'i kaydeder ve
chromadb'yi önceden yükler, böylece sonraki testlerin bozulan httpx stub'larından
etkilenmemesi sağlanır.
"""
import sys

# Conftest.py, diğer test dosyalarının modül düzeyindeki kodu çalışmadan önce
# yüklenir. Gerçek httpx'i burada kaydet.
try:
    import httpx as _REAL_HTTPX_GLOBAL
except ImportError:
    _REAL_HTTPX_GLOBAL = None

import pytest


@pytest.fixture(scope="session", autouse=True)
def _preload_chromadb():
    """
    Test koleksiyonu sırasında bazı modüller httpx'i stub ile değiştirir
    (örn. test_package_info_extended.py PKG = _load_pkg() satırı). Bu,
    chromadb'nin oturum başında önceden yüklenmesini engeller.

    Bu fixture, önce gerçek httpx'i geri yükler, sonra chromadb'yi yükler.
    Böylece chromadb sys.modules'a eklenir ve sonraki importlib.import_module()
    çağrıları önbelleğe alınmış sürümü döndürür.
    """
    # Gerçek httpx'i geri yükle (koleksiyon sırasında bozulmuş olabilir)
    if _REAL_HTTPX_GLOBAL is not None:
        sys.modules["httpx"] = _REAL_HTTPX_GLOBAL

    try:
        import importlib
        importlib.import_module("chromadb")
        # Tüm chromadb modüllerinin httpx referansını güncelle
        _chromadb_httpx_mods = [
            "chromadb.api.base_http_client",
            "chromadb.api.client",
            "chromadb.api.async_client",
            "chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2",
        ]
        for _mod_name in _chromadb_httpx_mods:
            _mod = sys.modules.get(_mod_name)
            if _mod is not None and hasattr(_mod, "httpx") and _REAL_HTTPX_GLOBAL is not None:
                try:
                    _mod.httpx = _REAL_HTTPX_GLOBAL
                except Exception:
                    pass
    except Exception:
        pass  # chromadb kurulu değilse, ilgili testler skip edilir

    yield
