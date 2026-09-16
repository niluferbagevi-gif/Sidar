# `web/plugins/worker.py` — İzole Plugin Container'ı için JSON-RPC Worker

- **Kaynak dosya:** `web/plugins/worker.py`
- **Not dosyası:** `docs/module-notes/web/plugins/worker.py.md`

**Amaç:** `web/plugins/sandbox.py`'nin `DockerPluginSandboxBackend`'inin
başlattığı, izole container içinde tek bir JSON-RPC isteğini işleyip yanıt
basan worker process'i. Import zamanında bile gerçek `stdout`'u yalnızca
`main()`'in en sonda yazdığı tek JSON yanıtına ayırır: `sys.stdout`'u en
başta `sys.stderr`'e yönlendirir, çünkü `config.py`'nin kök logging
handler'ı varsayılan olarak stdout'u hedefler ve bu worker'ın salt-okunur
container dosya sisteminde log dosyası handler'ı engellenince bir uyarı
basar — bu, JSON yanıtından önce RPC kanalını bozan gerçek bir üretim hatası
olarak `SEC-PLUGIN-001` container entegrasyon testinde keşfedildi.

**Özellikler:**
- `_RPC_STDOUT = sys.stdout` (orijinal stream saklanır) ardından
  `sys.stdout = sys.stderr` — importlardan önce ilk iş olarak yapılır.
- `_agent_class(namespace, requested)` — plugin modülünden çalıştırılacak
  `BaseAgent` alt sınıfını çözer.
- `handle_request(request)` — tek bir RPC isteğini işler.
- `main()` — stdin'den isteği okur, yanıtı `_RPC_STDOUT`'a yazar.
