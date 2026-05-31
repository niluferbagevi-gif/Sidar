# Incremental modularization map

Sidar keeps backwards-compatible facades while large modules are split into smaller,
independently testable responsibilities. Callers should prefer the new focused import
paths for new code; legacy imports remain supported during the transition.

## RAG

`core.rag` remains the public document-store facade. The first extraction moves source
and knowledge graph primitives into `core.rag.graph`, exposes `GraphIndex` through
`core.rag.indexer`, keeps query planning values in `core.rag.query`, and provides lazy
embedding compatibility helpers through `core.rag.embeddings_wrapper`.

## Database

`core.db` is currently a module file, so a `core/db/` package cannot be introduced in
the same migration without changing Python import resolution and moving the facade.
The first safe extraction therefore uses `core.db_components`: dialect normalization
lives in `dialect.py`, while Alembic execution lives in `migrations.py`. Pool and async
pool extraction should follow in this transition namespace before a dedicated facade
migration converts `core.db` into a package.

## Code manager

`managers.code_manager.CodeManager` remains the compatibility facade. New focused
helpers live under `managers.code`: pytest command parsing in `pytest_parser.py`, LSP
framing and URI handling in `lsp.py`, platform-specific LSP executable discovery in
`platform.py`, and sanitized argv construction in `runner.py`.

## Follow-up slices

1. Extract RAG indexing orchestration and document-store query execution after their
   backend injection points have stable import-contract tests.
2. Move PostgreSQL pool lifecycle and async pool adapters into `core.db_components`
   before converting `core.db` from a file facade to a package facade.
3. Move the remaining `CodeManager` subprocess orchestration behind `managers.code.runner`.
4. Split `agent.sidar_agent` only after its self-heal, nightly workflow, and distributed
   lock boundaries are covered by explicit facade tests.
