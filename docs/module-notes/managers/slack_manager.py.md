# `managers/slack_manager.py` — Slack integration

Slack SDK bot tokenı ve doğrulanmış Slack Incoming Webhook URL'leri üzerinden mesaj gönderir.
SDK yoksa webhook moduna kontrollü düşer; kimlik bilgileri yoksa entegrasyon pasif kalır.

Token ve webhook parametreleri `None` varsayılanıyla secret-optional sözleşmesini açıklar;
girişler istemci sınırında normalize edildiği için mevcut boş-string konfigürasyonları aynı
davranışı korur.

