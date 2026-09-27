"""Tests for the living-docs stale link/path checker."""

from __future__ import annotations

import subprocess

import pytest

from scripts.ci import check_doc_links as checker


def _make_repo(tmp_path, monkeypatch, allowed=None):
    """Point the checker at an isolated repo root with its own exemption table."""
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "ALLOWED_MISSING", allowed or {})
    checker._anchors_of.cache_clear()
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "llm.py").write_text("", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("", encoding="utf-8")
    return tmp_path


def _git_init(root) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def test_tracked_files_lists_git_index(tmp_path) -> None:
    """Tracked files lists git index."""
    (tmp_path / "a.md").write_text("", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "untracked.md").write_text("", encoding="utf-8")
    _git_init(tmp_path)
    (tmp_path / "later.md").write_text("", encoding="utf-8")

    assert sorted(checker.tracked_files(tmp_path)) == ["a.md", "sub/b.py", "untracked.md"]


def test_tracked_files_requires_an_absolute_git_binary(tmp_path, monkeypatch) -> None:
    """Tracked files requires an absolute git binary."""
    monkeypatch.setattr(checker.shutil, "which", lambda name: None)
    with pytest.raises(OSError, match="git"):
        checker.tracked_files(tmp_path)

    monkeypatch.setattr(checker.shutil, "which", lambda name: "git")
    with pytest.raises(OSError, match="git"):
        checker.tracked_files(tmp_path)


def test_living_docs_skips_historical_records_and_non_markdown() -> None:
    """Living docs skips historical records and non markdown."""
    files = [
        "README.md",
        "CHANGELOG.md",
        "docs/archive/old.md",
        "docs/AUDIT_REPORT_v5.0.md",
        "reports/run.md",
        "docs/guide.md",
        "core/llm.py",
    ]

    assert checker.living_docs(files) == ["README.md", "docs/guide.md"]


def test_top_level_dirs_ignores_root_files() -> None:
    """Top level dirs ignores root files."""
    assert checker.top_level_dirs(["README.md", "core/llm.py", "docs/a/b.md"]) == {
        "core",
        "docs",
    }


def test_broken_links_resolves_relative_to_document(tmp_path, monkeypatch) -> None:
    """Broken links resolves relative to document."""
    _make_repo(tmp_path, monkeypatch)
    text = (
        "[ok](guide.md) [anchor](guide.md#bolum) [self](#top) "
        "[web](https://example.com/x.md) [mail](mailto:a@b.c) [abs](/etc/hosts) "
        "[up](../core/llm.py) [dead](gone.md#x) [deaddir](../web_ui/)"
    )

    assert checker.broken_links("docs/index.md", text) == ["gone.md#x", "../web_ui/"]


def test_broken_links_checks_inline_html_hrefs(tmp_path, monkeypatch) -> None:
    """Inline HTML hrefs (e.g. inside ``<pre>`` file trees) resolve relative to the document."""
    _make_repo(tmp_path, monkeypatch)
    text = (
        '<pre>\n<a href="guide.md">ok</a>\n<a class="x" href="../core/llm.py#L1">up</a>\n'
        '<a href="https://example.com/x.md">web</a>\n<a href="#top">self</a>\n'
        '<a href="docs/guide.md">root-relative</a>\n</pre>\n[md](gone.md)'
    )

    assert checker.broken_links("docs/index.md", text) == ["gone.md", "docs/guide.md"]


def test_heading_slug_follows_github_rules() -> None:
    """Punctuation/backticks/emoji drop out, spaces become dashes, Turkish İ keeps its dot."""
    assert checker.heading_slug("2. Veri Katmanı (core/db.py)") == "2-veri-katmanı-coredbpy"
    websocket = checker.heading_slug("3.3 WebSocket: `/ws/chat` ve **ses**")
    assert websocket == "33-websocket-wschat-ve-ses"
    assert checker.heading_slug("[Kurulum](x.md) <b>Adımları</b> 🚀") == "kurulum-adımları-"
    assert checker.heading_slug("snake_case - adı") == "snake_case---adı"
    assert checker.heading_slug("İzolasyon") == "i\u0307zolasyon"


def test_document_anchors_counts_duplicates_and_skips_code_fences() -> None:
    """Duplicate headings get -1/-2 suffixes, fenced ``#`` lines are ignored, ids count."""
    text = (
        "# Başlık\n## Başlık\n### Başlık ###\n"
        "```bash\n# yorum satırı\n```\n"
        '<a id="özel-çapa"></a>\n<a name="eski"></a>\n#etiket değil\n'
    )

    assert checker.document_anchors(text) == {
        "başlık",
        "başlık-1",
        "başlık-2",
        "özel-çapa",
        "eski",
    }


def test_broken_anchors_checks_markdown_fragments_only(tmp_path, monkeypatch) -> None:
    """Fragments into Markdown targets must exist; code/external/missing targets are skipped."""
    _make_repo(tmp_path, monkeypatch)
    (tmp_path / "docs" / "guide.md").write_text(
        '# Kurulum Adımları\n<a id="6-güvenlik-ve-izolasyon-notları"></a>\n'
        "## 6. Güvenlik ve İzolasyon Notları\n",
        encoding="utf-8",
    )
    text = (
        "# Giriş\n"
        "[ok](guide.md#kurulum-adımları) [enc](guide.md#kurulum-ad%C4%B1mlar%C4%B1) "
        "[case](guide.md#Kurulum-Adımları) [id](guide.md#6-güvenlik-ve-izolasyon-notları) "
        "[self](#giriş) [nofrag](guide.md) [empty](guide.md#) "
        "[code](../core/llm.py#L1) [web](https://example.com/a.md#x) [gone](nope.md#x) "
        "[stale](guide.md#kurulum) [selfstale](#yok)\n"
        '<a href="guide.md#eski-başlık">html</a>\n'
    )

    assert checker.broken_anchors("docs/index.md", text) == [
        "guide.md#kurulum",
        "#yok",
        "guide.md#eski-başlık",
    ]


def test_missing_paths_checks_only_repo_rooted_backticks(tmp_path, monkeypatch) -> None:
    """Missing paths checks only repo rooted backticks."""
    _make_repo(tmp_path, monkeypatch)
    used: set[tuple[str, str]] = set()
    text = (
        "`core/llm.py` `core/llm.py::LLMClient` `core/` `docs/guide.md`. "
        "`core/db.py` `tests/test_old.py` `core/gone.py`, "
        "`async/await` `plain.py` `core/*.py` `artifacts/test-summary.json` "
        "`web_ui_react/dist/`"
    )

    missing = checker.missing_paths("README.md", text, frozenset({"core", "docs"}), used)

    assert missing == ["core/db.py", "core/gone.py"]
    assert used == set()


def test_missing_paths_honours_per_document_exemptions(tmp_path, monkeypatch) -> None:
    """Missing paths honours per document exemptions."""
    _make_repo(tmp_path, monkeypatch, allowed={"README.md": frozenset({"core/db.py"})})
    used: set[tuple[str, str]] = set()
    top_dirs = frozenset({"core"})

    assert checker.missing_paths("README.md", "`core/db.py`", top_dirs, used) == []
    assert used == {("README.md", "core/db.py")}
    assert checker.missing_paths("docs/guide.md", "`core/db.py`", top_dirs, used) == ["core/db.py"]


def test_find_problems_reports_links_paths_and_stale_exemptions(tmp_path, monkeypatch) -> None:
    """Find problems reports links paths and stale exemptions."""
    _make_repo(
        tmp_path,
        monkeypatch,
        allowed={
            "README.md": frozenset({"core/db.py", "core/llm.py"}),
            "docs/removed.md": frozenset({"core/x.py"}),
        },
    )
    (tmp_path / "README.md").write_text(
        "[dead](docs/nope.md) `core/db.py` `core/rag.py`\n", encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text("`core/ancient.py`\n", encoding="utf-8")
    files = ["README.md", "CHANGELOG.md", "core/llm.py", "docs/guide.md"]

    assert checker.find_problems(files) == [
        "README.md: kırık bağlantı -> docs/nope.md",
        "README.md: var olmayan yol -> core/rag.py",
        "README.md: ALLOWED_MISSING girdisi artık gereksiz -> core/llm.py",
        "docs/removed.md: ALLOWED_MISSING girdisi artık gereksiz -> core/x.py",
    ]


def test_main_passes_on_clean_repo(tmp_path, monkeypatch, capsys) -> None:
    """Main passes on clean repo."""
    _make_repo(tmp_path, monkeypatch)
    (tmp_path / "README.md").write_text("See `core/llm.py` and [guide](docs/guide.md).\n")
    _git_init(tmp_path)

    assert checker.main([]) == 0
    assert "güncel" in capsys.readouterr().out


def test_main_fails_and_lists_stale_references(tmp_path, monkeypatch, capsys) -> None:
    """Main fails and lists stale references."""
    _make_repo(tmp_path, monkeypatch)
    (tmp_path / "README.md").write_text("`core/db.py`\n", encoding="utf-8")
    _git_init(tmp_path)

    assert checker.main([]) == 1
    err = capsys.readouterr().err
    assert "README.md: var olmayan yol -> core/db.py" in err
    assert "ALLOWED_MISSING" in err


def test_main_reports_git_failure(tmp_path, monkeypatch, capsys) -> None:
    """Main reports git failure."""
    monkeypatch.setattr(checker, "ROOT", tmp_path)

    def _boom(root):
        raise subprocess.CalledProcessError(128, ["git", "ls-files"])

    monkeypatch.setattr(checker, "tracked_files", _boom)

    assert checker.main([]) == 2
    assert "git ls-files" in capsys.readouterr().err


@pytest.mark.skipif(
    not (checker.ROOT / ".git").exists(), reason="requires a git checkout of the repo"
)
def test_committed_docs_have_no_stale_references() -> None:
    """Committed docs have no stale references."""
    assert checker.find_problems(checker.tracked_files(checker.ROOT)) == []
