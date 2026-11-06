"""보안 회귀 테스트 — 업로드 권한(CSRF·DNS 리바인딩·프록시 경유·토큰 무차별 대입)과 기본 보안 헤더.

업로드 설정(REG_UPLOAD_TOKEN 등)은 모듈을 불러올 때 읽으므로 임시 폴더에서 별도 프로세스로 실행한다.
"""
import json
import os
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ANON = textwrap.dedent(r'''
    import io, json
    import api_server
    c = api_server.app.test_client()

    def up(title, headers=None, base_url="http://localhost:5100"):
        data = {"title": title, "file": (io.BytesIO("제1조(목적) 가.".encode("utf-8")), "a.txt")}
        r = c.post("/api/regs/upload", data=data, content_type="multipart/form-data", headers=headers or {},
                   base_url=base_url, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        return r.status_code

    out = {
        "plain": up("인사 규정"),
        "same_origin": up("복무 규칙", {"Origin": "http://localhost:5100", "Sec-Fetch-Site": "same-origin"}),
        "csrf_origin": up("감사 규정", {"Origin": "https://evil.example"}),
        "csrf_fetch_site": up("감사 규정", {"Sec-Fetch-Site": "cross-site"}),
        "rebind_host": up("감사 규정", base_url="http://evil.example:5100"),
        "proxied": up("감사 규정", {"X-Forwarded-For": "203.0.113.9"}),
    }
    r = c.post("/api/regs/upload/delete", data={"slug": "인사_규정"}, headers={"Origin": "https://evil.example"},
               base_url="http://localhost:5100", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    out["csrf_delete"] = r.status_code
    print(json.dumps(out))
''')

TOKEN = textwrap.dedent(r'''
    import io, json
    import api_server
    c = api_server.app.test_client()

    def up(token, ip):
        data = {"title": "인사 규정", "token": token, "file": (io.BytesIO("제1조(목적) 가.".encode("utf-8")), "a.txt")}
        r = c.post("/api/regs/upload", data=data, content_type="multipart/form-data", environ_base={"REMOTE_ADDR": ip})
        return r.status_code

    bad = [up("wrong-%d" % i, "198.51.100.7") for i in range(10)]
    out = {"bad": bad, "locked": up("wrong", "198.51.100.7"), "locked_good": up("s3cret-token", "198.51.100.7"),
           "other_ip_good": up("s3cret-token", "198.51.100.8")}
    print(json.dumps(out))
''')


def _run(script, tmp_path, **env_over):
    reg = tmp_path / "regulations"
    reg.mkdir()
    man = tmp_path / "manifest.json"
    man.write_text("[]", encoding="utf-8")
    env = {**os.environ, "REG_DIR": str(reg), "REG_MANIFEST": str(man), "REG_UPLOAD_TOKEN": "",
           "GITHUB_TOKEN": "", "GITHUB_REPO": "", "REG_UPLOAD_ALLOW_ANON": "", **env_over}
    p = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_tokenless_upload_only_from_local_page(tmp_path):
    out = _run(ANON, tmp_path)
    assert out["plain"] == 200 and out["same_origin"] == 200       # 이 PC 의 업로드 화면은 그대로 동작
    assert out["csrf_origin"] == 401                                 # 다른 사이트가 브라우저로 보낸 폼(CSRF)
    assert out["csrf_fetch_site"] == 401
    assert out["rebind_host"] == 401                                 # DNS 리바인딩(Host 가 루프백 이름이 아님)
    assert out["proxied"] == 401                                     # 같은 PC 의 리버스 프록시를 거친 원격 요청
    assert out["csrf_delete"] == 401                                 # 되돌리기(삭제)도 같은 기준


def test_upload_token_bruteforce_locked(tmp_path):
    out = _run(TOKEN, tmp_path, REG_UPLOAD_TOKEN="s3cret-token")
    assert out["bad"] == [401] * 10
    assert out["locked"] == 429 and out["locked_good"] == 429        # 잠긴 동안은 맞는 토큰도 시험하지 않는다
    assert out["other_ip_good"] == 200


def test_security_headers(client):
    for path in ("/", "/api/ping", "/api/regs/upload/status"):
        r = client.get(path)
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
