import asyncio
import sys
import types

import pytest


def _ensure_httpx_stub() -> None:
    if "httpx" not in sys.modules:
        httpx_stub = types.SimpleNamespace(AsyncClient=None)
        sys.modules["httpx"] = httpx_stub


_ensure_httpx_stub()

from managers.jira_manager import JiraManager


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"x", text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.content = content
        self.text = text

    def json(self):
        return self._json_data


class _FakeClient:
    def __init__(self, response=None, exc=None, captured=None, **kwargs):
        self._response = response
        self._exc = exc
        self._captured = captured if captured is not None else {}
        self._captured["init_kwargs"] = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method, url, **kwargs):
        self._captured["request"] = {"method": method, "url": url, "kwargs": kwargs}
        if self._exc is not None:
            raise self._exc
        return self._response


def _run(coro):
    return asyncio.run(coro)


def test_init_client_requires_url_and_token():
    mgr = JiraManager(url="", token="")
    assert mgr.is_available() is False


def test_init_client_uses_basic_auth_when_email_provided():
    mgr = JiraManager(
        url="https://example.atlassian.net/", token=" token ", email=" user@example.com "
    )

    assert mgr.is_available() is True
    assert mgr.url == "https://example.atlassian.net"
    assert mgr.token == "token"
    assert mgr.email == "user@example.com"
    assert mgr._auth == ("user@example.com", "token")
    assert "Authorization" not in mgr._headers


def test_init_client_uses_bearer_without_email():
    mgr = JiraManager(url="https://jira.local", token="abc123")

    assert mgr.is_available() is True
    assert mgr._auth is None
    assert mgr._headers["Authorization"] == "Bearer abc123"


def test_request_returns_unavailable_when_not_configured():
    mgr = JiraManager()

    ok, data, err = _run(mgr._request("GET", "issue/PROJ-1"))

    assert ok is False
    assert data is None
    assert err == "Jira bağlantısı mevcut değil"


def test_request_success_with_json(monkeypatch):
    captured = {}

    def _factory(**kwargs):
        return _FakeClient(
            response=_FakeResponse(status_code=200, json_data={"id": "10001"}, content=b"{"),
            captured=captured,
            **kwargs,
        )

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _factory)
    mgr = JiraManager(url="https://jira.local", token="abc")

    ok, data, err = _run(mgr._request("GET", "/issue/PROJ-1", params={"x": 1}))

    assert ok is True
    assert data == {"id": "10001"}
    assert err == ""
    assert captured["request"]["method"] == "GET"
    assert captured["request"]["url"] == "https://jira.local/rest/api/3/issue/PROJ-1"
    assert captured["request"]["kwargs"] == {"params": {"x": 1}}


def test_request_success_without_content(monkeypatch):
    def _factory(**kwargs):
        return _FakeClient(
            response=_FakeResponse(status_code=204, json_data=None, content=b""), **kwargs
        )

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _factory)
    mgr = JiraManager(url="https://jira.local", token="abc")

    ok, data, err = _run(mgr._request("DELETE", "issue/PROJ-1"))

    assert ok is True
    assert data == {}
    assert err == ""


def test_request_handles_http_error(monkeypatch):
    long_text = "x" * 500

    def _factory(**kwargs):
        return _FakeClient(
            response=_FakeResponse(status_code=404, text=long_text, content=b"x"), **kwargs
        )

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _factory)
    mgr = JiraManager(url="https://jira.local", token="abc")

    ok, data, err = _run(mgr._request("GET", "issue/PROJ-404"))

    assert ok is False
    assert data is None
    assert err.startswith("HTTP 404: ")
    assert len(err) == len("HTTP 404: ") + 300


def test_request_handles_exception(monkeypatch):
    def _factory(**kwargs):
        return _FakeClient(exc=RuntimeError("boom"), **kwargs)

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _factory)
    mgr = JiraManager(url="https://jira.local", token="abc")

    ok, data, err = _run(mgr._request("GET", "search"))

    assert ok is False
    assert data is None
    assert err == "boom"


def test_create_issue_requires_project_key():
    mgr = JiraManager(url="https://jira.local", token="abc")

    ok, data, err = _run(mgr.create_issue(summary="Test"))

    assert ok is False
    assert data == {}
    assert err == "Proje anahtarı belirtilmedi"


