"""MCP 서버(mcp_server/server.py): 표준 입출력 JSON-RPC 로 도구 목록·호출이 되는지, 화면 엔진 도구가 개정문·대비표·검증을 내는지."""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "mcp_server", "server.py")


class Mcp:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8", cwd=ROOT)
        self.n = 0

    def send(self, msg):
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()

    def rpc(self, method, params=None):
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, **({"params": params} if params is not None else {})})
        return json.loads(self.p.stdout.readline())

    def call(self, name, args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})["result"]
        return r, json.loads(r["content"][0]["text"]) if not r["isError"] or r["content"][0]["text"].startswith("{") else r["content"][0]["text"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=20)


@pytest.fixture(scope="module")
def mcp():
    m = Mcp()
    r = m.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})
    assert r["result"]["protocolVersion"] == "2025-06-18"
    m.send({"jsonrpc": "2.0", "method": "notifications/initialized"})   # 알림 — 답이 없어야 다음 응답이 밀리지 않는다
    yield m
    m.close()


def test_initialize_and_list(mcp):
    tools = mcp.rpc("tools/list")["result"]["tools"]
    names = [t["name"] for t in tools]
    for n in ["run_agent", "amend_regulation", "search_regulations", "get_regulation", "check_regulation", "health_check",
              "citation_impact", "upper_law_impact", "bulk_rename", "advise", "list_regulations"]:
        assert n in names
    for t in tools:
        assert t["description"] and t["inputSchema"]["type"] == "object"
    assert mcp.rpc("ping")["result"] == {}
    assert mcp.rpc("없는/메서드")["error"]["code"] == -32601


def test_old_protocol_version_is_accepted():
    m = Mcp()
    try:
        assert m.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})["result"]["protocolVersion"] == "2024-11-05"
        assert m.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"   # 모르는 판이면 서버가 아는 최신 판
    finally:
        m.close()


def test_read_tools(mcp):
    r, d = mcp.call("search_regulations", {"query": "일비", "limit": 3})
    assert not r["isError"] and d["results"][0]["regulation"] == "여비규정"
    r, d = mcp.call("get_regulation", {"regulation": "여비규정", "articles": ["제15조"]})
    assert [a["article"] for a in d["articles"]] == ["제15조"] and "별표 2" in d["appendices"]
    r, d = mcp.call("get_regulation", {"regulation": "여비"})                    # 둘 이상이면 후보를 준다
    assert r["isError"] and "여비규정" in d["candidates"]
    r, d = mcp.call("check_regulation", {"text": "제1조(목적) 이 규칙은 제9조에 따른다.", "title": "시험규칙"})
    assert d["errors"] >= 1 and any("제9조" in i["message"] for i in d["issues"])
    r, d = mcp.call("citation_impact", {"regulation": "여비규정", "articles": ["제20조"]})
    assert any(h["article"] == "제24조" for h in d["same_regulation"])
    r, d = mcp.call("bulk_rename", {"old": "기획운영본부", "new": "경영기획본부"})
    assert d["regulations"] == 24 and d["places"] == 29 and d["amendments"][0]["regulation"]
    r, d = mcp.call("health_check", {"top": 2})
    assert d["regulations"] >= 100 and len(d["lowest"]) == 2
    r, d = mcp.call("없는_도구", {})
    assert r["isError"]


@pytest.mark.skipif(not shutil.which("node"), reason="화면 엔진 도구는 Node.js 가 필요하다")
def test_engine_tools(mcp, tmp_path):
    r, d = mcp.call("amend_regulation", {"regulation": "여비규정", "changes": [{"article": "제20조", "type": "delete"}], "output_dir": str(tmp_path)})
    assert not r["isError"], d
    assert "제20조를 삭제한다." in d["amendment_text"] and d["verification"]["ok"]
    assert d["comparison_table"][0]["amended"].endswith("<삭 제>")
    assert any("제24조" in x and "제20조" in x for x in d["check"]["items"])         # 지운 조를 인용하는 제24조를 짚는다
    assert d["saved"]["file"].endswith(".hwpx") and os.path.getsize(d["saved"]["file"]) > 3000
    r, d = mcp.call("run_agent", {"request": "여비규정 제15조의 일비를 3만원으로 올려줘"})
    assert d["mode"] == "amend" and d["verification"]["ok"] and "별표 2를 별지와 같이 한다." in d["amendment_text"]
    assert any(s["step"] == "수치 반영" and "30,000" in s["detail"] for s in d["steps"])
