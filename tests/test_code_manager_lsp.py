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
