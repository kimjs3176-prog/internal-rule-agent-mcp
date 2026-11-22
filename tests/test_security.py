"""보안 회귀 테스트 — 기본 보안 헤더와, 웹 화면을 옮긴 뒤 남은 내규 등록 주소가 없는지."""


def test_security_headers(client):
    for path in ("/", "/api/ping"):
        r = client.get(path, headers={"Accept": "text/html"})
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_no_web_screen_or_upload(client):
    # 웹 화면과 내규 등록은 내규똑똑(agro-law)으로 옮겼다 — 이 서버에는 MCP 와 엔진 API 만 있다
    for path in ("/upload", "/upload.html", "/api/regs/upload/status", "/assets/reg_agent.js"):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/regs/upload", data={}).status_code in (404, 405)
