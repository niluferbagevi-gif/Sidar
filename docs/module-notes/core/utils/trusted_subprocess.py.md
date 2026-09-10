# `core/utils/trusted_subprocess.py` — Merkezi, denetlenmiş subprocess wrapper'ı

- **Kaynak dosya:** `core/utils/trusted_subprocess.py`
- **Not dosyası:** `docs/module-notes/core/utils/trusted_subprocess.py.md`

**Amaç:** Bandit'in B603 ("subprocess call - check for execution of untrusted
input") kuralı, argv ne kadar güvenli kurulursa kurulsun `shell=False` ve
tam-literal-olmayan argv'li hemen hemen her `subprocess.run`/`Popen`
çağrısını işaretler — bu, `bandit-suppression-baseline.json`'ın
`debt_plan.completed_reviews`'inde tek tek doğrulanmıştır: incelenen her
çağrı noktası zaten sabit/doğrulanmış bir argv kullanıyordu (mutlak,
`shutil.which`-çözümlenmiş executable'lar; tamamen iç sabitlerden kurulu
argv listeleri; allowlist'li komut şekilleri), yine de `# nosec`
kaldırıldığında aynı B603 bulgusu tekrar çıktı.

Bu modül, içsel olarak güvenilir (trusted) her subprocess çağrısını
`run_trusted_command()`/`popen_trusted_command()` üzerinden geçirerek
kaçınılmaz B603 suppression'ını TEK, denetlenmiş bir yere topluyor —
her caller artık kendi `# nosec`'ini taşımıyor. Trust modeli değişmedi:
`command`'ın sabit veya doğrulanmış/allowlist'li bir liste olmasından
hâlâ tamamen caller sorumlu; bu modül *ne* çalıştırıldığını sanitize
veya kısıtlamıyor, yalnızca audit edilmiş `subprocess.run`/`Popen`
çağrısının *nerede* yaşadığını değiştiriyor. Ayrıca minimal bir güvenlik
ağı ekliyor: `shell=True` isteğini reddeder, boş komutu reddeder, argv
içinde gömülü NUL byte'ı reddeder (`UntrustedCommandError`).

**Not:** İç yardımcı fonksiyonun (`_reject_shell_request`) parametresi
bilinçli olarak `shell=` adlı bir keyword argument olarak *çağrılmıyor* —
Bandit'in B604 (`any_other_function_with_shell_equals_true`) kuralı,
hangi fonksiyona ait olursa olsun `shell=` adlı bir keyword taşıyan HER
çağrıyı işaretleyen düşük güvenilirlikli, naif bir sezgisel; bu, gerçek
bir suppression eklemeden o yanlış pozitifi önlüyor.

**Kapsam:** `tests/unit/core/test_trusted_subprocess.py` ile `%100`
satır/dal kapsamı (shell=True reddi, boş komut reddi, gömülü NUL reddi,
`run`/`Popen` mutlu yolları). Faz 1'de 8 çağrı noktası
(`scripts/ci/check_ruff_debt_baseline.py`, `scripts/doctor_production_readiness.py`,
`scripts/sync_postgres_password.py`, `launcher/process.py`,
`core/doctor/__init__.py`, `core/multimodal.py`, `main.py`) buraya
taşındı; kalanlar (`managers/code/*`, `web/plugins/sandbox.py`,
`web/process_lifecycle.py`, `managers/system_health.py`,
`tools/audit_imports.py`) artan risk sırasıyla sonraki fazlara bırakıldı.