def test_create_issue_builds_payload(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc", default_project="DEF")
    captured = {}

    async def _fake_request(method, endpoint, **kwargs):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["kwargs"] = kwargs
        return True, {"key": "DEF-1"}, ""

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, data, err = _run(
        mgr.create_issue(
            summary="Bug title",
            issue_type="Bug",
            description="Desc",
            priority="High",
            labels=["backend", "urgent"],
            assignee_account_id="acc-1",
        )
    )

    assert ok is True
    assert data == {"key": "DEF-1"}
    assert err == ""
    fields = captured["kwargs"]["json"]["fields"]
    assert captured["method"] == "POST"
    assert captured["endpoint"] == "issue"
    assert fields["project"] == {"key": "DEF"}
    assert fields["summary"] == "Bug title"
    assert fields["issuetype"] == {"name": "Bug"}
    assert fields["priority"] == {"name": "High"}
    assert fields["labels"] == ["backend", "urgent"]
    assert fields["assignee"] == {"accountId": "acc-1"}
    assert fields["description"]["content"][0]["content"][0]["text"] == "Desc"


def test_create_issue_returns_empty_dict_when_no_data(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc", default_project="DEF")

    async def _fake_request(*args, **kwargs):
        return True, None, ""

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, data, err = _run(mgr.create_issue(summary="Task"))

    assert ok is True
    assert data == {}
    assert err == ""


def test_get_issue_returns_empty_dict_on_none(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")

    async def _fake_request(*args, **kwargs):
        return True, None, ""

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, data, err = _run(mgr.get_issue("PROJ-1"))

    assert ok is True
    assert data == {}
    assert err == ""


def test_update_issue(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")
    captured = {}

    async def _fake_request(method, endpoint, **kwargs):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["kwargs"] = kwargs
        return True, None, ""

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, err = _run(mgr.update_issue("PROJ-1", {"summary": "New"}))

    assert ok is True
    assert err == ""
    assert captured == {
        "method": "PUT",
        "endpoint": "issue/PROJ-1",
        "kwargs": {"json": {"fields": {"summary": "New"}}},
    }


def test_transition_issue_fails_when_transition_list_request_fails(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")

    async def _fake_request(*args, **kwargs):
        return False, None, "bad request"

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, err = _run(mgr.transition_issue("PROJ-1", "Done"))

    assert ok is False
    assert err == "bad request"


def test_transition_issue_fails_when_transition_not_found(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")

    async def _fake_request(method, endpoint, **kwargs):
        if endpoint.endswith("/transitions") and method == "GET":
            return True, {"transitions": [{"id": "10", "name": "To Do"}]}, ""
        return pytest.fail("Unexpected second request")

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, err = _run(mgr.transition_issue("PROJ-1", "Done"))

    assert ok is False
    assert "Geçiş bulunamadı" in err
    assert "To Do" in err
    with pytest.raises(Exception, match="Unexpected"):
        _run(_fake_request("POST", "issue/PROJ-1/transitions"))


def test_ensure_httpx_stub_adds_stub_when_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "httpx", raising=False)
    _ensure_httpx_stub()
    assert "httpx" in sys.modules


def test_transition_issue_success_with_case_insensitive_match(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")
    calls = []

    async def _fake_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if method == "GET":
            return True, {"transitions": [{"id": "31", "name": "In Progress"}]}, ""
        return True, None, ""

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, err = _run(mgr.transition_issue("PROJ-1", "in progress"))

    assert ok is True
    assert err == ""
    assert calls[1] == (
        "POST",
        "issue/PROJ-1/transitions",
        {"json": {"transition": {"id": "31"}}},
    )


def test_add_comment(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")
    captured = {}

    async def _fake_request(method, endpoint, **kwargs):
        captured.update({"method": method, "endpoint": endpoint, "kwargs": kwargs})
        return True, {"id": "c1"}, ""

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, data, err = _run(mgr.add_comment("PROJ-1", "Merhaba"))

    assert ok is True
    assert data == {"id": "c1"}
    assert err == ""
    assert captured["method"] == "POST"
    assert captured["endpoint"] == "issue/PROJ-1/comment"
    assert captured["kwargs"]["json"]["body"]["content"][0]["content"][0]["text"] == "Merhaba"


def test_add_comment_returns_empty_dict_when_data_none(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")

    async def _fake_request(*args, **kwargs):
        return True, None, ""

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, data, err = _run(mgr.add_comment("PROJ-1", "Merhaba"))

    assert ok is True
    assert data == {}
    assert err == ""


def test_search_issues_returns_error_when_request_fails(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")

    async def _fake_request(*args, **kwargs):
        return False, None, "search failed"

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, issues, err = _run(mgr.search_issues("project = PROJ"))

    assert ok is False
    assert issues == []
    assert err == "search failed"


def test_search_issues_simplifies_results_and_caps_max_results(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")
    captured = {}

    async def _fake_request(method, endpoint, **kwargs):
        captured.update({"method": method, "endpoint": endpoint, "kwargs": kwargs})
        return (
            True,
            {
                "issues": [
                    {
                        "key": "PROJ-1",
                        "fields": {
                            "summary": "Fix login",
                            "status": {"name": "To Do"},
                            "assignee": {"displayName": "Ada"},
                            "priority": {"name": "High"},
                            "issuetype": {"name": "Bug"},
                        },
                    },
                    {"key": "PROJ-2", "fields": None},
                ]
            },
            "",
        )

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, issues, err = _run(mgr.search_issues("project = PROJ", fields=["summary"], max_results=500))

    assert ok is True
    assert err == ""
    assert captured["method"] == "GET"
    assert captured["endpoint"] == "search"
    assert captured["kwargs"]["params"]["maxResults"] == 100
    assert captured["kwargs"]["params"]["fields"] == ["summary"]
    assert issues == [
        {
            "key": "PROJ-1",
            "summary": "Fix login",
            "status": "To Do",
            "assignee": "Ada",
            "priority": "High",
            "type": "Bug",
        },
        {
            "key": "PROJ-2",
            "summary": "",
            "status": "",
            "assignee": "",
            "priority": "",
            "type": "",
        },
    ]


def test_search_issues_uses_default_fields(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")
    captured = {}

    async def _fake_request(method, endpoint, **kwargs):
        captured.update(kwargs)
        return True, {"issues": []}, ""

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, issues, err = _run(mgr.search_issues("project = PROJ"))

    assert ok is True
    assert issues == []
    assert err == ""
    assert captured["params"]["fields"] == [
        "summary",
        "status",
        "assignee",
        "priority",
        "issuetype",
    ]


def test_list_projects_handles_error(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")

    async def _fake_request(*args, **kwargs):
        return False, None, "no access"

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, projects, err = _run(mgr.list_projects())

    assert ok is False
    assert projects == []
    assert err == "no access"


def test_list_projects_simplifies_output(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")

    async def _fake_request(*args, **kwargs):
        return True, [{"key": "PROJ", "name": "Project", "id": "100"}, {}], ""

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, projects, err = _run(mgr.list_projects())

    assert ok is True
    assert err == ""
    assert projects == [
        {"key": "PROJ", "name": "Project", "id": "100"},
        {"key": "", "name": "", "id": ""},
    ]


def test_get_project_statuses_handles_error(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")

    async def _fake_request(*args, **kwargs):
        return False, None, "forbidden"

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, statuses, err = _run(mgr.get_project_statuses("PROJ"))

    assert ok is False
    assert statuses == []
    assert err == "forbidden"


def test_get_project_statuses_deduplicates_and_skips_empty(monkeypatch):
    mgr = JiraManager(url="https://jira.local", token="abc")

    async def _fake_request(*args, **kwargs):
        return (
            True,
            [
                {"statuses": [{"name": "To Do"}, {"name": "In Progress"}]},
                {"statuses": [{"name": "To Do"}, {"name": ""}]},
            ],
            "",
        )

    monkeypatch.setattr(mgr, "_request", _fake_request)

    ok, statuses, err = _run(mgr.get_project_statuses("PROJ"))

    assert ok is True
    assert err == ""
    assert statuses == ["To Do", "In Progress"]


def test_request_retries_on_timeout(monkeypatch):
    """
    httpx.TimeoutException fırlatıldığında AsyncRetrying mekanizmasının
    devreye girdiğini ve doğru hata mesajını döndüğünü test eder.
    (Satır 105-106 kapsamı)
    """
    import httpx

    # Eğer ortamda stub httpx kullanılıyorsa TimeoutException'ı mocklayalım
    if not hasattr(httpx, "TimeoutException"):
        httpx.TimeoutException = type("TimeoutException", (Exception,), {})
    if not hasattr(httpx, "TransportError"):
        httpx.TransportError = type("TransportError", (Exception,), {})

    class _TimeoutClient(_FakeClient):
        async def request(self, method, url, **kwargs):
            raise httpx.TimeoutException("Bağlantı zaman aşımına uğradı")

    def _factory(**kwargs):
        return _TimeoutClient(**kwargs)

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _factory)
    mgr = JiraManager(url="https://jira.local", token="abc")

    # _request fonksiyonu exception fırlatınca retry yapacak ve en sonunda hata dönecek
    ok, data, err = _run(mgr._request("GET", "issue/PROJ-1"))

    assert ok is False
    assert data is None
    assert "Bağlantı zaman aşımına uğradı" in err


def test_request_retries_on_service_unavailable(monkeypatch):
    """
    HTTP 503 (veya 429/502/504) durum kodlarında AsyncRetrying mekanizmasının
    _JiraRetryableError fırlattığını test eder.
    (Satır 107-108 kapsamı)
    """

    class _503Client(_FakeClient):
        async def request(self, method, url, **kwargs):
            return _FakeResponse(
                status_code=503,
                text="Service Unavailable Retry Later",
                content=b"",
            )

    def _factory(**kwargs):
        return _503Client(**kwargs)

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _factory)
    mgr = JiraManager(url="https://jira.local", token="abc")

    ok, data, err = _run(mgr._request("GET", "issue/PROJ-1"))

    assert ok is False
    assert data is None
    assert "HTTP 503: Service Unavailable" in err
