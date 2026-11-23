"""The local API answers only local clients (SEC-API-01).

The API has no authentication and scans any path it is sent. Bound to 127.0.0.1 it is
still reachable from a web page the user visits: a browser sends the page's request to
127.0.0.1 and lets the page read the answer when the API allows that origin (CORS), and a
DNS-rebinding page reaches it under its own host name. So by default:

- no cross-origin access: no Access-Control-Allow-Origin for another origin;
- only loopback host names are served (Host header), other names get 400.

Origins that may call the API, and further host names, are given explicitly.
"""

import pytest

pytest.importorskip("fastapi", reason="requires api extra: pip install ai-slop-detector[api]")

from fastapi.testclient import TestClient  # noqa: E402

from slop_detector.api.server import create_app  # noqa: E402

EVIL = "https://evil.example"


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "local_module.py"
    path.write_text("def f(x):\n    return x\n", encoding="utf-8")
    return str(path)


def _local(app=None):
    return TestClient(app or create_app(), base_url="http://127.0.0.1:8000")


def test_preflight_from_another_origin_is_not_allowed():
    response = _local().options(
        "/analyze/file",
        headers={
            "Origin": EVIL,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None, response.headers
    assert response.headers.get("access-control-allow-credentials") is None, response.headers


def test_a_page_of_another_origin_cannot_read_a_scan(target):
    response = _local().post("/analyze/file", json={"file_path": target}, headers={"Origin": EVIL})
    assert response.headers.get("access-control-allow-origin") is None, response.headers


def test_a_rebinding_host_name_is_refused(target):
    client = TestClient(create_app(), base_url="http://evil.example:8000")
    response = client.post("/analyze/file", json={"file_path": target})
    assert response.status_code == 400, response.status_code


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_keep_loopback_clients_are_served(host, target):
    client = TestClient(create_app(), base_url=f"http://{host}:8000")
    response = client.post("/analyze/file", json={"file_path": target})
    assert response.status_code == 200, response.text


def test_keep_an_allowed_origin_is_allowed_and_no_other(target):
    app = create_app(allowed_origins=["http://localhost:3000"])
    ok = _local(app).post(
        "/analyze/file", json={"file_path": target}, headers={"Origin": "http://localhost:3000"}
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert ok.headers.get("access-control-allow-credentials") is None
    other = _local(app).post("/analyze/file", json={"file_path": target}, headers={"Origin": EVIL})
    assert other.headers.get("access-control-allow-origin") is None


def test_keep_a_bound_host_name_is_added(target):
    client = TestClient(create_app(allowed_hosts=["10.0.0.5"]), base_url="http://10.0.0.5:8000")
    assert client.post("/analyze/file", json={"file_path": target}).status_code == 200
