"""自宅LAN（スマホ）からの接続: LAN外の拒否、PINログイン、試行回数の制限、PC専用の設定。"""

import pytest
from fastapi.testclient import TestClient

from app import security
from app.main import app

PHONE = ("192.168.1.20", 50000)


@pytest.fixture()
def phone(client):
    # スマホは HTTPS（Secure Cookie が送られるように https で）
    with TestClient(app, client=PHONE, base_url="https://testserver") as c:
        yield c


def test_outside_lan_is_refused(client):
    with TestClient(app, client=("8.8.8.8", 1234), base_url="https://testserver") as c:
        r = c.get("/api/today")
        assert r.status_code == 403
        assert c.post("/api/auth/login", json={"pin": "x"}).status_code == 403


def test_pin_login_flow(client, phone):
    # PINが未設定ならログインできない
    assert phone.get("/api/today").status_code == 401
    assert phone.post("/api/auth/login", json={"pin": "246813"}).status_code == 401

    # PINはPCから設定する。推測されやすいものや短いものは不可
    assert client.put("/api/lan", json={"pin": "12345"}).status_code == 400
    assert client.put("/api/lan", json={"pin": "111111"}).status_code == 400
    assert client.put("/api/lan", json={"pin": "246813"}).status_code == 200
    # PINのハッシュは設定の取得で返さない
    assert "pin_hash" not in client.get("/api/settings").json()

    assert phone.get("/api/auth/status").json() == {"local": False, "authenticated": False}
    r = phone.post("/api/auth/login", json={"pin": "246813"})
    assert r.status_code == 200
    assert "httponly" in r.headers["set-cookie"].lower() and "secure" in r.headers["set-cookie"].lower()
    assert phone.get("/api/auth/status").json()["authenticated"] is True
    assert phone.get("/api/today").status_code == 200
    assert phone.get("/api/today").headers["x-frame-options"] == "DENY"

    # スマホからはLANやGoogleの設定は変えられない
    assert phone.put("/api/lan", json={"enabled": False}).status_code == 403
    assert phone.get("/api/google").status_code == 403
    assert phone.get("/api/meta").json()["local"] is False

    # PINを変えるとスマホはログアウトされる
    client.put("/api/lan", json={"pin": "975310"})
    assert phone.get("/api/today").status_code == 401


def test_logout(client, phone):
    client.put("/api/lan", json={"pin": "246813"})
    phone.post("/api/auth/login", json={"pin": "246813"})
    assert phone.get("/api/today").status_code == 200
    phone.post("/api/auth/logout")
    assert phone.get("/api/today").status_code == 401


def test_too_many_wrong_pins_locks_out(client, phone):
    client.put("/api/lan", json={"pin": "246813"})
    for _ in range(5):
        assert phone.post("/api/auth/login", json={"pin": "000001"}).status_code == 401
    r = phone.post("/api/auth/login", json={"pin": "246813"})
    assert r.status_code == 429 and "分ほど待って" in r.json()["detail"]
    # 別の端末は影響を受けない
    with TestClient(app, client=("192.168.1.21", 1), base_url="https://testserver") as other:
        assert other.post("/api/auth/login", json={"pin": "246813"}).status_code == 200


def test_enable_requires_pin_and_certificate(client):
    assert client.put("/api/lan", json={"enabled": True}).status_code == 400
    client.put("/api/lan", json={"pin": "246813"})
    s = client.put("/api/lan", json={"enabled": True}).json()
    assert s["enabled"] is True and s["running"] is False
    assert s["cert_ok"] is False and "証明書" in s["error"]
    s = client.put("/api/lan", json={"enabled": False}).json()
    assert s["enabled"] is False


def test_address_checks():
    assert security.is_lan("192.168.0.5") and security.is_lan("10.0.0.2") and security.is_lan("172.16.3.4")
    assert security.is_lan("::ffff:192.168.1.9")
    assert not security.is_lan("8.8.8.8") and not security.is_lan("127.0.0.1") and not security.is_lan("bad")
    assert security.is_local("127.0.0.1") and security.is_local("::1")
    h = security.hash_pin("246813")
    assert security.verify_pin("246813", h) and not security.verify_pin("246814", h)
