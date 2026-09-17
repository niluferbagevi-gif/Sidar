# `plugins/slack_notification_agent.py` — Slack Bildirim Marketplace Eklentisi

- **Kaynak dosya:** `plugins/slack_notification_agent.py`
- **Not dosyası:** `docs/module-notes/plugins/slack_notification_agent.py.md`

**Amaç:** Slack bildirimleri için hot-loadable marketplace eklentisi;
`SlackNotificationAgent`, yapılandırılmış bir webhook URL'sine kanal
bildirimi gönderir (dış servise yazan, `requires_auth=True` bir eklenti).

**Özellikler:**
- `run_task(task_prompt)` — prompt'tan hedef kanalı (`_extract_channel`,
  `#kanal-adi` deseni) ve mesaj metnini (`_extract_message`) ayrıştırır;
  `cfg.SLACK_WEBHOOK_URL` boşsa yapılandırma eksikliğini bildirir, aksi
  halde `urllib.request` ile (10sn zaman aşımı, `asyncio.to_thread`
  içinde) POST isteği atar.
- `_extract_channel(prompt)` / `_extract_message(prompt)` — regex tabanlı
  ayrıştırma; kanal etiketi mesajdan çıkarılıp geri kalanı bildirim
  metni olarak kullanılır.
- `_format_response(ok, detail, channel, message)` — başarı/hata
  durumuna göre kullanıcıya dönecek özet metni kurar.

## İlgili modüller

`plugins/manifest.py` (`slack_notifications` manifesti,
`secret_names=("SLACK_WEBHOOK_URL", "SLACK_TOKEN")`),
`managers/slack_manager.py` (ayrı, doğrudan Slack entegrasyon yolu).
