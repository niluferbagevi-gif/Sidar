from __future__ import annotations

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
    assert store.added == [
        {
            "path": str(doc),
            "title": "README.md",
            "tags": ["source:repo-docs", "brand:Sidar", "audience:Sidar operators"],
            "session_id": "global",
        }
    ]


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
