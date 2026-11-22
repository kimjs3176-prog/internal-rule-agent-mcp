"""원격 MCP(/mcp, Streamable HTTP): claude.ai·ChatGPT 커넥터처럼 주소로 붙어 도구를 쓰는지, 막아야 할 것을 막는지."""
import json

import pytest
from conftest import needs_engine

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
PUB = {"Host": "agro-law-demo.vercel.app", "X-Forwarded-Proto": "https"}


def rpc(client, method, params=None, i=1, headers=None, path="/mcp"):
    body = {"jsonrpc": "2.0", "id": i, "method": method, **({"params": params} if params is not None else {})}
    return client.post(path, data=json.dumps(body, ensure_ascii=False), headers={**H, **(headers or {})})


def call(client, name, args, headers=None):
    r = rpc(client, "tools/call", {"name": name, "arguments": args}, headers=headers)
    assert r.status_code == 200, r.data
    return r.get_json()["result"]


@pytest.fixture(autouse=True)
def _no_token(monkeypatch):
    for k in ("MCP_TOKEN", "MCP_HTTP", "MCP_ALLOWED_ORIGINS", "MCP_PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)


def test_initialize_list_and_lifecycle(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
    assert r.status_code == 200 and r.headers["Content-Type"].startswith("application/json")
    res = r.get_json()["result"]
    assert res["protocolVersion"] == "2025-06-18" and res["capabilities"]["tools"] and "download" in res["instructions"]
    assert rpc(client, "initialize", {"protocolVersion": "2025-03-26"}).get_json()["result"]["protocolVersion"] == "2025-03-26"
    # 알림은 본문 없이 202
    r = client.post("/mcp", data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), headers=H)
    assert r.status_code == 202 and r.data == b""
    tools = rpc(client, "tools/list", headers={"MCP-Protocol-Version": "2025-06-18"}).get_json()["result"]["tools"]
    names = [t["name"] for t in tools]
    for n in ["run_agent", "amend_regulation", "search_regulations", "get_regulation", "check_regulation", "health_check",
              "citation_impact", "upper_law_impact", "bulk_rename", "advise", "list_regulations", "search", "fetch"]:
        assert n in names
    for t in tools:                                          # 원격은 파일을 쓰지 않는다 — output_dir 없음, 모두 읽기 전용
        assert "output_dir" not in t["inputSchema"]["properties"] and t["annotations"]["readOnlyHint"] is True
    assert "documents" in next(t for t in tools if t["name"] == "run_agent")["inputSchema"]["properties"]
    # 같은 것을 /api/mcp 로도
    assert rpc(client, "ping", path="/api/mcp").get_json()["result"] == {}


def test_transport_rules(client):
    assert client.get("/mcp").status_code == 405 and client.delete("/mcp").status_code == 405     # 세션·서버 알림 흐름 없음
    assert rpc(client, "ping", headers={"MCP-Protocol-Version": "2099-01-01"}).status_code == 400
    assert client.head("/mcp").status_code == 405                                                 # HEAD 로 살펴봐도 400 이 아니다
    # 첫 연결(initialize)은 판 머리글이 더 새 판이어도 받아 본문 판으로 맞춘다(claude.ai 커넥터 확인 단계)
    r = rpc(client, "initialize", {"protocolVersion": "2099-01-01", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
            headers={"MCP-Protocol-Version": "2099-01-01"})
    assert r.status_code == 200 and r.get_json()["result"]["protocolVersion"] == "2025-11-25"
    r = rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
            headers={"MCP-Protocol-Version": "2025-11-25"})
    assert r.status_code == 200 and r.get_json()["result"]["protocolVersion"] == "2025-11-25"
    assert rpc(client, "ping", headers={"MCP-Protocol-Version": "2025-11-25"}).status_code == 200
    r = client.post("/mcp", data="{bad", headers=H)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == -32700
    r = client.post("/mcp", data=json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/x"}]), headers=H)
    assert r.get_json() == [{"jsonrpc": "2.0", "id": 1, "result": {}}]                            # 묶음(2025-03-26 판)
    assert client.post("/mcp", data="[]", headers=H).status_code == 400
    r = client.post("/mcp", data=json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}), headers={"Accept": "text/event-stream"})
    assert r.headers["Content-Type"].startswith("text/event-stream") and r.data.startswith(b"event: message\ndata: {")
    assert rpc(client, "없는/메서드").get_json()["error"]["code"] == -32601
    assert rpc(client, "tools/call", {"name": 3}).get_json()["error"]["code"] == -32602
    # 클라이언트의 응답(result)에는 답하지 않는다
    assert client.post("/mcp", data=json.dumps({"jsonrpc": "2.0", "id": 9, "result": {}}), headers=H).status_code == 202
    assert client.post("/mcp", data=b"x" * 1_100_000, headers=H).status_code == 413


