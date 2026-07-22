# Sidar environment configuration guide

Sidar intentionally keeps **`.env` as the primary local runtime configuration file**.
The installer may also create or synchronize files such as `.env.advanced`,
`.env.development`, `.env.test`, and `.env.production`, but these files are not meant
to become independent, conflicting sources of truth.

## Single-source rule

Use `.env` for values that define the local installation baseline:

- database connection pieces such as `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`
- generated runtime secrets such as `API_KEY`, `JWT_SECRET_KEY`, and `MEMORY_ENCRYPTION_KEY`
- local hardware/runtime toggles such as `USE_GPU`, `REQUIRE_GPU`, and `COMPOSE_PROFILES`
- the active profile selector, `SIDAR_ENV`

The installer synchronizes shared secrets from `.env` into existing profile files so
smoke tests, Docker services, and local tools do not drift. If a shared secret differs
between `.env` and a profile file, treat `.env` as canonical and re-run the sync step
instead of editing every file by hand:

```bash
uv run python -m scripts.sync_database_passwords --all-envs
```

## Override layers and precedence

Runtime loading is layered so day-to-day setups can stay simple while advanced/test
setups still have explicit override points. The effective order is:

1. **Process environment** — already-exported variables are preserved by default.
2. **`.env`** — primary local baseline; loaded without overriding process env.
3. **`.env.advanced`** — optional advanced defaults; loaded without overriding process env.
4. **`.env.${SIDAR_ENV}`** — profile-specific override such as `.env.development`,
   `.env.test`, or `.env.production`; loaded with override semantics after `SIDAR_ENV`
   is known.
5. **`DOTENV_FILE`** — explicit one-off override file, resolved relative to the repo,
   absolute paths, or `~`; loaded with override semantics.
6. **`SIDAR_KEYS_FILE`** — final secret overlay, defaulting to `~/.sidar_keys.env` when
   present; loaded last and must not be committed.

Set `SIDAR_SKIP_DEFAULT_DOTENV=1` only for controlled tests/tools that need to bypass
repo-local `.env`, `.env.advanced`, and `.env.${SIDAR_ENV}`. `DOTENV_FILE` and
`SIDAR_KEYS_FILE` remain available for explicit overrides.

## What each file is for

| File | Purpose | Commit? | Notes |
| --- | --- | --- | --- |
| `.env` | Primary local runtime config generated from `.env.example`. | No | Canonical for local DB credentials and generated app secrets. Personal provider API keys should live in `SIDAR_KEYS_FILE`. |
| `.env.advanced` | Optional advanced runtime knobs generated from `.env.advanced.example`. | No | Use for uncommon tuning, not duplicate baseline secrets or real provider API keys manually. |
| `.env.development` | Development-profile overrides generated from `.env.development.example`. | No | Keep only values that should differ from `.env`. |
| `.env.test` | Smoke/unit-test profile overrides generated from `.env.test.example`. | No | Real service API keys are not copied here unless explicitly opted in. |
| `.env.production` | Explicit production-only overrides created by the rotation workflow or secret manager integration; the installer never copies local/dev secrets into it. | No | Required secrets must be populated and isolated before `SIDAR_ENV=production` can be persisted. |
| `.env.*.example` | Versioned templates. | Yes | Add new keys here when a new setting is introduced. |
| `~/.sidar_keys.env` or `SIDAR_KEYS_FILE` | User-private secret overlay. | No | Preferred and default installer target for personal provider API keys. Keep mode `600` or stricter. |

## Recommended workflows

### Local development

```bash
uv sync --all-extras
./install_sidar.sh --mode=local --env=development
```

Then edit `.env` for normal local settings. Use `.env.development` only for values
that must differ when `SIDAR_ENV=development` is active.

### Tests and smoke gates

Let the installer prepare `.env.test` from `.env.test.example` and synchronize safe
shared values before smoke tests. Do not copy real provider keys into `.env.test` by
default. If a test explicitly needs real keys, opt in consciously:

```bash
SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=1 ./install_sidar.sh --with-integration
```


### Production secret rotation

Installer, lokal geliştirme ve smoke test tutarlılığı için 8 ortak secret'ı `.env`
üzerinden profil dosyalarına senkronize edebilir: `API_KEY`, `JWT_SECRET_KEY`,
`MEMORY_ENCRYPTION_KEY`, `AUTONOMY_WEBHOOK_SECRET`,
`SWARM_FEDERATION_SHARED_SECRET`, `GITHUB_WEBHOOK_SECRET`,
`GRAFANA_ADMIN_PASSWORD` ve `METRICS_TOKEN`. Bu davranış local/dev/test için
uygundur; ancak `.env.production` gerçek dağıtıma kaynak olacaksa production
öncesinde bu değerlerin tamamı dev/test/local değerlerden farklı olacak şekilde
rotate edilmelidir. Operasyon adımları için
`docs/runbooks/production-secret-rotation.md` runbook'unu uygulayın.

### One-off overrides

For temporary experiments, prefer `DOTENV_FILE` instead of editing multiple profile
files:

```bash
DOTENV_FILE=.env.local-experiment uv run python main.py
```

For personal secrets shared across checkouts, prefer `SIDAR_KEYS_FILE`:

```bash
SIDAR_KEYS_FILE=~/.sidar_keys.env ./install_sidar.sh
```

By default, `install_sidar.sh` writes real service/provider API keys only to
`SIDAR_KEYS_FILE` and leaves repo-local `.env*` files as non-secret runtime
configuration. If you need the legacy behavior for an isolated environment, opt in
explicitly:

Seeing `.env` report `0/18` filled service API keys is therefore not a failure when
`SIDAR_KEYS_FILE`/`~/.sidar_keys.env` contains the real keys. The `.env` status line
describes only repo-local materialization; the runtime loader still reads the final
secret overlay from `SIDAR_KEYS_FILE`. Keep that file outside the repository with mode
`600` or stricter, and do not copy personal provider keys into `.env` unless the
explicit materialization opt-in below is intentional.

Sidar validates this boundary before initial dotenv loading and runtime reloads.
Relative paths resolve from the repository root, so `SIDAR_KEYS_FILE=.env` and
`SIDAR_KEYS_FILE=config/keys.env` fail closed. Symlinks that ultimately resolve into
the repository are rejected as well.

```bash
SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV=1 ./install_sidar.sh
```

When this opt-in is used, `.env.test` is still protected separately and receives real
keys only with `SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=1`.

## Troubleshooting drift

- If PostgreSQL auth fails, first compare `.env` and `.env.test`/profile credentials;
  then run `uv run python -m scripts.sync_database_passwords --all-envs`.
- If runtime reports missing critical keys, inspect the dotenv load report in installer
  output; it lists which layer loaded or skipped each file.
- If a profile file accumulates many duplicated baseline values, move unchanged values
  back to `.env` and leave only true overrides in `.env.${SIDAR_ENV}`.
