import builtins
import importlib.util
import sys
import types
from pathlib import Path

from tests.test_rag_runtime_extended import _load_rag_module, _new_store


def _load_rag_module_without_bleach(module_name: str):
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 50
        RAG_CHUNK_OVERLAP = 10
        HF_TOKEN = ""
        HF_HUB_OFFLINE = False

    cfg_mod.Config = _Cfg
    prev_cfg = sys.modules.get("config")
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "bleach":
            raise ImportError("bleach missing for test")
        return real_import(name, globals, locals, fromlist, level)

    try:
        sys.modules["config"] = cfg_mod
        builtins.__import__ = _fake_import
        spec = importlib.util.spec_from_file_location(module_name, Path("core/rag.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        builtins.__import__ = real_import
        if prev_cfg is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev_cfg


def test_rag_module_bleach_importerror_fallback_cleans_html():
    mod = _load_rag_module_without_bleach("rag_no_bleach_fallback")
    assert mod._BLEACH_AVAILABLE is False
    cleaned = mod.DocumentStore._clean_html(
        '<style>hide</style><script>alert(1)</script><div>Hello&nbsp;<b>world</b> &amp; &lt;tag&gt;</div>'
    )
    assert cleaned == "Hello world & <tag>"


def test_touch_document_missing_id_and_consolidation_skip_paths(tmp_path):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    save_calls = {"count": 0}
    store._save_index = lambda: save_calls.__setitem__("count", save_calls["count"] + 1)
    store._touch_document("missing-doc")
    assert save_calls["count"] == 0

    store._index = {
        "doc-1": {
            "session_id": "s1",
            "title": "Only",
            "created_at": 1.0,
            "last_accessed_at": 1.0,
            "access_count": 0,
            "tags": [],
            "source": "file://only",
        }
    }
    skipped_few = store.consolidate_session_documents("s1", keep_recent_docs=2)
    assert skipped_few == {
        "status": "skipped",
        "session_id": "s1",
        "removed_docs": 0,
        "summary_doc_id": "",
    }

    store._index = {
        "keep": {
            "session_id": "s1",
            "title": "Keep",
            "created_at": 30.0,
            "last_accessed_at": 30.0,
            "access_count": 0,
            "tags": [],
            "source": "file://keep",
        },
        "pinned": {
            "session_id": "s1",
            "title": "Pinned",
            "created_at": 10.0,
            "last_accessed_at": 10.0,
            "access_count": 0,
            "tags": ["pinned"],
            "source": "file://pinned",
        },
        "active": {
            "session_id": "s1",
            "title": "Active",
            "created_at": 5.0,
            "last_accessed_at": 5.0,
            "access_count": 2,
            "tags": [],
            "source": "file://active",
        },
    }
    skipped_nonremovable = store.consolidate_session_documents("s1", keep_recent_docs=1)
    assert skipped_nonremovable == {
        "status": "skipped",
        "session_id": "s1",
        "removed_docs": 0,
        "summary_doc_id": "",
    }


def test_consolidate_session_documents_removes_old_digest_and_old_docs(tmp_path):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    store._index = {
        "recent": {
            "session_id": "s1",
            "title": "Recent",
            "preview": "recent-preview",
            "created_at": 50.0,
            "last_accessed_at": 50.0,
            "access_count": 0,
            "tags": [],
            "source": "file://recent",
        },
        "old-removable": {
            "session_id": "s1",
            "title": "Old",
            "preview": "old-preview",
            "created_at": 5.0,
            "last_accessed_at": 5.0,
            "access_count": 0,
            "tags": [],
            "source": "file://old",
        },
        "nightly-old": {
            "session_id": "s1",
            "title": "Digest",
            "preview": "digest-preview",
            "created_at": 1.0,
            "last_accessed_at": 1.0,
            "access_count": 0,
            "tags": ["memory-summary"],
            "source": "memory://nightly-digest/old",
        },
    }

    deleted = []
    store.delete_document = lambda doc_id, session_id="global": deleted.append((doc_id, session_id)) or f"deleted:{doc_id}"
    store._add_document_sync = lambda **kwargs: "summary-1"

    result = store.consolidate_session_documents("s1", keep_recent_docs=1)
    assert result == {
        "status": "completed",
        "session_id": "s1",
        "removed_docs": 1,
        "summary_doc_id": "summary-1",
    }
    assert ("nightly-old", "s1") in deleted
    assert ("old-removable", "s1") in deleted