def test_origin_token_and_switch(client, monkeypatch):
    assert rpc(client, "ping", headers={"Origin": "https://evil.example"}).status_code == 403          # 다른 사이트의 브라우저 호출
    r = rpc(client, "ping", headers={"Origin": "http://localhost:5100"})
    assert r.status_code == 200 and r.headers["Access-Control-Allow-Origin"] == "http://localhost:5100"
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://inspector.example")
    assert rpc(client, "ping", headers={"Origin": "https://inspector.example"}).status_code == 200
    r = client.options("/mcp", headers={"Origin": "https://inspector.example", "Access-Control-Request-Method": "POST"})
    assert r.status_code == 204 and "MCP-Protocol-Version" in r.headers["Access-Control-Allow-Headers"]
    monkeypatch.setenv("MCP_TOKEN", "s3cret")
    r = rpc(client, "ping")
    assert r.status_code == 401 and r.headers["WWW-Authenticate"].startswith("Bearer")
    assert rpc(client, "ping", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert rpc(client, "ping", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    monkeypatch.setenv("MCP_HTTP", "off")
    assert rpc(client, "ping").status_code == 404


@needs_engine
def test_run_agent_with_download_links(client):
    res = call(client, "run_agent", {"request": "여비규정 제15조의 일비를 3만원으로 올려줘"}, headers=PUB)
    d = res["structuredContent"]
    assert not res["isError"] and d["mode"] == "amend" and d["verification"]["ok"]
    assert "별표 2를 별지와 같이 한다." in d["amendment_text"] and "doc" not in d and "saved" not in d
    assert any(s["step"] == "수치 반영" and "30,000" in s["detail"] for s in d["steps"])
    link = d["download"]["hwpx"]
    assert link.startswith("https://agro-law-demo.vercel.app/api/mcp/doc/hwpx/")
    f = client.get(link.split("vercel.app", 1)[1])
    assert f.status_code == 200 and f.data[:2] == b"PK" and len(f.data) > 3000
    assert "filename*=UTF-8''%EC%97%AC%EB%B9%84" in f.headers["Content-Disposition"]
    f = client.get(d["download"]["docx"].split("vercel.app", 1)[1])
    assert f.status_code == 200 and f.data[:2] == b"PK"
    assert client.get("/api/mcp/doc/hwpx/not-a-token").status_code == 400
    assert client.get("/api/mcp/doc/pdf/x").status_code == 404
    # 문서 링크를 원하지 않으면 주지 않는다
    assert "download" not in call(client, "run_agent", {"request": "여비규정 제15조의 일비를 3만원으로 올려줘", "documents": False})["structuredContent"]
    # 원격에서는 output_dir 를 받지 않는다(파일을 쓰지 않음)
    d = call(client, "run_agent", {"request": "여비규정 제20조를 삭제해줘", "output_dir": "/tmp/should-not-exist-mcp"}, headers=PUB)["structuredContent"]
    assert "saved" not in d and "제20조를 삭제한다." in d["amendment_text"]


@needs_engine
def test_signed_links_with_token(client, monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "s3cret")
    auth = {**PUB, "Authorization": "Bearer s3cret"}
    d = call(client, "amend_regulation", {"regulation": "여비규정", "changes": [{"article": "제20조", "type": "delete"}]}, headers=auth)["structuredContent"]
    link = d["download"]["docx"].split("vercel.app", 1)[1]
    assert "." in link.rsplit("/", 1)[1]                                                           # 서명이 붙는다
    assert client.get(link).status_code == 200                                                     # 링크만으로 받는다(머리글 없이)
    forged = link.rsplit(".", 1)[0] + ".AAAAAAAAAAAAAAAAAAAAAAAA"
    assert client.get(forged).status_code == 403
    assert client.get(link.rsplit(".", 1)[0]).status_code == 403                                  # 서명을 뗀 링크


def test_search_fetch_and_read_tools(client):
    d = call(client, "search", {"query": "출장 일비"}, headers=PUB)["structuredContent"]
    top = [x["id"] for x in d["results"][:3]]
    assert "여비규정#제15조" in top and d["results"][0]["url"].startswith("https://agro-law-demo.vercel.app/regulations/")
    r = call(client, "fetch", {"id": "여비규정#제15조"})["structuredContent"]
    assert r["title"].startswith("「여비규정」 제15조") and "별표 2" in r["text"] and r["metadata"]["revision"]
    r = call(client, "fetch", {"id": "여비규정#별표 2"})["structuredContent"]
    assert "25,000" in r["text"]
    assert call(client, "fetch", {"id": "없는규정#제1조"})["isError"]
    d = call(client, "get_regulation", {"regulation": "여비규정", "articles": "제15조", "appendices": ["별표2"]})["structuredContent"]
    assert [a["article"] for a in d["articles"]] == ["제15조"] and [x["id"] for x in d["appendix_text"]] == ["별표 2"]
    d = call(client, "search_regulations", {"query": "출장 숙박비 상한", "limit": 5})["structuredContent"]
    assert any(x["regulation"] == "여비규정" for x in d["results"])                               # 붙은 말로 없으면 낱말별로
    r = call(client, "get_regulation", {})
    assert r["isError"] and "regulation" in r["content"][0]["text"]                                # 필수 입력이 빠지면 무엇이 빠졌는지


def test_rate_limit_per_ip(client, monkeypatch):
    """같은 주소에서 1분에 MCP_PER_MIN 번을 넘으면 429(Retry-After), 다른 주소는 그대로. 토큰 확인보다 먼저 센다."""
    from mcp_server import remote
    remote._RATE.clear()
    monkeypatch.setenv("MCP_PER_MIN", "10")
    monkeypatch.setenv("VERCEL", "1")                          # Vercel 앞단이 채운 X-Forwarded-For 로 센다
    a, b = {"X-Forwarded-For": "203.0.113.7"}, {"X-Forwarded-For": "198.51.100.9"}
    codes = [rpc(client, "ping", headers=a).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[10:] == [429, 429]
    r = rpc(client, "ping", headers=a)
    assert r.status_code == 429 and 1 <= int(r.headers["Retry-After"]) <= 60 and r.get_json()["error"]["code"] == -32000
    assert rpc(client, "ping", headers=b).status_code == 200
    assert client.get("/api/mcp/doc/hwpx/x", headers=a).status_code == 429     # 문서 내려받기 링크도 같은 상한
    assert client.get("/mcp", headers={**a, "Accept": "text/html"}).status_code == 200   # 브라우저 안내는 세지 않음
    monkeypatch.setenv("MCP_TOKEN", "s3cret")
    assert rpc(client, "ping", headers=a).status_code == 429                  # 틀린 토큰도 상한에 걸린다(대입 방지)
    monkeypatch.delenv("VERCEL")                                              # Vercel 밖: 꾸민 X-Forwarded-For 는 믿지 않는다
    monkeypatch.delenv("MCP_TOKEN")
    remote._RATE.clear()
    codes = [rpc(client, "ping", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(12)]
    assert codes[10:] == [429, 429]
    remote._RATE.clear()
