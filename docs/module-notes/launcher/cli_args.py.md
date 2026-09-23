# `launcher/cli_args.py` — Launcher Komut Satırı Argümanları

- **Kaynak dosya:** `launcher/cli_args.py`
- **Not dosyası:** `docs/module-notes/launcher/cli_args.py.md`

**Amaç:** `main.main()`'in `argparse` tanımı ve argüman doğrulamaları.

**Özellikler:**
- `build_arg_parser(*, session_filename)` — `--quick`, `--skip-wizard`,
  `--last/--use-last`, `--provider`, `--level`, `--model`, `--host`, `--port`,
  `--log`, `--capture-output`, `--child-log`, `--yes/-y`.
- `use_last_from_env()` — `SIDAR_LAUNCHER_USE_LAST` (`1/true/yes/on`).
- `validate_port_argument(parser, port)` — 1-65535 dışı veya tam sayı olmayan
  değerde `parser.error` ile çıkar.
