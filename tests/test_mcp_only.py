"""범용 MCP 전용 배포(MCP_ONLY=1): 이 저장소의 기관·내규를 싣지 않고, 다른 기관 사규를 다루는 도구 6개만 연다.
MCP_ONLY 는 시작할 때 읽으므로 따로 띄운 파이썬에서 확인한다."""
import json
import os
import subprocess
import sys

from conftest import needs_engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHILD = r'''
import json, sys
import alio
alio.reachable = lambda force=False: False
import api_server
c = api_server.app.test_client()
H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
def rpc(method, params=None):
    b = {"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params is not None else {})}
    return c.post("/mcp", data=json.dumps(b, ensure_ascii=False), headers=H).get_json()
out = {}
out["init"] = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})["result"]
out["tools"] = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
out["blocked"] = rpc("tools/call", {"name": "run_agent", "arguments": {"request": "여비규정 제15조의 일비를 3만원으로 올려줘"}})["result"]
out["config"] = c.get("/api/regagent/config").get_json()
out["ping"] = c.get("/api/ping").get_json()
out["upload"] = c.get("/api/regs/upload/status").status_code
g = c.get("/mcp", headers={"Accept": "text/html"})
out["guide"] = [g.status_code, g.mimetype, g.get_data(as_text=True)]
out["get_json"] = c.get("/mcp", headers={"Accept": "application/json"}).status_code
if "--engine" in sys.argv:
    TXT = "제1조(목적) 이 규정은 출장에 관한 사항을 정한다.\n제2조(일비) 일비는 1일 2만원으로 한다.\n부칙\n이 규정은 공포한 날부터 시행한다."
    r = rpc("tools/call", {"name": "amend_regulation", "arguments": {"regulation": "출장규정", "source_text": TXT,
        "org": {"org_name": "한국가상공단"}, "changes": [{"article": "제2조", "body": "일비는 1일 3만원으로 한다."}], "documents": False}})
    out["amend"] = r["result"]["structuredContent"]
print("@@" + json.dumps(out, ensure_ascii=False))
'''


def _run(*args):
    env = {**os.environ, "MCP_ONLY": "1"}
    env.pop("ORG_CONFIG", None)
    p = subprocess.run([sys.executable, "-c", CHILD, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    line = next((x for x in p.stdout.splitlines() if x.startswith("@@")), None)
    assert line, p.stderr[-2000:]
    return json.loads(line[2:])


def test_mcp_only_offers_generic_tools_without_our_org():
    d = _run()
    assert sorted(d["tools"]) == sorted(["amend_regulation", "enact_regulation", "check_regulation",
                                        "alio_search_regulations", "alio_get_regulation", "alio_compare_values"])
    assert d["init"]["serverInfo"]["title"] == "범용 규정 제·개정 에이전트" and "등록된 내규는 없습니다" in d["init"]["instructions"]
    assert d["blocked"]["isError"] and "등록된 내규가 없어" in d["blocked"]["content"][0]["text"]
    cfg = d["config"]
    assert cfg["mcp_only"] and cfg["reg_count"] == 0 and cfg["org"]["org_name"] == "○○기관"
    assert "한국농업기술진흥원" not in json.dumps(cfg, ensure_ascii=False)
    assert d["ping"]["mcp_only"] is True and d["upload"] == 404
    code, mime, html = d["guide"]
    assert code == 200 and mime == "text/html" and "범용 규정 제·개정 에이전트 MCP" in html and "/mcp</code>" in html
    assert "<code>run_agent</code>" not in html and "<code>amend_regulation</code>" in html
    assert d["get_json"] == 405                                     # MCP 클라이언트의 GET 은 그대로 405


@needs_engine
def test_mcp_only_amend_pasted_text():
    a = _run("--engine")["amend"]
    assert "제2조 중 “2만원”을 “3만원”으로 한다." in a["amendment_text"] and a["verification"]["ok"]


def test_default_mode_guide_page(client):
    g = client.get("/mcp", headers={"Accept": "text/html"})
    html = g.get_data(as_text=True)
    assert g.status_code == 200 and "규정 제·개정 에이전트 MCP" in html and "<code>run_agent</code>" in html
    assert client.get("/api/ping").get_json()["mcp_only"] is False
