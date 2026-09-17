# `run_tests.sh` gate modules

`run_tests.sh` is the public entry point and owns argument parsing, stage selection,
gate ordering, and the aggregate exit code. Gate implementations are sourced from
focused modules in this directory:

- `environment_helpers.sh`: Python/uv bootstrap, test environment, pre-commit, and coverage-ratchet preflight helpers.
- `production_readiness_helpers.sh`: strict production-readiness request and system dependency validation.
- `backend_helpers.sh`: static analysis, security, benchmark tooling, runtime dependency, and Docker image preparation.
- `service_helpers.sh`: Docker Compose service lifecycle, PostgreSQL test database preparation, and Ollama model synchronization.
- `bats_helpers.sh`: local BATS dependency discovery and shell-test execution.
- `benchmark_helpers.sh`, `coverage_helpers.sh`, and `frontend_helpers.sh`: their named quality-gate implementations.
- `summary_helpers.sh`: backend failure aggregation, artifact opening, machine-readable summary generation, and release-scope messaging.

These files are libraries, not standalone commands. They intentionally read and
update variables owned by `run_tests.sh`. Add new cross-cutting gate logic to the
matching module and keep the root script limited to orchestration.
