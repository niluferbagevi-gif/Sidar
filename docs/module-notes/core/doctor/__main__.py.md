# `core/doctor/__main__.py` — `python -m core.doctor` Giriş Noktası

- **Kaynak dosya:** `core/doctor/__main__.py`
- **Not dosyası:** `docs/module-notes/core/doctor/__main__.py.md`

**Amaç:** `core/doctor/__init__.py`'deki `main()`'i çağıran, tek satırlık
standart `python -m` giriş noktası; `raise SystemExit(main())` ile process
exit code'unu doğrudan CLI çağrısına yansıtır.
