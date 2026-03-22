import subprocess
from pathlib import Path

import pytest

from tests.test_code_manager_runtime import CM_MOD, FULL, DummySecurity


def _make_manager(monkeypatch, tmp_path):
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    manager = CM_MOD.CodeManager(DummySecurity(tmp_path, level=FULL), tmp_path)
    manager.docker_available = False
    return manager


def test_lsp_go_to_definition_formats_result(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "sample.py"
    target.write_text("value = 1\nprint(value)\n", encoding="utf-8")

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_kwargs: [
            {
                "id": 2,
                "result": [
                    {
                        "uri": CM_MOD._path_to_file_uri(target),
                        "range": {"start": {"line": 0, "character": 0}},
                    }
                ],
            }
        ],
    )

    ok, output = manager.lsp_go_to_definition(str(target), 1, 6)

    assert ok is True
    assert "sample.py" in output
    assert "satır 1" in output


def test_lsp_rename_symbol_dry_run_and_apply(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "rename_me.py"
    target.write_text("old_name = 1\nprint(old_name)\n", encoding="utf-8")

    rename_result = {
        "changes": {
            CM_MOD._path_to_file_uri(target): [
                {
                    "range": {
                        "start": {"line": 1, "character": 6},
                        "end": {"line": 1, "character": 14},
                    },
                    "newText": "new_name",
                },
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 8},
                    },
                    "newText": "new_name",
                },
            ]
        }
    }

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_kwargs: [{"id": 2, "result": rename_result}],
    )

    ok, dry_run = manager.lsp_rename_symbol(str(target), 0, 1, "new_name", apply=False)
    assert ok is True
    assert "dry-run hazır" in dry_run

    ok, applied = manager.lsp_rename_symbol(str(target), 0, 1, "new_name", apply=True)
    assert ok is True
    assert "Değişen dosya sayısı: 1" in applied
    assert target.read_text(encoding="utf-8") == "new_name = 1\nprint(new_name)\n"


def test_lsp_workspace_diagnostics_formats_publish_notifications(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "diag.py"
    target.write_text("print(unknown_name)\n", encoding="utf-8")

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_kwargs: [
            {
                "method": "textDocument/publishDiagnostics",
                "params": {
                    "uri": CM_MOD._path_to_file_uri(target),
                    "diagnostics": [
                        {
                            "message": "\"unknown_name\" is not defined",
                            "severity": 1,
                            "range": {"start": {"line": 0, "character": 6}},
                        }
                    ],
                },
            }
        ],
    )

    ok, output = manager.lsp_workspace_diagnostics([str(target)])

    assert ok is True
    assert "diag.py" in output
    assert "unknown_name" in output


def test_lsp_semantic_audit_returns_structured_summary(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "diag.py"
    target.write_text("print(unknown_name)\n", encoding="utf-8")

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_kwargs: [
            {
                "method": "textDocument/publishDiagnostics",
                "params": {
                    "uri": CM_MOD._path_to_file_uri(target),
                    "diagnostics": [
                        {
                            "message": "\"unknown_name\" is not defined",
                            "severity": 1,
                            "range": {"start": {"line": 0, "character": 6}},
                        }
                    ],
                },
            }
        ],
    )

    ok, audit = manager.lsp_semantic_audit([str(target)])

    assert ok is True
    assert audit["decision"] == "REJECT"
    assert audit["risk"] == "yüksek"
    assert audit["counts"] == {1: 1}
    assert audit["issues"][0]["path"].endswith("diag.py")


def test_decode_lsp_stream_raises_protocol_error_on_truncated_body():
    payload = b'Content-Length: 20\r\n\r\n{"jsonrpc":"2.0"}'

    with pytest.raises(CM_MOD._LSPProtocolError, match="Eksik LSP mesaj gövdesi"):
        CM_MOD._decode_lsp_stream(payload)


