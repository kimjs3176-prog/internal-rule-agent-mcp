"""원격 MCP — 배포한 웹 서비스의 /mcp 주소(Streamable HTTP)로 AI 도우미가 이 에이전트를 도구로 쓴다.

claude.ai·ChatGPT 의 커넥터, Claude Code(--transport http), VS Code·Cursor 등에 주소만 넣으면 된다(설치 없음).
  - 방식: 하나의 주소에 JSON-RPC 를 POST 한다(MCP 2025-06-18·2025-03-26 Streamable HTTP). 응답은 JSON(또는 SSE 한 건).
    세션을 두지 않는다(요청마다 독립 — 서버리스에서도 된다). 서버가 먼저 보내는 알림 흐름(GET)은 없다(405).
  - 읽기 전용: 내규 원문은 읽기만 하고 파일을 쓰지 않는다. 문서 세트는 내려받기 링크(/api/mcp/doc/…)로 준다.
  - 환경변수
      MCP_HTTP=off            원격 MCP 를 끈다(기본 켜짐)
      MCP_TOKEN=…             설정하면 Authorization: Bearer <값> 이 있어야 쓴다(사내 배포용). 내려받기 링크도 이 값으로 서명한다.
      MCP_ALLOWED_ORIGINS=…   브라우저에서 직접 부를 때 허용할 출처(쉼표 구분). 같은 주소와 ALLOWED_ORIGINS(화면 CORS)는 늘 허용
      MCP_PUBLIC_URL=…        링크에 쓸 공개 주소(프록시 뒤라 주소가 다르게 보일 때)
"""
import hmac
import json
import os
import re
from urllib.parse import quote, urlsplit

from flask import Blueprint, Response, request

from . import core

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
    """브라우저가 보낸 Origin 확인(DNS 재바인딩·다른 사이트의 몰래 호출 막기). Origin 이 없으면(서버 간 호출) 통과."""
    if not origin:
        return True
    o = origin.strip().rstrip("/")
    if urlsplit(o).netloc and urlsplit(o).netloc == (request.headers.get("X-Forwarded-Host") or request.host):
        return True
    extra = [x.strip().rstrip("/") for x in (os.environ.get("MCP_ALLOWED_ORIGINS") or "").split(",") if x.strip()]
    if o in extra:
        return True
    try:
        import api_server                                   # 화면 CORS 허용 출처와 같은 목록
        for p in getattr(api_server, "_cors_origins", []):
            if (hasattr(p, "match") and p.match(o)) or p == o:
                return True
    except Exception:
        pass
    return False


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


def _rpc_error(status, code, message, origin="", extra=None):
    r = Response(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}}, ensure_ascii=False),
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
    body = json.dumps(out, ensure_ascii=False)
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
