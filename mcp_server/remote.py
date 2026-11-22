"""원격 MCP — 배포한 웹 서비스의 /mcp 주소(Streamable HTTP)로 AI 도우미가 이 에이전트를 도구로 쓴다.

claude.ai·ChatGPT 의 커넥터, Claude Code(--transport http), VS Code·Cursor 등에 주소만 넣으면 된다(설치 없음).
  - 방식: 하나의 주소에 JSON-RPC 를 POST 한다(MCP 2025-06-18·2025-03-26 Streamable HTTP). 응답은 JSON(또는 SSE 한 건).
    세션을 두지 않는다(요청마다 독립 — 서버리스에서도 된다). 서버가 먼저 보내는 알림 흐름(GET)은 없다(405).
  - 읽기 전용: 내규 원문은 읽기만 하고 파일을 쓰지 않는다. 문서 세트는 내려받기 링크(/api/mcp/doc/…)로 준다.
  - 환경변수
      MCP_HTTP=off            원격 MCP 를 끈다(기본 켜짐)
      MCP_TOKEN=…             설정하면 Authorization: Bearer <값> 이 있어야 쓴다(사내 배포용). 내려받기 링크도 이 값으로 서명한다.
      MCP_ALLOWED_ORIGINS=…   브라우저에서 직접 부를 때 허용할 출처(쉼표 구분). ALLOWED_ORIGINS(화면 CORS)·MCP_PUBLIC_URL 은 늘 허용
      MCP_PUBLIC_URL=…        링크에 쓸 공개 주소(프록시 뒤라 주소가 다르게 보일 때)
      MCP_PER_MIN=120         남용 방지: 같은 접속 주소(IP)에서 1분에 받는 호출 수(MCP 호출·문서 내려받기). 넘으면 429
      MCP_TRUST_PROXY=1       Vercel 밖에서 프록시(nginx 등) 뒤에 둘 때만: X-Forwarded-For 의 첫 주소를 접속 주소로 센다
"""
import hmac
import json
import os
import re
import threading
import time
from urllib.parse import quote, urlsplit

from flask import Blueprint, Response, request

from . import core, engine

bp = Blueprint("mcp_remote", __name__)
MAX_BODY = 1_000_000
MAX_BATCH = 20
_HEADERS = "Content-Type, Authorization, Mcp-Session-Id, MCP-Protocol-Version, Last-Event-ID"


def enabled() -> bool:
    return (os.environ.get("MCP_HTTP") or "on").strip().lower() not in ("0", "off", "false", "no")


def _public_base():
    env = (os.environ.get("MCP_PUBLIC_URL") or "").strip().rstrip("/")
    if env:
        return env
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "http").split(",")[0].strip()
    host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
    return f"{proto}://{host}" if host else ""


def _origin_ok(origin: str) -> bool:
    """브라우저가 보낸 Origin 확인(DNS 재바인딩·다른 사이트의 몰래 호출 막기). Origin 이 없으면(서버 간 호출 — claude.ai·ChatGPT·Claude Code) 통과.
    요청의 Host 와 같은지로는 판단하지 않는다(재바인딩에서는 공격 사이트의 Origin 과 Host 가 늘 같다). 허용 목록에 있는 출처만 받는다."""
    if not origin:
        return True
    o = origin.strip().rstrip("/")
    allow = [x.strip().rstrip("/") for x in (os.environ.get("MCP_ALLOWED_ORIGINS") or "").split(",") if x.strip()]
    pub = (os.environ.get("MCP_PUBLIC_URL") or "").strip()
    if pub:
        u = urlsplit(pub)
        allow.append(f"{u.scheme}://{u.netloc}")
    if o in allow:
        return True
    try:
        for p in getattr(engine.server_module(), "_cors_origins", []):     # 화면 CORS 허용 출처와 같은 목록(localhost·배포 주소)
            if (hasattr(p, "match") and p.match(o)) or p == o:
                return True
    except Exception:
        pass
    return False


def _dump(obj) -> str:
    """응답 JSON — 한글은 그대로 두되, 글에 깨진 유니코드(짝 없는 대리 문자)가 섞이면 \\u 꼴로(500 오류 대신)."""
    s = json.dumps(obj, ensure_ascii=False)
    try:
        s.encode("utf-8")
        return s
    except UnicodeEncodeError:
        return json.dumps(obj)