def test_run_lsp_sequence_handles_timeout_and_server_failure(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "sample.py"
    extra = tmp_path / "helper.py"
    target.write_text("value = 1\n", encoding="utf-8")
    extra.write_text("helper = 2\n", encoding="utf-8")

    captured = {}

    class _TimeoutProc:
        returncode = None

        def communicate(self, payload, timeout):
            captured["payload"] = payload
            captured["timeout"] = timeout
            raise subprocess.TimeoutExpired(cmd="pyright-langserver", timeout=timeout)

        def kill(self):
            captured["killed"] = True

    monkeypatch.setattr(CM_MOD.subprocess, "Popen", lambda *args, **kwargs: _TimeoutProc())

    with pytest.raises(RuntimeError, match="zaman aşımına uğradı"):
        manager._run_lsp_sequence(
            primary_path=target,
            request_method="textDocument/definition",
            request_params=manager._position_params(target, 0, 0),
            extra_open_files=[extra, extra, tmp_path / "missing.py"],
        )

    assert captured["timeout"] == manager.lsp_timeout_seconds
    decoded_messages = CM_MOD._decode_lsp_stream(captured["payload"])
    did_open_uris = [
        item["params"]["textDocument"]["uri"]
        for item in decoded_messages
        if item.get("method") == "textDocument/didOpen"
    ]
    assert did_open_uris == [CM_MOD._path_to_file_uri(target), CM_MOD._path_to_file_uri(extra)]
    assert captured["killed"] is True

    class _FailingProc:
        returncode = 9

        def communicate(self, payload, timeout):
            return b"", b"language server crashed"

    monkeypatch.setattr(CM_MOD.subprocess, "Popen", lambda *args, **kwargs: _FailingProc())

    with pytest.raises(RuntimeError, match="language server crashed"):
        manager._run_lsp_sequence(primary_path=target, request_method=None)


def test_run_lsp_sequence_skips_existing_extra_files_with_unsupported_language(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "sample.py"
    helper = tmp_path / "helper.py"
    unsupported = tmp_path / "notes.md"
    target.write_text("value = 1\n", encoding="utf-8")
    helper.write_text("helper = 2\n", encoding="utf-8")
    unsupported.write_text("# ignored by lsp\n", encoding="utf-8")

    captured = {}

    class _Proc:
        returncode = 0

        def communicate(self, payload, timeout):
            captured["payload"] = payload
            captured["timeout"] = timeout
            return b"", b""

    monkeypatch.setattr(CM_MOD.subprocess, "Popen", lambda *args, **kwargs: _Proc())

    messages = manager._run_lsp_sequence(
        primary_path=target,
        request_method=None,
        extra_open_files=[helper, unsupported],
    )

    assert messages == []
    decoded_messages = CM_MOD._decode_lsp_stream(captured["payload"])
    did_open_uris = [
        item["params"]["textDocument"]["uri"]
        for item in decoded_messages
        if item.get("method") == "textDocument/didOpen"
    ]
    assert did_open_uris == [CM_MOD._path_to_file_uri(target), CM_MOD._path_to_file_uri(helper)]
    assert CM_MOD._path_to_file_uri(unsupported) not in did_open_uris
    assert captured["timeout"] == manager.lsp_timeout_seconds

def test_run_lsp_sequence_propagates_protocol_error_from_stdout(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "sample.py"
    target.write_text("value = 1\n", encoding="utf-8")

    class _Proc:
        returncode = 0

        def communicate(self, payload, timeout):
            return b'Content-Length: 25\r\n\r\n{"jsonrpc":"2.0","id":2}', b""

    monkeypatch.setattr(CM_MOD.subprocess, "Popen", lambda *args, **kwargs: _Proc())

    with pytest.raises(CM_MOD._LSPProtocolError, match="Eksik LSP mesaj gövdesi"):
        manager._run_lsp_sequence(primary_path=target, request_method="textDocument/definition")


def test_lsp_find_references_reports_protocol_errors(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "sample.py"
    target.write_text("value = 1\nprint(value)\n", encoding="utf-8")

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_kwargs: (_ for _ in ()).throw(CM_MOD._LSPProtocolError("broken stream")),
    )

    ok, output = manager.lsp_find_references(str(target), 1, 6)

    assert ok is False
    assert "broken stream" in output


def test_apply_workspace_edit_rejects_when_security_cannot_write(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "rename_me.py"
    target.write_text("old_name = 1\n", encoding="utf-8")
    manager.security._can_write = False

    ok, output = manager._apply_workspace_edit(
        {
            "changes": {
                CM_MOD._path_to_file_uri(target): [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 8},
                        },
                        "newText": "new_name",
                    }
                ]
            }
        }
    )

    assert ok is False
    assert "LSP rename yazma yetkisi yok" in output


def test_summarize_lsp_diagnostic_entries_covers_warning_info_and_clean_states():
    warning = CM_MOD.CodeManager._summarize_lsp_diagnostic_entries([{"severity": 2}, {"severity": "oops"}])
    assert warning["status"] == "issues-found"
    assert warning["risk"] == "orta"
    assert warning["decision"] == "APPROVE"
    assert warning["counts"] == {2: 1, 0: 1}

    info_only = CM_MOD.CodeManager._summarize_lsp_diagnostic_entries([{"severity": 3}, {"severity": 4}])
    assert info_only["status"] == "info-only"
    assert info_only["risk"] == "düşük"

    clean = CM_MOD.CodeManager._summarize_lsp_diagnostic_entries([])
    assert clean["status"] == "clean"
    assert clean["summary"] == "LSP diagnostics temiz."


def test_code_manager_lsp_helper_edge_cases(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    sample = tmp_path / "pkg" / "sample.py"
    sample.parent.mkdir()
    sample.write_text("value = 1\n", encoding="utf-8")

    normalized = manager._normalize_lsp_path("pkg/sample.py")
    assert normalized == sample.resolve()

    manager.enable_lsp = False
    with pytest.raises(RuntimeError, match="ENABLE_LSP"):
        manager._run_lsp_sequence(primary_path=sample, request_method=None)

    manager.enable_lsp = True
    unsupported = tmp_path / "notes.md"
    unsupported.write_text("# demo\n", encoding="utf-8")
    with pytest.raises(ValueError, match="desteklenmeyen dosya türü"):
        manager._run_lsp_sequence(primary_path=unsupported, request_method=None)

    with pytest.raises(RuntimeError, match="server exploded"):
        manager._extract_lsp_result([{"id": 2, "error": "server exploded"}])

    assert manager._format_lsp_locations([], limit=5) == "Sonuç bulunamadı."
    formatted = manager._format_lsp_locations(
        [
            {
                "targetUri": CM_MOD._path_to_file_uri(sample),
                "targetSelectionRange": {"start": {"line": 0, "character": 0}},
            },
            {
                "uri": CM_MOD._path_to_file_uri(sample),
                "range": {"start": {"line": 1, "character": 2}},
            },
        ],
        limit=1,
    )
    assert "sample.py" in formatted
    assert "... ve 1 ek sonuç daha." in formatted


def test_code_manager_lsp_definition_references_and_rename_failures(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "demo.py"
    target.write_text("value = 1\nprint(value)\n", encoding="utf-8")

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("definition down")),
    )
    ok, output = manager.lsp_go_to_definition(str(target), 1, 6)
    assert ok is False
    assert "definition down" in output

    manager.lsp_max_references = 1
    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_kwargs: [
            {
                "id": 2,
                "result": [
                    {
                        "targetUri": CM_MOD._path_to_file_uri(target),
                        "targetSelectionRange": {"start": {"line": 0, "character": 0}},
                    },
                    {
                        "uri": CM_MOD._path_to_file_uri(target),
                        "range": {"start": {"line": 1, "character": 6}},
                    },
                ],
            }
        ],
    )
    ok, refs = manager.lsp_find_references(str(target), 1, 6)
    assert ok is True
    assert "demo.py" in refs
    assert "... ve 1 ek sonuç daha." in refs

    ok, msg = manager.lsp_rename_symbol(str(target), 0, 0, "   ", apply=False)
    assert ok is False
    assert "boş olamaz" in msg

    monkeypatch.setattr(manager, "_run_lsp_sequence", lambda **_kwargs: [{"id": 2, "result": None}])
    ok, msg = manager.lsp_rename_symbol(str(target), 0, 0, "new_name", apply=False)
    assert ok is False
    assert "değişiklik üretmedi" in msg

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("rename boom")),
    )
    ok, msg = manager.lsp_rename_symbol(str(target), 0, 0, "new_name", apply=False)
    assert ok is False
    assert "rename boom" in msg


