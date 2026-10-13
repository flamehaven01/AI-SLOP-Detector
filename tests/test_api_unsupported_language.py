"""The file endpoints answer 400 for a JS/TS/Go file, not 500.

analyze_file refuses non-Python source (UnsupportedLanguageError); the API
turned that into a 500 server error although the request is what is wrong.
"""

import pytest

pytest.importorskip("fastapi", reason="requires api extra: pip install ai-slop-detector[api]")

from fastapi.testclient import TestClient  # noqa: E402

from slop_detector.api.server import create_app  # noqa: E402


@pytest.mark.parametrize("route", ["/analyze/file", "/agent/file"])
def test_js_file_is_a_client_error(tmp_path, route):
    path = tmp_path / "app.js"
    path.write_text("function f() { return 1; }\n", encoding="utf-8")
    response = TestClient(create_app()).post(route, json={"file_path": str(path)})
    assert response.status_code == 400
    assert "not Python source" in response.json()["detail"]
