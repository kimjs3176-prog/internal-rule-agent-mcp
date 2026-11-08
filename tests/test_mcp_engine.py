"""MCP 화면 엔진 실행기(mcp_server/engine.py): QuickJS 와 Node 가 같은 결과를 내는지, 엔진이 부를 수 있는 곳을 막는지."""
import json
import shutil

import pytest

quickjs = pytest.importorskip("quickjs")

REQUESTS = [
    "여비규정 제15조의 일비를 3만원으로 올려줘",
    "여비규정 제20조를 삭제해줘",
    "모든 내규에서 기획운영본부를 경영기획본부로 바꿔줘",
    "업무용 드론 운영지침을 새로 만들어줘",
    "출장 중 숙박비가 상한액을 넘으면 얼마까지 더 받을 수 있나요?",
    "청탁금지법 제10조가 개정됐어",
    "복무규정의 연차휴가 일수를 25일로 바꿔줘",
    "여비규정 제15조의 숙박비 상한액을 서울특별시 12만원으로 올려줘",
]
AMENDS = [
    {"slug": "여비규정", "changes": [{"article": "제20조", "type": "delete"}]},
    {"slug": "여비규정", "changes": [{"article": "제2조", "body": "여비는 운임·일비·숙박비·식비·이전비 및 가족여비로 구분한다."}], "reason": "준비금 폐지"},
    {"slug": "여비규정", "changes": [{"article": "제99조", "type": "modify", "body": "x"}]},
]


@pytest.fixture
def E(ra, monkeypatch):
    import alio
    import api_server
    from mcp_server import engine
    monkeypatch.setattr(alio, "reachable", lambda force=False: False)              # 외부망 결과가 실행마다 달라지지 않게
    monkeypatch.setattr(api_server._LAW_SESSION, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline")))
    return engine


def _strip(d):
    d = json.loads(json.dumps(d, ensure_ascii=False))
    d.pop("seconds", None)
    return d


@pytest.mark.skipif(not shutil.which("node"), reason="견줄 Node.js 가 없다")
def test_quickjs_matches_node(E, monkeypatch):
    for req in REQUESTS:
        monkeypatch.setenv("MCP_ENGINE", "quickjs")
        q = E.run("agent", request=req, docs=True)
        monkeypatch.setenv("MCP_ENGINE", "node")
        n = E.run("agent", request=req, docs=True)
        assert not q.get("error"), (req, q)
        assert _strip(q) == _strip(n), req
    for a in AMENDS:
        monkeypatch.setenv("MCP_ENGINE", "quickjs")
        q = E.run("amend", **a, docs=True)
        monkeypatch.setenv("MCP_ENGINE", "node")
        assert _strip(q) == _strip(E.run("amend", **a, docs=True)), a


def test_quickjs_engine_results(E, monkeypatch):
    monkeypatch.setenv("MCP_ENGINE", "quickjs")
    d = E.run("agent", request="여비규정 제15조의 일비를 3만원으로 올려줘")
    assert d["mode"] == "amend" and d["verification"]["ok"] and "별표 2를 별지와 같이 한다." in d["amendment_text"]
    assert "30,000" in d["amendment_text"]                                              # 천 단위 쉼표(toLocaleString) — 브라우저와 같다
    d = E.run("amend", slug="여비규정", changes=[{"article": "제99조", "body": "x"}])
    assert "제99조" in d["error"]


def test_engine_bridge_blocks(E):
    assert E.allowed("GET", "/api/regagent/catalog") and E.allowed("POST", "/api/law/articles?name=x")
    for m, u in [("POST", "/api/regagent/ledger"), ("POST", "/api/regs/upload"), ("GET", "https://example.com/api/regagent/x"),
                 ("GET", "/api/regagent/../regs/upload"), ("DELETE", "/api/regagent/catalog"), ("GET", "//evil/api/regagent/x"),
                 ("GET", "/api/mcp"), ("GET", "/api/ai/models")]:
        assert not E.allowed(m, u), (m, u)
    run = E._run_quickjs
    assert run({}, script="fetch('https://example.com/x').then(r=>r.json()).then(d=>{__out=JSON.stringify(d)})")["success"] is False
    assert run({}, script="fetch('/api/regagent/ledger',{method:'POST',body:'{}'}).then(r=>r.json()).then(d=>{__out=JSON.stringify(d)})")["success"] is False
    ok = run({}, script="fetch('/api/regagent/catalog').then(r=>r.json()).then(d=>{__out=JSON.stringify({n:d.regs.length})})")
    assert ok["n"] > 100


def test_engine_guards(E, monkeypatch):
    run = E._run_quickjs
    # 가상 시계: 대기(setInterval·setTimeout)는 실제로 기다리지 않고 순서대로 돈다
    assert run({}, script="new Promise(r=>{ const t=setInterval(()=>{},300); setTimeout(()=>{clearInterval(t); r(1)}, 60000) }).then(()=>{__out='\"ok\"'})") == "ok"
    assert "끝나지 않는" in run({}, script="setInterval(()=>{},10)")["error"]
    assert "결과를 내지" in run({}, script="new Promise(()=>{})")["error"]
    monkeypatch.setattr(E, "EVAL_LIMIT", 1)
    r = run({}, script="for(;;){}")                                                      # 끝나지 않는 계산은 끊는다
    assert "멈췄습니다" in r["error"]
    monkeypatch.setattr(E, "MAX_TICKS", 50)
    assert "끝나지 않는" in run({}, script="(function f(){ setTimeout(f, 1); })()")["error"]
