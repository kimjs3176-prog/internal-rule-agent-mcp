"""원격 MCP 보안·운영 점검 고침: 묶음 호출 상한·시간, 프록시 주소, 엔진 경로 우회, 엔진 시간 제한, 링크 기한, 큰 본문, JSON-RPC 오류 코드."""
import io
import json
import shutil
import subprocess
import time

import pytest

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def post(client, body, headers=None):
    return client.post("/mcp", data=json.dumps(body, ensure_ascii=False), headers={**H, **(headers or {})})


def ping(i=1):
    return {"jsonrpc": "2.0", "id": i, "method": "ping"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("MCP_TOKEN", "MCP_HTTP", "MCP_ALLOWED_ORIGINS", "MCP_PUBLIC_URL", "MCP_TRUST_PROXY", "VERCEL"):
        monkeypatch.delenv(k, raising=False)
    from mcp_server import remote
    remote._RATE.clear()
    yield
    remote._RATE.clear()


# 1. 묶음: 건마다 상한에 세고, 한 묶음 전체에 시간 제한을 둔다
def test_batch_counts_each_message(client, monkeypatch):
    monkeypatch.setenv("MCP_PER_MIN", "10")
    r = post(client, [ping(i) for i in range(8)])
    assert r.status_code == 200 and len(r.get_json()) == 8
    r = post(client, [ping(i) for i in range(8)])                # 1분에 16건 — 상한(10)을 넘는다
    assert r.status_code == 429 and r.get_json()["error"]["code"] == -32000 and r.headers["Retry-After"]


def test_batch_shared_deadline(client, monkeypatch):
    from mcp_server import core, engine
    monkeypatch.setattr(engine, "HTTP_TIMEOUT", 1)
    calls = []

    def slow(**kw):
        calls.append(1)
        time.sleep(0.6)
        return {"ok": True}
    monkeypatch.setitem(core._BY, "list_regulations", (*core._BY["list_regulations"][:2], slow, *core._BY["list_regulations"][3:]))
    body = [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "list_regulations", "arguments": {}}} for i in range(5)]
    out = post(client, body).get_json()
    assert len(out) == 5 and len(calls) == 2                     # 0초·0.6초에 시작한 두 건만 돌고 나머지는 하지 않는다
    late = [x for x in out if "error" in x]
    assert len(late) == 3 and all("따로" in x["error"]["message"] for x in late)


# 2. 프록시 뒤: X-Forwarded-For 의 맨 오른쪽(프록시가 붙인 주소)을 쓰고, 상한 표는 커지지 않는다
def test_trust_proxy_uses_rightmost(client, monkeypatch):
    monkeypatch.setenv("MCP_PER_MIN", "10")
    monkeypatch.setenv("MCP_TRUST_PROXY", "1")
    codes = [post(client, ping(), {"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"}).status_code for i in range(15)]
    assert codes.count(429) == 5                                 # 앞 주소를 바꿔도 같은 접속 주소로 센다


def test_rate_table_bounded(client, monkeypatch):
    from mcp_server import remote
    monkeypatch.setenv("MCP_TRUST_PROXY", "1")
    monkeypatch.setattr(remote, "_RATE_MAX", 50)
    for i in range(200):
        post(client, ping(), {"X-Forwarded-For": f"10.1.{i // 250}.{i % 250}"})
    assert len(remote._RATE) <= 50


# 3. 엔진 경로: 퍼센트 부호화·점 경로로 막힌 API(작업 실적 기록)를 돌아가지 못한다
BAD = ["/api/regagent/%6Cedger", "/api/regagent/%256Cedger", "/api/regagent/./ledger", "/api/regagent/x/%2e%2e/ledger",
       "/api/regagent/x/../ledger", "/api/regagent//ledger", "/api/regagent/%2fledger", "/api/regagent/ledger?x=1"]
GOOD = ["/api/regagent/catalog", "/api/law/search?q=%EC%97%AC%EB%B9%84", "/api/regagent/reg/%EC%97%AC%EB%B9%84%EA%B7%9C%EC%A0%95"]


