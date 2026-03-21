from tests.test_web_server_runtime import _FakeHTMLResponse, _load_web_server
import asyncio


def test_web_server_uses_react_dist_as_single_ui_root():
    mod = _load_web_server()
    assert str(mod.WEB_DIR).replace('\\', '/').endswith('/web_ui_react/dist')


def test_web_server_index_missing_dist_returns_build_guidance(monkeypatch, tmp_path):
    mod = _load_web_server()
    monkeypatch.setattr(mod, 'WEB_DIR', tmp_path)

    response = asyncio.run(mod.index())

    assert isinstance(response, _FakeHTMLResponse)
    assert response.status_code == 500
    assert 'npm run build' in response.content