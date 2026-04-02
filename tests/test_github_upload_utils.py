import github_upload


def test_url_and_path_helpers():
    assert github_upload._is_valid_repo_url("https://github.com/org/repo")
    assert github_upload._is_valid_repo_url("git@github.com:org/repo.git")
    assert not github_upload._is_valid_repo_url("https://gitlab.com/org/repo")

    assert github_upload._normalize_path("./foo//bar") == "foo/bar"
    assert github_upload._normalize_path("/a/b") == "a/b"


def test_forbidden_path_and_file_read(tmp_path):
    assert github_upload.is_forbidden_path(".env")
    assert github_upload.is_forbidden_path("logs/app.log")
    assert not github_upload.is_forbidden_path("docs/readme.md")

    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello", encoding="utf-8")
    assert github_upload.get_file_content(str(file_path)) == "hello"


def test_collect_safe_files_and_stage(monkeypatch):
    deleted = ["gone.txt"]

    def _fake_run(args, show_output=True):
        if args[:3] == ["git", "ls-files", "-co"]:
            return True, "ok.py\nlogs/secret.txt\ngone.txt\n"
        if args[:2] == ["git", "add"]:
            return True, ""
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)
    monkeypatch.setattr(github_upload.os.path, "isdir", lambda path: False)
    monkeypatch.setattr(github_upload, "get_file_content", lambda path: "print('ok')")

    safe, blocked = github_upload.collect_safe_files(deleted_files_list=deleted)
    assert safe == ["ok.py"]
    assert blocked == ["logs/secret.txt"]

    ok, _ = github_upload.stage_files(["ok.py"])
    assert ok