def test_apply_workspace_edit_raises_when_target_file_is_missing(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    missing = tmp_path / "missing.py"

    edit = {
        "changes": {
            CM_MOD._path_to_file_uri(missing): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 0},
                    },
                    "newText": "print('x')\n",
                }
            ]
        }
    }

    with pytest.raises(FileNotFoundError):
        manager._apply_workspace_edit(edit)


def test_code_manager_workspace_edit_and_semantic_audit_edge_cases(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    target = tmp_path / "rename_me.py"
    target.write_text("old_name = 1\n", encoding="utf-8")

    ok, output = manager._apply_workspace_edit({})
    assert ok is False
    assert output == "Workspace edit boş döndü."

    captured = []

    def _write_file(path, content, validate=True):
        captured.append((path, content, validate))
        return False, "disk is read-only"

    monkeypatch.setattr(manager, "write_file", _write_file)
    edit = {
        "documentChanges": [
            {
                "textDocument": {"uri": CM_MOD._path_to_file_uri(target)},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 8},
                        },
                        "newText": "new_name",
                    }
                ],
            }
        ]
    }
    ok, output = manager._apply_workspace_edit(edit)
    assert ok is False
    assert output == "disk is read-only"
    assert captured and captured[0][0].endswith("rename_me.py")

    empty_mgr = _make_manager(monkeypatch, tmp_path / "empty")
    ok, audit = empty_mgr.lsp_semantic_audit([])
    assert ok is False
    assert audit["status"] == "no-targets"
    assert audit["summary"] == "LSP tanılaması için uygun dosya bulunamadı."

    diag_mgr = _make_manager(monkeypatch, tmp_path)
    monkeypatch.setattr(diag_mgr, "_run_lsp_sequence", lambda **_kwargs: [{"id": 999, "result": None}])
    ok, audit = diag_mgr.lsp_semantic_audit([str(target)])
    assert ok is True
    assert audit["status"] == "no-signal"
    assert audit["summary"] == "LSP diagnostics bildirimi dönmedi."