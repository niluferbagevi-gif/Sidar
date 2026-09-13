# `plugins/aws_management_agent.py` — AWS Yönetim Marketplace Eklentisi

- **Kaynak dosya:** `plugins/aws_management_agent.py`
- **Not dosyası:** `docs/module-notes/plugins/aws_management_agent.py.md`

**Amaç:** AWS operasyonları için hot-loadable (çalışırken yüklenebilir)
marketplace eklentisi; `BaseAgent`'ı genişleten `AWSManagementAgent`,
sabit bir komut allowlist'i (`_COMMAND_MAP`: `ec2`/`s3`/`cloudwatch`)
üzerinden host'ta kurulu AWS CLI'ı çalıştırır.

**Özellikler:**
- `_security_manager()` — `managers/security.py`'deki
  `SecurityManager`'ı çözer; host shell erişimi bu manager üzerinden
  kapılanır.
- `run_task(task_prompt)` — önce `can_run_shell()` ile
  `ACCESS_LEVEL=full` olmadan komut çalıştırmayı reddeder (fail-closed),
  ardından AWS CLI'ın PATH'te olup olmadığını kontrol eder, prompt'tan
  anahtar kelimeyle (`_select_command`) sabit bir AWS CLI komutu seçer ve
  `asyncio.to_thread` ile 20 saniye zaman aşımlı çalıştırır.
- `_select_command(prompt)` — yalnızca üç sabit komuta (instance/bucket/
  alarm listeleme) izin verir; serbest metinden dinamik komut kurmaz —
  komut enjeksiyonu yüzeyini kapatır.
- `_summarize_output(prompt, stdout)` — AWS CLI'ın JSON çıktısını (S3
  bucket listesi, EC2 instance'ları veya CloudWatch alarmları) kısa,
  okunabilir bir özete indirger.

## İlgili modüller

`managers/security.py`, `plugins/manifest.py` (`aws_management`
manifesti), `agent/base_agent.py`.