def test_engine_allowed_decodes():
    from mcp_server import engine
    for u in BAD:
        assert not engine.allowed("GET", u), u
        assert engine.local_fetch("GET", u)[0] == 403, u
    for u in GOOD:
        assert engine.allowed("GET", u), u


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js 필요")
def test_engine_mjs_allowed_decodes():
    import os
    src = open(os.path.join(os.path.dirname(__file__), "..", "mcp_server", "engine.mjs"), encoding="utf-8").read()
    start = src.index("const ALLOWED")
    decl = src[start:src.index("\n\n", start)]
    js = decl + f"\nconsole.log(JSON.stringify([{json.dumps(BAD)}.map(ALLOWED), {json.dumps(GOOD)}.map(ALLOWED)]));"
    bad, good = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert not any(bad), dict(zip(BAD, bad))
    assert all(good), dict(zip(GOOD, good))


# 4. QuickJS: 시간이 다 되면 다음 요청을 시작하지 않는다
def test_quickjs_no_fetch_after_deadline():
    pytest.importorskip("quickjs")
    from mcp_server import engine
    calls = []

    def slow(m, u, b=None, ctx=""):
        calls.append(u)
        time.sleep(0.6)
        return 200, '{"success":true}', "application/json"
    s = "Promise.all([1,2,3,4,5].map(function(i){return fetch('/api/regagent/x'+i);})).then(function(){ __out = JSON.stringify({ok:1}); });"
    t0 = time.monotonic()
    r = engine._run_quickjs({}, fetch=slow, script=s, timeout=1)
    assert "error" in r and "초" in r["error"] and len(calls) == 2 and time.monotonic() - t0 < 2.5


# 5. 내려받기 링크에 기한이 있다
def test_doc_token_expires(client, monkeypatch):
    from mcp_server import core
    tok = core.make_token("enact", {"title": "시험지침", "text": "제1조(목적) 이 지침은 시험을 정한다."})
    assert core.read_token(tok)[0] == "enact"
    real = time.time
    monkeypatch.setattr(core.time, "time", lambda: real() + core.LINK_TTL + 60)
    with pytest.raises(core.LinkExpired):
        core.read_token(tok)
    r = client.get(f"/api/mcp/doc/hwpx/{tok}")
    assert r.status_code == 410 and "다시" in r.get_data(as_text=True)
    monkeypatch.setattr(core.time, "time", real)
    import base64
    import zlib
    old = base64.urlsafe_b64encode(zlib.compress(json.dumps(["enact", {"title": "x", "text": "제1조(목적) 가."}]).encode())).decode().rstrip("=")
    assert client.get(f"/api/mcp/doc/hwpx/{old}").status_code == 410     # 기한이 없는 옛 링크도 받지 않는다


def test_signed_token_exp_is_covered_by_signature(monkeypatch):
    from mcp_server import core
    monkeypatch.setenv("MCP_TOKEN", "s3cret")
    tok = core.make_token("enact", {"title": "x", "text": "제1조(목적) 가."})
    raw, _, sig = tok.partition(".")
    import base64
    import zlib
    op, inp, exp = json.loads(zlib.decompress(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))))
    forged = base64.urlsafe_b64encode(zlib.compress(json.dumps([op, inp, exp + 10 ** 7]).encode())).decode().rstrip("=")
    with pytest.raises(PermissionError):
        core.read_token(forged + "." + sig)


# 6. 큰 본문: 1MB 넘게는 읽지 않고 JSON-RPC 꼴 413
def test_oversized_stream_not_read_fully(client):
    from mcp_server import remote

    class S(io.BytesIO):
        n = 0

        def read(self, k=-1):
            b = super().read(k)
            S.n += len(b)
            return b

        def readinto(self, b):
            r = super().readinto(b)
            S.n += r
            return r
    r = client.post("/mcp", input_stream=S(b"x" * (remote.MAX_BODY * 3)), headers={**H, "Transfer-Encoding": "chunked"},
                    environ_overrides={"wsgi.input_terminated": True})
    assert r.status_code == 413 and r.get_json()["error"]["code"] == -32600
    assert S.n <= remote.MAX_BODY + 65536


def test_over_app_limit_is_json(client):
    r = client.post("/mcp", data=b"x" * (46 * 1024 * 1024), headers=H)
    assert r.status_code == 413 and r.headers["Content-Type"].startswith("application/json")


# 7. JSON-RPC 오류 코드
def test_unknown_tool_and_null_id(client):
    r = post(client, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "없는_도구", "arguments": {}}}).get_json()
    assert r["id"] == 7 and r["error"]["code"] == -32602 and "없는_도구" in r["error"]["message"]
    r = post(client, {"jsonrpc": "2.0", "id": None, "method": "ping"}).get_json()
    assert r["id"] is None and r["error"]["code"] == -32600
