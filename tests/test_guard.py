"""حارس الاستوديو: Host وOrigin (web/guard.py) — النفق ومواقع غريبة ما بتتحكم بالاستوديو."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.guard import LocalGuard, host_ok, origin_ok


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.post("/act")
    def act():
        return {"done": True}

    @app.delete("/act")
    def delete():
        return {"done": True}
    app.add_middleware(LocalGuard)
    return TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:8000", "[::1]:8000", "LOCALHOST:9000", "testserver"])
def test_local_hosts_pass(host):
    assert host_ok(host)


@pytest.mark.parametrize("host", ["", "evil.com", "abc.ngrok-free.app", "127.0.0.1.evil.com", "localhost.evil.com:8000", "192.168.1.5:8000", "[::2]"])
def test_other_hosts_are_refused(host):
    assert not host_ok(host)


def test_get_with_tunnel_host_is_400_in_arabic(client):
    r = client.get("/ping", headers={"Host": "abc.ngrok-free.app"})
    assert r.status_code == 400 and "localhost" in r.json()["detail"]
    assert client.get("/ping").status_code == 200


def test_cross_site_post_is_403_but_same_origin_and_no_origin_pass(client):
    assert client.post("/act", headers={"Origin": "https://evil.com"}).status_code == 403
    assert client.post("/act", headers={"Origin": "null"}).status_code == 403
    assert client.post("/act", headers={"Origin": "http://localhost:8000"}).status_code == 403          # localhost ≠ 127.0.0.1:8000 (Host)
    assert client.post("/act", headers={"Origin": "http://127.0.0.1:9999"}).status_code == 403          # منفذ تاني
    assert client.post("/act", headers={"Origin": "http://127.0.0.1:8000"}).status_code == 200
    assert client.post("/act").status_code == 200                                                         # curl/اختبارات
    assert client.delete("/act", headers={"Origin": "https://evil.com"}).status_code == 403
    assert client.post("/act", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/act", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_get_is_not_origin_checked(client):
    assert client.get("/ping", headers={"Origin": "https://evil.com"}).status_code == 200


def test_extension_origin_passes_other_schemes_do_not(client):
    assert client.post("/act", headers={"Origin": "chrome-extension://abcdef"}).status_code == 200
    assert client.post("/act", headers={"Origin": "file://"}).status_code == 403


def test_env_lists_extend_hosts_and_origins(monkeypatch, client):
    monkeypatch.setenv("VP_ALLOWED_HOSTS", "studio.example.com, 10.0.0.7")
    monkeypatch.setenv("VP_ALLOWED_ORIGINS", "https://studio.example.com")
    assert host_ok("studio.example.com:443") and host_ok("10.0.0.7:8000") and not host_ok("other.example.com")
    assert origin_ok("https://studio.example.com", "internal:80")
    assert client.get("/ping", headers={"Host": "studio.example.com"}).status_code == 200


def test_the_real_app_has_the_guard_and_still_serves_pages():
    from web.app import app
    c = TestClient(app)                                      # Host: testserver
    assert c.get("/").status_code == 200
    assert c.get("/", headers={"Host": "evil.ngrok.app"}).status_code == 400
    assert c.post("/api/ads/meta/token", headers={"Origin": "https://evil.com"}, json={}).status_code == 403


def test_zaki_ui_shell_icons_are_served_from_the_root_too():
    from web.app import app
    r = TestClient(app).get("/icons.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml") and b"<svg" in r.content[:300]
