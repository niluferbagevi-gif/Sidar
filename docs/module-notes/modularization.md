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

`core.db` is now a package facade (`core/db/__init__.py`) after the Phase 1 package
conversion. Legacy `from core.db import ...` imports remain supported while new code
can target domain boundaries such as `core.db.auth`, `core.db.coverage`,
`core.db.marketing`, `core.db.session`, and `core.db.models`. The existing
`core.db_components` transition namespace still owns low-level dialect and migration
helpers until pool/repository code is moved in later slices.

## Code manager

`managers.code_manager.CodeManager` remains the compatibility facade. New focused
helpers live under `managers.code`: pytest command parsing in `pytest_parser.py`, LSP
framing and URI handling in `lsp.py`, platform-specific LSP executable discovery in
`platform.py`, and sanitized argv construction in `runner.py`.

## Follow-up slices

1. Move DB repository/pool lifecycle code from `core/db/__init__.py` into the new
   domain modules after their facade import contracts are stable.
2. Extract RAG indexing orchestration and document-store query execution after their
   backend injection points have stable import-contract tests.
3. Move the remaining `CodeManager` subprocess orchestration behind `managers.code.runner`.
4. Continue splitting `agent.sidar_agent` now that self-heal execution has an
   `agent.self_heal.executor` boundary.
