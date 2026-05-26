from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import seed_rag


class FakeStore:
    def __init__(self, existing: list[dict[str, str]] | None = None) -> None:
        self.index = list(existing or [])
        self.deleted: list[tuple[str, str]] = []
        self.added: list[dict[str, object]] = []

    def get_index_info(self, session_id: str | None = None) -> list[dict[str, str]]:
        return [
            item
            for item in self.index
            if session_id is None or item.get("session_id", "global") == session_id
        ]

    def delete_document(self, doc_id: str, session_id: str = "global") -> str:
        self.deleted.append((doc_id, session_id))
        self.index = [item for item in self.index if item.get("id") != doc_id]
        return f"deleted {doc_id}"

    def add_document_from_file(
        self,
        path: str,
        title: str = "",
        tags: list[str] | None = None,
        session_id: str = "global",
    ) -> tuple[bool, str]:
        self.added.append(
            {"path": path, "title": title, "tags": tags or [], "session_id": session_id}
        )
        return True, f"added {title}"

    def close(self) -> None:
        return None


def test_discover_seed_files_filters_to_repo_text_and_code_files(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    keep = docs / "keep.md"
    keep.write_text("# Keep", encoding="utf-8")
    code = docs / "agent.py"
    code.write_text("print('Sidar')", encoding="utf-8")
    shell = docs / "run.sh"
    shell.write_text("#!/usr/bin/env bash\necho Sidar", encoding="utf-8")
    large = docs / "large.md"
    large.write_text("x" * 40, encoding="utf-8")
    ignored = docs / "image.png"
    ignored.write_bytes(b"png")

    files = seed_rag.discover_seed_files(["docs/*"], base_dir=tmp_path, max_bytes=30)

    assert files == [code.resolve(), keep.resolve(), shell.resolve()]


def test_discover_seed_files_rejects_repo_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(seed_rag.SeedError):
        seed_rag.discover_seed_files(["../outside.md"], base_dir=tmp_path)


def test_seed_files_replaces_existing_source_and_tags_repo_docs(tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text("Brand: Sidar", encoding="utf-8")
    source = f"file://{doc}"
    store = FakeStore(existing=[{"id": "old", "source": source, "session_id": "global"}])

    summary = seed_rag.seed_files(store, [doc], session_id="global", base_dir=tmp_path)

    assert summary["added_count"] == 1
    assert summary["deleted"] == ["old"]
    assert store.deleted == [("old", "global")]
    assert len(store.added) == 1
    assert store.added[0]["path"] == str(doc)
    assert store.added[0]["title"] == "README.md"
    assert store.added[0]["session_id"] == "global"
    assert "source:repo-docs" in store.added[0]["tags"]
    assert "brand:Sidar" in store.added[0]["tags"]
    assert "audience:Sidar operators" in store.added[0]["tags"]


def test_seed_files_can_skip_existing_source_when_append_mode(tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text("content", encoding="utf-8")
    store = FakeStore(existing=[{"id": "old", "source": f"file://{doc}", "session_id": "s1"}])

    summary = seed_rag.seed_files(
        store,
        [doc],
        session_id="s1",
        replace_existing=False,
        base_dir=tmp_path,
    )

    assert summary["added_count"] == 0
    assert summary["skipped"] == [{"path": "README.md", "reason": "already_indexed"}]
    assert store.added == []


def test_default_seed_patterns_include_curated_code_context() -> None:
    assert "core/rag.py" in seed_rag.DEFAULT_INCLUDE_PATTERNS
    assert "agent/sidar_agent.py" in seed_rag.DEFAULT_INCLUDE_PATTERNS
    assert "run_tests.sh" in seed_rag.DEFAULT_INCLUDE_PATTERNS
    assert ".py" in seed_rag.TEXT_EXTENSIONS
    assert ".sh" in seed_rag.TEXT_EXTENSIONS


def test_build_store_routes_import_time_notices_to_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import builtins
    from types import SimpleNamespace

    class FakeDocumentStore:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args
            self.kwargs = kwargs

        def close(self) -> None:
            return None

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "config":
            print("config stdout notice")
            return SimpleNamespace(
                Config=SimpleNamespace(HF_HUB_OFFLINE="1", HF_USE_LOCAL_CACHE_ONLY="yes")
            )
        if name == "core.rag":
            print("rag stdout notice")
            return SimpleNamespace(DocumentStore=FakeDocumentStore)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    store = seed_rag._build_store(tmp_path, initialize_vector=False)

    captured = capsys.readouterr()
    assert isinstance(store, FakeDocumentStore)
    assert store.kwargs["cfg"].HF_HUB_OFFLINE is True
    assert store.kwargs["cfg"].HF_USE_LOCAL_CACHE_ONLY is True
    assert captured.out == ""
    assert "config stdout notice" in captured.err
    assert "rag stdout notice" in captured.err


def test_seed_rag_boolish_normalizes_external_aliases() -> None:
    assert seed_rag._boolish("1") is True
    assert seed_rag._boolish("yes") is True
    assert seed_rag._boolish("0") is False
    assert seed_rag._boolish("off") is False
    with pytest.raises(seed_rag.SeedError):
        seed_rag._boolish("maybe")


def test_seed_rag_summary_only_outputs_counts_without_verbose_lists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = tmp_path / "README.md"
    doc.write_text("Sidar", encoding="utf-8")
    monkeypatch.setattr(seed_rag, "discover_seed_files", lambda *_args, **_kwargs: [doc])

    def fake_seed_files(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "session_id": "global",
            "added_count": 2,
            "skipped_count": 1,
            "deleted_count": 1,
            "added": [{"path": "a.md"}, {"path": "b.md"}],
            "skipped": [{"path": "c.md"}],
            "deleted": ["old"],
        }

    monkeypatch.setattr(seed_rag, "seed_files", fake_seed_files)

    assert seed_rag.main(["--dry-run", "--summary-only"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["added_count"] == 2
    assert output["skipped_count"] == 1


def test_wait_for_pgvector_readiness_retries_until_extension_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeConn:
        def __init__(self, state: dict[str, int]) -> None:
            self._state = state

        def execute(self, _query: object) -> object:
            self._state["calls"] += 1
            ready = self._state["calls"] >= 3
            return type("_Result", (), {"scalar": lambda self: ready})()

        def __enter__(self) -> _FakeConn:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class _FakeEngine:
        def __init__(self, state: dict[str, int]) -> None:
            self._state = state

        def connect(self) -> _FakeConn:
            return _FakeConn(self._state)

        def dispose(self) -> None:
            return None

    state = {"calls": 0}
    fake_config = type(
        "_Cfg",
        (),
        {
            "RAG_VECTOR_BACKEND": "pgvector",
            "DATABASE_URL": "postgresql+asyncpg://sidar:pw@postgres:5432/sidar",
        },
    )
    monkeypatch.setitem(sys.modules, "config", type("_Mod", (), {"Config": fake_config})())
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "sqlalchemy",
        SimpleNamespace(create_engine=lambda *_a, **_k: _FakeEngine(state), text=lambda q: q),
    )
    monkeypatch.setenv("SEED_RAG_PGVECTOR_MAX_RETRIES", "5")
    monkeypatch.setenv("SEED_RAG_PGVECTOR_RETRY_DELAY_SEC", "0.1")
    sleep_calls: list[float] = []
    monkeypatch.setattr(seed_rag.time, "sleep", lambda s: sleep_calls.append(s))

    seed_rag._wait_for_pgvector_readiness()

    assert state["calls"] == 3
    assert sleep_calls == [0.1, 0.1]
