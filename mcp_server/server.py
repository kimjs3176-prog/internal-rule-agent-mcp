"""규정 제·개정 에이전트 — MCP(Model Context Protocol) 서버.

Claude·ChatGPT·Gemini·사내 모델 등 MCP 를 지원하는 AI 도우미가 이 에이전트를 “도구”로 쓰게 한다.
웹 화면과 같은 엔진·같은 내규 데이터를 쓰며, 별도 패키지 없이 표준 입출력(stdio) JSON-RPC 로 동작한다.

실행: python mcp_server/server.py        (AI 도우미의 MCP 설정에 이 명령을 등록 — docs/MCP.md)
  - 기관 설정·내규 위치는 웹 서비스와 같은 환경변수(ORG_CONFIG, REG_DIR, REG_MANIFEST, LAW_OC 등)를 따른다.
  - 개정문·신구조문대비표·에이전트 도구는 Node.js 18 이상이 필요하다(화면 엔진 assets/reg_agent.js 를 그대로 돌린다).
  - 문서 저장(output_dir)은 지정한 폴더에만 쓴다. 그 밖의 도구는 내규를 읽기만 한다.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 표준 출력은 MCP 메시지 전용이다. 서버 코드가 찍는 print·로그는 모두 표준 오류로 보낸다.
_PROTO = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8", newline="\n", write_through=True)
os.dup2(2, 1)
sys.stdout = sys.stderr

import api_server  # noqa: E402  (웹 서비스와 같은 앱·블루프린트·데이터)

APP = api_server.app
APP.config["TESTING"] = True
CLIENT = APP.test_client()
VERSION = "1.0.0"
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine.mjs")
ENGINE_TIMEOUT = int(os.environ.get("MCP_ENGINE_TIMEOUT", "120"))

INSTRUCTIONS = (
    "이 서버는 기관 내규(규정·규칙·지침)의 제·개정을 돕는 ‘규정 제·개정 에이전트’입니다. "
    "답에는 근거를 「내규명」 제N조 형태로 밝히고, 금액·기한은 조문·별표 원문에서 확인한 값만 쓰세요. "
    "개정은 ① get_regulation 으로 현행 조문을 읽고 ② 고친 조문 전문을 amend_regulation 에 넣어 개정문·신구조문대비표·개정문 검증·조문 점검·인용 영향을 받으세요. "
    "한 문장 요청(예: “여비규정 제15조의 일비를 3만원으로 올려줘”)은 run_agent 가 규칙으로 끝까지 처리합니다. "
    "검증 결과(verification.ok=false)나 점검 오류가 있으면 사용자에게 그대로 알리세요."
)


# ── 웹 서비스 API 를 그대로 부른다(같은 프로세스, 네트워크 없음) ───────────────────────
def _get(path, **q):
    r = CLIENT.get(path, query_string={k: v for k, v in q.items() if v not in (None, "")})
    return r.get_json(silent=True) or {"success": False, "error": f"응답 오류({r.status_code})"}


def _post(path, body):
    r = CLIENT.post(path, json=body)
    return r.get_json(silent=True) or {"success": False, "error": f"응답 오류({r.status_code})"}


def _find(name):
    """내규명(일부만 적어도 됨) 또는 slug → 내규 하나. 없으면 비슷한 이름 후보."""
    name = str(name or "").strip().strip("「」 ")
    cat = _get("/api/regagent/catalog").get("regs", [])
    for r in cat:
        if name in (r["slug"], r["title"]):
            return r, []
    key = name.replace(" ", "")
    hits = [r for r in cat if key and key in r["title"].replace(" ", "")]
    if len(hits) == 1:
        return hits[0], []
    return None, [r["title"] for r in hits][:8]                # 여러 개면 고르게 후보를 준다


# ── 화면 엔진(Node) — 에이전트·개정문 도구가 쓴다. 엔진은 같은 컴퓨터의 내부 주소로 API 를 부른다 ──
_HTTP = {}


def _base():
    if "base" not in _HTTP:
        import logging
        from werkzeug.serving import make_server
        logging.getLogger("werkzeug").setLevel(logging.WARNING)      # 내부 주소 요청 기록은 남기지 않는다
        srv = make_server("127.0.0.1", 0, APP, threaded=True)        # 같은 컴퓨터 안에서만(127.0.0.1, 빈 포트)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        _HTTP["base"] = f"http://127.0.0.1:{srv.server_port}"
    return _HTTP["base"]


def _engine(op, **kw):
    node = shutil.which("node")
    if not node:
        return {"error": "이 도구는 Node.js 18 이상이 필요합니다(화면 엔진을 그대로 씁니다). Node.js 를 설치한 뒤 다시 시도하세요."}
    try:
        p = subprocess.run([node, ENGINE], input=json.dumps({"op": op, "base": _base(), **kw}, ensure_ascii=False),
                           capture_output=True, text=True, timeout=ENGINE_TIMEOUT, encoding="utf-8")
    except subprocess.TimeoutExpired:
        return {"error": f"엔진이 {ENGINE_TIMEOUT}초 안에 끝나지 않았습니다."}
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return {"error": "엔진 응답을 읽지 못했습니다.", "detail": (p.stderr or "")[-500:]}


def _outdir(d):
    if not d:
        return None
    d = os.path.abspath(os.path.expanduser(str(d)))
    os.makedirs(d, exist_ok=True)
    return d


# ── 도구 ──────────────────────────────────────────────────────────────────────
def t_search_regulations(query, limit=10):
    d = _get("/api/regagent/regs/search", q=query)
    if not d.get("success"):
        return d
    out = []
    for r in d.get("regs", [])[: max(1, min(int(limit or 10), 30))]:
        out.append({"regulation": _title(r["slug"]), "slug": r["slug"], "hits": r.get("hits"),
                    "articles": [{"article": f"제{a['no']}조", "title": a["title"], "snippet": a["snip"]} for a in r.get("arts", [])[:5]]})
    return {"query": d.get("q"), "count": len(out), "results": out}


def _title(slug):
    for r in _get("/api/regagent/catalog").get("regs", []):
        if r["slug"] == slug:
            return r["title"]
    return slug


def t_list_regulations(category=""):
    regs = _get("/api/regagent/catalog").get("regs", [])
    if category:
        regs = [r for r in regs if r.get("category") == category]
    return {"count": len(regs), "regulations": [{"regulation": r["title"], "category": r.get("category"), "revision": r.get("revision"),
                                                  "articles": r.get("live")} for r in regs]}


def t_get_regulation(regulation, articles=None, include_appendix=False):
    r, cand = _find(regulation)
    if not r:
        return {"error": f"「{regulation}」을(를) 찾지 못했습니다.", "candidates": cand}
    d = _get("/api/regagent/articles", slug=r["slug"])
    if not d.get("success"):
        return d
    want = {str(a).replace("제", "").replace("조", "").strip() for a in (articles or []) if str(a).strip()}
    arts = [a for a in d["articles"] if not want or a["no"] in want]
    out = {"regulation": d["title"], "category": d.get("category"), "revision": d.get("revision"),
           "article_count": len(d["articles"]),
           "articles": [{"article": f"제{a['no']}조", "title": a.get("title", ""), "deleted": bool(a.get("deleted")), "body": a.get("body", "")} for a in arts],
           "appendices": [x.get("id") for x in d.get("appendix", [])]}
    if want and not arts:
        out["note"] = f"요청한 조({', '.join(sorted(want))})가 없습니다."
    if include_appendix:
        out["appendix_text"] = [{"id": x.get("id"), "head": x.get("head", ""), "body": x.get("body", "")} for x in d.get("appendix", [])]
    return out


def t_check_regulation(regulation="", text="", title=""):
    if text:
        d = _post("/api/regagent/lint", {"text": text, "title": title or "검토안"})
    else:
        r, cand = _find(regulation)
        if not r:
            return {"error": f"「{regulation}」을(를) 찾지 못했습니다.", "candidates": cand}
        d = _post("/api/regagent/lint", {"slug": r["slug"]})
    if not d.get("success"):
        return d
    iss = d.get("issues", [])
    lv = {"error": "오류", "warn": "주의", "info": "표기 제안"}
    return {"regulation": d.get("reg") or title or "검토안", "errors": sum(i["level"] == "error" for i in iss), "warnings": sum(i["level"] == "warn" for i in iss),
            "suggestions": sum(i["level"] == "info" for i in iss),
            "issues": [{"level": lv.get(i["level"], i["level"]), "article": f"제{i['no']}조" if i.get("no") else "", "message": i["msg"], "fix": i.get("fix", "")} for i in iss[:60]]}


def t_health_check(top=10):
    d = _post("/api/regagent/health", {})
    if not d.get("success"):
        return d
    rows = sorted([r for r in d.get("rows", []) if r.get("score") is not None], key=lambda r: r["score"])[: max(1, min(int(top or 10), 30))]
    return {"regulations": d.get("count"), "average_score": d.get("avg"), "grades": d.get("grades"), "with_issues": d.get("with_issues"),
            "with_errors": d.get("with_errors"), "issue_total": d.get("issue_total"), "not_revised_3y": d.get("old_regs"),
            "lowest": [{"regulation": r["title"], "score": r["score"], "grade": r["grade"], "revision": r.get("revision"),
                        "reasons": [x if isinstance(x, str) else x.get("t") or x.get("msg") or json.dumps(x, ensure_ascii=False) for x in r.get("reasons", [])][:6]} for r in rows]}


def t_citation_impact(regulation, articles):
    r, cand = _find(regulation)
    if not r:
        return {"error": f"「{regulation}」을(를) 찾지 못했습니다.", "candidates": cand}
    nos = [str(a).replace("제", "").replace("조", "").strip() for a in (articles or [])]
    d = _post("/api/regagent/impact", {"slug": r["slug"], "nos": nos, "moves": {}})
    if not d.get("success"):
        return d
    return {"regulation": r["title"], "summary": d.get("summary"),
            "same_regulation": [{"article": f"제{h['no']}조", "title": h.get("title"), "cites": h.get("text"), "snippet": h.get("snippet"), "suggest": h.get("suggest")} for h in d.get("inner", [])],
            "other_regulations": d.get("outer", []), "appendices": d.get("appendix", []), "mentions": d.get("mentions", [])}


def t_upper_law_impact(law, articles=None, old_text="", new_text=""):
    d = _post("/api/regagent/upper", {"law": law, "arts": articles or [], "old": old_text, "new": new_text})
    if not d.get("success"):
        return d
    return {"law": d.get("law"), "candidates": [{"regulation": c.get("reg"), "article": f"제{c['no']}조", "body": c.get("body"), "score": c.get("score"),
                                                 "cites": c.get("cites")} for c in d.get("candidates", [])[:30]],
            "count": d.get("count"), "removed_terms": d.get("removed_terms")}


def t_bulk_rename(old, new, output_dir=""):
    d = _post("/api/regagent/bulk", {"old": old, "new": new, "whole": True})
    if not d.get("success"):
        return d
    return {"old": d["old"], "new": d["new"], "regulations": d["reg_count"], "places": d["total"],
            "amendments": [{"regulation": r.get("reg") or r.get("title"), "amendment_text": r.get("amend_text"),
                            "places": [loc for a in r.get("articles", []) for loc in a.get("locs", [])]} for r in d.get("regs", [])]}


def t_advise(question, regulation=""):
    body = {"question": question}
    if regulation:
        r, cand = _find(regulation)
        if not r:
            return {"error": f"「{regulation}」을(를) 찾지 못했습니다.", "candidates": cand}
        body["slug"] = r["slug"]
    d = _post("/api/regagent/advise", body)
    if not d.get("success"):
        return d
    return {k: d.get(k) for k in ("question", "answer", "conclusion", "basis", "conditions", "caveats", "laws", "followups") if d.get(k)}


def t_run_agent(request, output_dir="", format="hwpx"):
    return _engine("agent", request=request, output_dir=_outdir(output_dir), format=format)


def t_amend_regulation(regulation, changes, appendix_changes=None, addenda="", reason="", effective="", output_dir="", format="hwpx"):
    r, cand = _find(regulation)
    if not r:
        return {"error": f"「{regulation}」을(를) 찾지 못했습니다.", "candidates": cand}
    return _engine("amend", slug=r["slug"], changes=changes or [], appendix_changes=appendix_changes or [], addenda=addenda,
                   reason=reason, effective=effective, output_dir=_outdir(output_dir), format=format)


_STR = {"type": "string"}
_SAVE = {"output_dir": {"type": "string", "description": "문서 세트(심의안건서·개정문·신구조문대비표·이유서 등)를 저장할 폴더. 비우면 저장하지 않는다."},
         "format": {"type": "string", "enum": ["hwpx", "docx"], "description": "저장 형식: 한글(hwpx, 기본) 또는 Word(docx)"}}

TOOLS = [
    ("run_agent", "에이전트 실행(한 문장 요청)", t_run_agent,
     "한 문장 요청을 웹 화면의 에이전트와 똑같이 끝까지 처리한다(AI 없이 규칙 기반). 예: “여비규정 제15조의 일비를 3만원으로 올려줘”(개정), "
     "“여비규정 제20조를 삭제해줘”, “모든 내규에서 기획운영본부를 경영기획본부로 바꿔줘”(일괄 정비), “업무용 드론 운영지침을 새로 만들어줘”(제정), 내규 질의(자문). "
     "단계별 작업 내역과 결론, 개정이면 개정문·신구조문대비표·개정문 검증, 제정이면 조문 초안을 돌려준다. 자유로운 문장 수정은 amend_regulation 을 쓴다.",
     {"type": "object", "properties": {"request": {"type": "string", "description": "하고 싶은 일을 한 문장으로"}, **_SAVE}, "required": ["request"]}),
    ("amend_regulation", "개정안 → 개정문·대비표·검증", t_amend_regulation,
     "고친 조문(전문)을 받아 개정문(“○○ 일부를 다음과 같이 개정한다.”), 신구조문대비표, 개정문 검증(개정문을 현행에 다시 적용해 수정안과 같은지), "
     "조문 점검(인용 오류·항 번호·표기), 인용 영향(이 조를 인용하는 다른 조·내규)을 돌려준다. 먼저 get_regulation 으로 현행 조문을 읽고, 바꿀 조의 본문 전체를 적는다.",
     {"type": "object", "properties": {
         "regulation": {"type": "string", "description": "내규명(예: 여비규정)"},
         "changes": {"type": "array", "description": "고칠 조문들", "items": {"type": "object", "properties": {
             "article": {"type": "string", "description": "조 번호(예: 제15조, 15, 3의2)"},
             "type": {"type": "string", "enum": ["modify", "insert", "delete"], "description": "개정(기본)·신설·삭제"},
             "title": {"type": "string", "description": "조 제목(비우면 현행 제목)"},
             "body": {"type": "string", "description": "고친 뒤의 조 본문 전체(항은 ①② 등으로 줄을 나눈다). 삭제면 비운다."}},
             "required": ["article"]}},
         "appendix_changes": {"type": "array", "description": "고칠 별표(선택)", "items": {"type": "object", "properties": {
             "id": {"type": "string", "description": "예: 별표 2"}, "head": _STR, "body": {"type": "string", "description": "고친 뒤의 별표 본문 전체"}}, "required": ["id", "body"]}},
         "addenda": {"type": "string", "description": "부칙 문장(선택, 비우면 “이 규정은 발령한 날부터 시행한다.”)"},
         "reason": {"type": "string", "description": "개정 이유(선택, 이유서·검토 보고서에 씀)"},
         "effective": {"type": "string", "description": "시행일(선택, 예: 2027. 1. 1.)"},
         **_SAVE}, "required": ["regulation", "changes"]}),
    ("search_regulations", "내규 검색", t_search_regulations,
     "낱말로 내규 조문을 찾는다. 낱말이 많이 나온 내규 순으로 조 번호·제목·발췌를 돌려준다.",
     {"type": "object", "properties": {"query": {"type": "string", "description": "찾을 낱말(예: 일비, 연차휴가)"}, "limit": {"type": "integer", "description": "최대 내규 수(기본 10)"}}, "required": ["query"]}),
    ("list_regulations", "내규 목록", t_list_regulations, "등록된 내규 전체 목록(이름·종류·개정 표기·조 수).",
     {"type": "object", "properties": {"category": {"type": "string", "description": "종류만 고르기(정관·규정·규칙·지침 등, 선택)"}}}),
    ("get_regulation", "내규 조문 읽기", t_get_regulation, "내규의 조문 원문(전체 또는 고른 조)과 별표 목록. 금액·일수는 별표에 있을 수 있으니 include_appendix 로 함께 읽는다.",
     {"type": "object", "properties": {"regulation": {"type": "string", "description": "내규명(일부만 적어도 됨)"},
                                       "articles": {"type": "array", "items": _STR, "description": "읽을 조(예: [\"제15조\", \"16\"]), 비우면 전체"},
                                       "include_appendix": {"type": "boolean", "description": "별표 본문도 함께"}}, "required": ["regulation"]}),
    ("check_regulation", "조문 점검", t_check_regulation,
     "내규 하나(또는 붙여 넣은 조문 글)의 형식 오류를 점검한다: 없는·삭제된 조문 인용, 항·호 번호, 현행 목록에 없는 내규명, 옛 명칭, 표기.",
     {"type": "object", "properties": {"regulation": {"type": "string", "description": "점검할 내규명"}, "text": {"type": "string", "description": "또는 점검할 조문 글(제1조(목적) …)"},
                                       "title": {"type": "string", "description": "text 의 내규명(선택)"}}}),
    ("health_check", "내규 건강검진", t_health_check, "기관 내규 전체를 진단해 평균 점수·등급 분포·문제가 있는 내규 수와 점수가 낮은 내규(이유 포함)를 돌려준다.",
     {"type": "object", "properties": {"top": {"type": "integer", "description": "점수가 낮은 내규 몇 개를 보일지(기본 10)"}}}),
    ("citation_impact", "인용 영향", t_citation_impact, "어떤 조를 고치거나 지울 때 그 조를 인용하는 같은 내규의 조·다른 내규·별표를 찾는다.",
     {"type": "object", "properties": {"regulation": _STR, "articles": {"type": "array", "items": _STR, "description": "고칠 조(예: [\"제20조\"])"}}, "required": ["regulation", "articles"]}),
    ("upper_law_impact", "상위법 개정 영향", t_upper_law_impact, "상위법(법령) 개정 시 그 법을 인용하는 내규 조문 후보를 찾는다. 개정 전·후 조문을 주면 사라진 용어도 짚는다.",
     {"type": "object", "properties": {"law": {"type": "string", "description": "법령명(예: 공공기관의 운영에 관한 법률)"}, "articles": {"type": "array", "items": _STR},
                                       "old_text": {"type": "string", "description": "개정 전 조문(선택)"}, "new_text": {"type": "string", "description": "개정 후 조문(선택)"}}, "required": ["law"]}),
    ("bulk_rename", "일괄 정비(명칭 변경)", t_bulk_rename, "모든 내규에서 용어·조직 명칭을 찾아 바꾸는 정비안: 내규별 개정문과 바뀌는 위치(조사 자동 교정).",
     {"type": "object", "properties": {"old": {"type": "string", "description": "바꿀 말"}, "new": {"type": "string", "description": "새 말"}}, "required": ["old", "new"]}),
    ("advise", "내규 자문", t_advise, "내규 질의에 근거 조문을 찾아 회신 초안을 만든다(AI 없이 근거 조문 중심).",
     {"type": "object", "properties": {"question": _STR, "regulation": {"type": "string", "description": "특정 내규로 좁히기(선택)"}}, "required": ["question"]}),
]
_BY = {t[0]: t for t in TOOLS}


def _tool_list():
    return [{"name": n, "title": ti, "description": desc, "inputSchema": schema} for n, ti, _, desc, schema in TOOLS]


def _call(name, args):
    t = _BY.get(name)
    if not t:
        return {"content": [{"type": "text", "text": f"모르는 도구: {name}"}], "isError": True}
    try:
        res = t[2](**(args or {}))
    except TypeError as e:
        return {"content": [{"type": "text", "text": f"입력값이 맞지 않습니다: {e}"}], "isError": True}
    except Exception as e:  # 도구 오류는 프로토콜 오류가 아니라 결과로 알린다(AI 가 읽고 다시 시도)
        return {"content": [{"type": "text", "text": f"처리 중 오류: {type(e).__name__}: {e}"}], "isError": True}
    err = isinstance(res, dict) and bool(res.get("error")) and len(res) <= 3
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if len(text) > 200000:
        text = text[:200000] + "\n…(길어서 잘랐습니다)"
    out = {"content": [{"type": "text", "text": text}], "isError": err}
    if isinstance(res, dict):
        out["structuredContent"] = res
    return out


def handle(msg):
    """JSON-RPC 메시지 하나 → 응답(알림이면 None)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:                                  # 알림(notifications/initialized 등)에는 답하지 않는다
        return None
    if method == "initialize":
        want = params.get("protocolVersion")
        res = {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0], "capabilities": {"tools": {"listChanged": False}},
               "serverInfo": {"name": "reg-agent", "title": "규정 제·개정 에이전트", "version": VERSION}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": _tool_list()}
    elif method == "tools/call":
        res = _call(params.get("name"), params.get("arguments"))
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def _send(obj):
    _PROTO.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _PROTO.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        if isinstance(msg, list):                     # 묶음 요청(2025-03-26 이전 판)
            out = [r for r in (handle(m) for m in msg) if r is not None]
            if out:
                _send(out)
        else:
            r = handle(msg)
            if r is not None:
                _send(r)


if __name__ == "__main__":
    main()
