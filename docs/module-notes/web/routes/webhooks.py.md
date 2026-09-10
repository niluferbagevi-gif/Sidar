# `web/routes/webhooks.py` — GitHub Webhook Rotaları

- **Kaynak dosya:** `web/routes/webhooks.py`
- **Not dosyası:** `docs/module-notes/web/routes/webhooks.py.md`

**Amaç:** GitHub webhook uç noktasını ve imza doğrulamasını (`web/security.py`'nin
`verify_webhook_hmac_signature()` ailesini kullanarak) kaydeder; bayrak ile
devre dışı bırakılabilir ama devre dışı bırakma açıkça loglanır.

**Özellikler:**
- `GithubSignatureValidationResult` (`Literal["disabled_by_flag", "verified"]`)
  — imza doğrulamasının sonucunu tipli biçimde ayırt eder.
- `_coerce_bool(value, *, default)` — config/env boolean normalizasyonu.
- `_github_webhook_signature_required(cfg)`,
  `_validate_github_webhook_signature(...)` — imza zorunluluğunu ve
  doğrulamasını uygular.
- `build_webhooks_router(...)` — `POST` webhook rotasını kaydeden fabrika.