def _auth_ok() -> bool:
    tok = (os.environ.get("MCP_TOKEN") or "").strip()
    if not tok:
        return True
    h = request.headers.get("Authorization", "")
    m = re.match(r"(?i)^bearer\s+(.+)$", h.strip())
    return bool(m) and hmac.compare_digest(m.group(1).strip().encode(), tok.encode())


def _cors(resp, origin):
    if origin and _origin_ok(origin):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Expose-Headers"] = "Mcp-Session-Id, MCP-Protocol-Version"
        resp.headers.add("Vary", "Origin")
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ── 남용 방지: 접속 주소(IP)별 분당 호출 상한 ──────────────────────────────────
# 인스턴스 메모리에만 센다(주소는 저장하지 않고 이 판단에만 쓴다). 서버리스는 인스턴스마다 따로 세므로 대략의 상한이다.
# claude.ai·ChatGPT 커넥터는 그 회사 서버에서 부르므로, 그 사용자들은 몇 개의 주소를 함께 쓴다 — 상한을 넉넉히 둔다.
_RATE: dict = {}
_RATE_LOCK = threading.Lock()


def _per_min() -> int:
    try:
        return max(10, int(os.environ.get("MCP_PER_MIN") or 120))
    except ValueError:
        return 120


def _client_ip() -> str:
    # Vercel 은 앞단에서 X-Forwarded-For 를 실제 접속 주소로 채운다. 그 밖에서는 요청자가 이 머리글을 꾸밀 수 있으므로
    # 프록시 뒤라고 밝힌 때(MCP_TRUST_PROXY=1)만 믿고, 아니면 실제 연결 주소(remote_addr)를 쓴다.
    if os.environ.get("VERCEL") or (os.environ.get("MCP_TRUST_PROXY") or "").strip() == "1":
        v = (request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP") or "").split(",")[0].strip()
        if v:
            return v
    return request.remote_addr or ""


def rate_limited() -> bool:
    """이번 1분 동안 이 주소의 호출이 상한을 넘었는가(세면서 판단)."""
    now = int(time.time() // 60)
    k = (_client_ip(), now)
    with _RATE_LOCK:
        n = _RATE.get(k, 0) + 1
        _RATE[k] = n
        if len(_RATE) > 5000:
            for kk in [x for x in _RATE if x[1] < now]:
                _RATE.pop(kk, None)
    return n > _per_min()


def _retry_after() -> str:
    return str(max(1, 60 - int(time.time()) % 60))


def _rpc_error(status, code, message, origin="", extra=None):
    r = Response(_dump({"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}}),
                 status=status, mimetype="application/json")
    for k, v in (extra or {}).items():
        r.headers[k] = v
    return _cors(r, origin)


@bp.route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
@bp.route("/mcp/", methods=["GET", "POST", "DELETE", "OPTIONS"])
@bp.route("/api/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
def mcp_endpoint():
    if not enabled():
        return Response("Not Found", status=404)
    origin = request.headers.get("Origin", "")
    if not _origin_ok(origin):
        return _rpc_error(403, -32000, "Forbidden: 허용되지 않은 출처(Origin)입니다. 관리자가 MCP_ALLOWED_ORIGINS 에 넣어야 합니다.")
    if request.method == "OPTIONS":                         # 브라우저 사전 확인(CORS preflight)
        r = Response(status=204)
        r.headers["Access-Control-Allow-Methods"] = "POST, GET, DELETE, OPTIONS"
        r.headers["Access-Control-Allow-Headers"] = _HEADERS
        r.headers["Access-Control-Max-Age"] = "600"
        return _cors(r, origin)
    if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):   # 브라우저로 주소를 열면 연결 안내
        return _guide_page()
    # 호출 상한은 토큰 확인보다 먼저 센다 — 틀린 토큰 요청도 세어 MCP_TOKEN 무차별 대입을 늦춘다
    if request.method == "POST" and rate_limited():
        return _rpc_error(429, -32000, "요청이 너무 많습니다. 잠시 후 다시 시도하세요.", origin, {"Retry-After": _retry_after()})
    if not _auth_ok():
        return _rpc_error(401, -32001, "Unauthorized: Authorization: Bearer <MCP_TOKEN> 이 필요합니다.", origin,
                          {"WWW-Authenticate": 'Bearer realm="reg-agent"'})
    if request.method in ("GET", "DELETE"):                 # 서버 알림 흐름(SSE)·세션이 없다
        r = _rpc_error(405, -32000, "Method Not Allowed: 이 서버는 POST 만 받습니다(세션·알림 흐름 없음).", origin)
        r.headers["Allow"] = "POST, OPTIONS"
        return r
    ver = request.headers.get("MCP-Protocol-Version", "").strip()
    if ver and ver not in core.PROTOCOLS:
        return _rpc_error(400, -32600, f"Bad Request: 지원하지 않는 MCP-Protocol-Version({ver[:20]}). 지원: {', '.join(core.PROTOCOLS)}", origin)
    if (request.content_length or 0) > MAX_BODY:
        return _rpc_error(413, -32600, "요청이 너무 큽니다(1MB 이하).", origin)
    raw = request.get_data(cache=False)
    if len(raw) > MAX_BODY:
        return _rpc_error(413, -32600, "요청이 너무 큽니다(1MB 이하).", origin)
    try:
        msg = json.loads(raw.decode("utf-8"))
    except Exception:
        return _rpc_error(400, -32700, "Parse error", origin)
    base = _public_base()
    if isinstance(msg, list):                               # 묶음(2025-03-26 판까지)
        if not msg or len(msg) > MAX_BATCH:
            return _rpc_error(400, -32600, "Invalid Request: 묶음은 1~20건입니다.", origin)
        out = [x for x in (core.handle(m, mode="http", base=base) for m in msg) if x is not None]
    else:
        out = core.handle(msg, mode="http", base=base)
    if not out:                                             # 알림·응답만 왔으면 본문 없이 202
        return _cors(Response(status=202), origin)
    body = _dump(out)
    accept = request.headers.get("Accept", "")
    if "text/event-stream" in accept and "application/json" not in accept and "*/*" not in accept:
        r = Response(f"event: message\ndata: {body}\n\n", mimetype="text/event-stream")    # SSE 만 받는 클라이언트 — 응답 한 건을 보내고 닫는다
    else:
        r = Response(body, mimetype="application/json")
    return _cors(r, origin)


@bp.route("/api/mcp/doc/<fmt>/<token>")
def mcp_doc(fmt, token):
    """MCP 결과의 내려받기 링크 — 링크에 담긴 요청을 다시 실행해 한글(hwpx)·Word(docx) 문서 세트를 만든다."""
    if not enabled():
        return Response("Not Found", status=404)
    if fmt not in ("hwpx", "docx"):
        return Response("형식은 hwpx·docx 중 하나입니다.", status=404, mimetype="text/plain; charset=utf-8")
    if rate_limited():                                   # 링크를 열면 엔진을 다시 돌리므로 같은 상한으로 센다
        r = Response("요청이 너무 많습니다. 잠시 후 다시 시도하세요.", status=429, mimetype="text/plain; charset=utf-8")
        r.headers["Retry-After"] = _retry_after()
        return r
    try:
        op, inp = core.read_token(token)
    except PermissionError as e:
        return Response(str(e), status=403, mimetype="text/plain; charset=utf-8")
    except ValueError as e:
        return Response(str(e), status=400, mimetype="text/plain; charset=utf-8")
    data, name, err = core.doc_file(op, inp, fmt)
    if err or not data:
        return Response(err or "문서를 만들지 못했습니다.", status=422, mimetype="text/plain; charset=utf-8")
    mime = "application/hwp+zip" if fmt == "hwpx" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    r = Response(data, mimetype=mime)
    ascii_name = re.sub(r"[^A-Za-z0-9.\-]", "_", name.encode("ascii", "ignore").decode())
    if not re.search(r"[A-Za-z0-9]", ascii_name.rsplit(".", 1)[0]):
        ascii_name = f"reg-agent.{fmt}"                     # 한글만 있는 이름은 filename* 이 쓰이고, 옛 브라우저용 이름은 영문으로
    r.headers["Content-Disposition"] = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    r.headers["Cache-Control"] = "no-store"
    return r


def _guide_page():
    """브라우저로 MCP 주소를 열었을 때의 안내 — 이 주소를 AI 도우미에 넣는 방법과 도구 목록. MCP 클라이언트는 POST 라 영향이 없다."""
    from html import escape as _h
    url = (_public_base() or request.host_url.rstrip("/")) + "/mcp"
    only = core.mcp_only()
    title = "범용 규정 제·개정 에이전트 MCP" if only else "규정 제·개정 에이전트 MCP"
    lead = ("어느 기관의 사규·내규·자치법규든, 알리오 공시 규정이나 원문만 있으면 개정문·신구조문대비표·개정문 검증·조문 점검·제출 문서를 만듭니다."
            if only else "이 기관에 등록된 내규로 개정·제정·점검·건강검진을 하고, 다른 기관 사규도 원문·알리오로 다룹니다.")
    tools = "".join(f"<li><code>{_h(t['name'])}</code> {_h(t['title'])}</li>" for t in core.tool_list())
    ex = ("<li>한국○○공사 여비규정을 알리오에서 찾아 일비를 3만원으로 올리는 개정안 만들어 줘.</li>"
          "<li>(규정 원문을 붙여 넣고) 이 규정 형식 점검해 줘. 우리는 ○○재단이고 기관장은 이사장이야.</li>"
          + ("<li>공공기관들의 경조휴가 일수를 비교해 줘.</li>" if only else "<li>유관 기관들의 경조휴가 일수를 비교해 줘.</li>"))
    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_h(title)}</title><style>
:root{{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--ink:#1d2126;--mu:#575e68;--rule:#e3e6e9;--acc:#256ef4}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b0d11;--card:#121519;--ink:#eceff1;--mu:#a5acb2;--rule:#2c3136;--acc:#6d9df5}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 Pretendard,"Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;word-break:keep-all}}
main{{max-width:760px;margin:0 auto;padding:56px 20px 64px}} h1{{font-size:clamp(26px,4vw,36px);letter-spacing:-.03em;line-height:1.25;margin:0 0 12px;text-wrap:balance}}
p.lead{{color:var(--mu);margin:0 0 28px;text-wrap:balance}} section{{background:var(--card);border:1px solid var(--rule);border-radius:14px;padding:20px 22px;margin:0 0 16px}}
h2{{font-size:16px;margin:0 0 10px}} code{{font:14px ui-monospace,SFMono-Regular,Menlo,monospace}} .url{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.url code{{flex:1;min-width:0;padding:10px 12px;border-radius:10px;background:var(--bg);border:1px solid var(--rule);overflow-wrap:anywhere}}
button{{font:600 14px inherit;padding:10px 16px;border-radius:999px;border:0;background:var(--ink);color:var(--card);cursor:pointer}}
ol,ul{{margin:0;padding-left:20px}} li{{margin:4px 0}} .mu{{color:var(--mu);font-size:14px}}
</style></head><body><main>
<h1>{_h(title)}</h1><p class="lead">{_h(lead)}</p>
<section><h2>연결 주소</h2><div class="url"><code id="u">{_h(url)}</code><button onclick="navigator.clipboard&&navigator.clipboard.writeText(document.getElementById('u').textContent).then(()=>{{this.textContent='복사됨'}})">복사</button></div>
<p class="mu">이 주소는 AI 도우미에 넣는 주소입니다. 브라우저로 여는 화면이 아닙니다.</p></section>
<section><h2>AI 도우미에 등록</h2><ol>
<li><b>claude.ai</b>: 설정 → 커넥터 → 사용자 지정 커넥터 추가 → 이 주소 입력(인증 비움) → 대화창 도구 메뉴에서 켜기</li>
<li><b>ChatGPT</b>: 설정 → 앱·커넥터 → 고급에서 개발자 모드 → 만들기 → 이 주소, 인증 “없음”</li>
<li><b>Claude Code</b>: <code>claude mcp add --transport http reg-agent {_h(url)}</code></li></ol></section>
<section><h2>이렇게 물어보세요</h2><ul>{ex}</ul></section>
<section><h2>도구 {len(core.tool_list())}개</h2><ul>{tools}</ul>
<p class="mu">개정문·대비표·검증·점검·문서는 이 서버의 규칙 엔진이 만듭니다. 받은 원문과 결과는 서버에 저장하지 않습니다.</p></section>
</main></body></html>"""
    r = Response(html, mimetype="text/html")
    r.headers["Cache-Control"] = "no-store"
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r
