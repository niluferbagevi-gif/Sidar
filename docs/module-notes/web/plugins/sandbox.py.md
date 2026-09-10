# `web/plugins/sandbox.py` — Plugin Kaynak Doğrulama ve İzolasyon Politikası

- **Kaynak dosya:** `web/plugins/sandbox.py`
- **Not dosyası:** `docs/module-notes/web/plugins/sandbox.py.md`

**Amaç:** Plugin marketplace'in üçüncü taraf plugin kaynak kodunu
çalıştırmadan önce doğrulayan ve izolasyon backend'ini seçen politika
katmanı. Docker her ortamda varsayılandır; legacy in-process backend yalnızca
operatörün açık, production-dışı opt-in'iyle etkinleşir (bkz.
`bandit-suppression-baseline.json`'daki B102 `exec()` kararı — bu dosyanın
`run_plugin_source_in_process()`'i legacy backend'in *tüm amacı* olduğu için
bilinçli olarak korunur, `docs/REFACTOR_PLAN.md` altında izlenir).
Doğrulayıcı yalnızca defense-in-depth katmanıdır, tek güvenlik sınırı değildir.

**Özellikler:**
- `PluginSandboxError` — sandbox politika ihlallerinde fırlatılır.
- `plugin_sandbox_backend(env=None)` — ortam değişkenlerinden aktif backend'i
  (`docker`/`in_process`) çözer.
- `DockerPluginSandboxBackend` — plugin kodunu izole bir Docker container'da
  çalıştıran ana backend sınıfı (`managers/code/docker.py`'deki sanitize
  edilmiş image/limit yardımcılarını kullanır).
- `build_isolated_plugin_proxy(...)` — host tarafında container'a JSON-RPC
  isteği gönderen proxy nesnesi kurar (`web/plugins/worker.py` ile eşleşir).
- `validate_plugin_source(source_code)` — `ast` tabanlı statik analizle
  tehlikeli import/çağrıları reddeder.
- `execute_validated_plugin_source(...)`, `run_plugin_source_in_process(...)`,
  `restricted_plugin_import(...)`, `build_restricted_plugin_builtins()`,
  `assert_in_process_plugin_execution_allowed()` — yalnızca opt-in edilmişse
  erişilebilen, kısıtlı `builtins`/`import` ile çalışan legacy in-process yol.
- `in_process_plugin_execution_allowed(env=None)` — legacy yolun açıkça
  etkinleştirilip etkinleştirilmediğini kontrol eder (fail-closed: varsayılan
  kapalı).
