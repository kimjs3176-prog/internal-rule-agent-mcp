"""화면 엔진 실행기 — MCP 도구(run_agent·amend_regulation)가 웹 화면과 똑같은 엔진(assets/reg_agent.js)을 돌린다.

두 가지 실행 방식이 있고 결과는 같다(tests/test_mcp_engine.py 가 같은 요청을 둘 다 돌려 견준다).
  - QuickJS(기본): 파이썬 안에서 돈다. Node.js 가 없어도 되고, 서버리스(Vercel)에서도 된다(requirements.txt 의 quickjs).
  - Node.js(대체): QuickJS 를 설치할 수 없을 때(예: Python 3.13 이상에서 빌드 도구가 없을 때) Node.js 18 이상으로 돌린다.
  환경변수 MCP_ENGINE=quickjs|node 로 고를 수 있다(기본 auto: QuickJS 가 있으면 QuickJS).

엔진은 서버 API 를 상대 주소(/api/regagent/…, /api/law/…)로만 부른다. 외부 주소·다른 경로(내규 등록·작업 실적 기록 등)는 막는다.
QuickJS 에서는 같은 프로세스의 Flask 앱을 직접 부르고(네트워크 없음), Node 에서는 127.0.0.1 의 빈 포트에 띄운 내부 서버를 부른다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TIMEOUT = int(os.environ.get("MCP_ENGINE_TIMEOUT", "90") or 90)      # 한 번 실행의 전체 제한(초)
HTTP_TIMEOUT = min(TIMEOUT, 40)                                     # 원격(/mcp): 클라이언트 요청 제한(흔히 60초)·서버리스 함수 제한 안에 답한다
EVAL_LIMIT = 30                                                     # QuickJS: 한 번에 이어서 도는 JS 계산의 제한(초) — 끝나지 않는 계산을 끊는다
MEM_LIMIT = 384 * 1024 * 1024
MAX_TICKS = 20000                                                   # 가상 타이머가 이보다 많이 돌면 끝나지 않는 대기로 본다

_ALLOWED = re.compile(r"^/api/(?:regagent|law)/[\w\-/.%]*$")


def allowed(method: str, url: str) -> bool:
    """엔진이 부를 수 있는 서버 API 인가: 내규·법령 조회 API(GET·POST)만. 작업 실적 기록·등록·외부 주소는 안 된다."""
    path = str(url).split("?", 1)[0]
    return (method in ("GET", "POST") and bool(_ALLOWED.match(path)) and ".." not in path and "//" not in path
            and not path.startswith("/api/regagent/ledger"))


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


_SRC = {}


def _src():
    if not _SRC:
        _SRC["reg"] = _read(os.path.join(ROOT, "assets", "reg_agent.js"))
        _SRC["core"] = _read(os.path.join(HERE, "engine_core.js"))
    return _SRC["reg"], _SRC["core"]


def server_module():
    """웹 서비스 모듈 — `python api_server.py` 로 띄웠으면 __main__ 이 그것이다(다시 불러 두 벌이 되지 않게)."""
    for name in ("api_server", "__main__"):
        m = sys.modules.get(name)
        if m is not None and getattr(m, "app", None) is not None and hasattr(m, "_cors_origins"):
            return m
    import api_server
    return api_server


def app():
    """지금 요청을 받는 Flask 앱(요청 안이면 그 앱, 아니면 웹 서비스 모듈의 앱)."""
    try:
        from flask import current_app, has_app_context
        if has_app_context():
            return current_app._get_current_object()
    except Exception:
        pass
    return server_module().app


_app = app


def local_fetch(method: str, url: str, body=None):
    """같은 프로세스의 Flask 앱에 요청(네트워크 없음) → (상태, 본문 글, Content-Type)."""
    if not allowed(method, url):
        return 403, json.dumps({"success": False, "error": "엔진이 부를 수 없는 주소입니다."}, ensure_ascii=False), "application/json"
    r = _app().test_client().open(url, method=method, data=body, content_type="application/json" if body is not None else None)
    return r.status_code, r.get_data(as_text=True), r.headers.get("Content-Type", "")


# ── QuickJS ──────────────────────────────────────────────────────────────────
# 브라우저 대신 채우는 것: fetch(요청을 줄에 세우고 파이썬이 처리), 가상 시계 타이머, localStorage, 화면 함수 자리.
# JS 가 파이썬을 직접 부르지 않게 해서(줄 세우기) QuickJS 의 계산 시간 제한을 켤 수 있다.
_PRELUDE = r"""
var __out = null, __fq = [], __fseq = 0, __fwait = {}, __now = 0, __tseq = 0, __timers = [];
globalThis.fetch = function (u, o) {
  return new Promise(function (res, rej) {
    var id = ++__fseq; __fwait[id] = { res: res, rej: rej };
    __fq.push({ id: id, url: String(u), method: String((o && o.method) || 'GET').toUpperCase(), body: (o && o.body != null) ? String(o.body) : null });
  });
};
globalThis.__ftake = function () { var q = __fq; __fq = []; return JSON.stringify(q); };
globalThis.__fdeliver = function (id, status, text, ctype) {
  var w = __fwait[id]; delete __fwait[id]; if (!w) return;
  if (status < 0) { w.rej(new TypeError(text)); return; }
  w.res({ ok: status >= 200 && status < 300, status: status, headers: { get: function (k) { return String(k).toLowerCase() === 'content-type' ? ctype : null; } },
          json: function () { return Promise.resolve().then(function () { return JSON.parse(text); }); },
          text: function () { return Promise.resolve(text); } });
};
globalThis.setTimeout = function (f, ms) { var a = [].slice.call(arguments, 2), id = ++__tseq; __timers.push({ id: id, at: __now + Math.max(0, +ms || 0), f: f, a: a }); return id; };
globalThis.setInterval = function (f, ms) { var a = [].slice.call(arguments, 2), id = ++__tseq; var iv = Math.max(1, +ms || 0); __timers.push({ id: id, at: __now + iv, f: f, a: a, iv: iv }); return id; };
globalThis.clearTimeout = globalThis.clearInterval = function (id) { __timers = __timers.filter(function (t) { return t.id !== id; }); };
globalThis.__tick = function () {
  if (!__timers.length) return 0;
  __timers.sort(function (x, y) { return x.at - y.at || x.id - y.id; });
  var t = __timers.shift(); __now = t.at;
  if (t.iv) __timers.push({ id: t.id, at: __now + t.iv, f: t.f, a: t.a, iv: t.iv });
  if (typeof t.f === 'function') t.f.apply(null, t.a); return 1;
};
// QuickJS(2021-03-27)에 없는 것 — 브라우저·Node 와 같은 결과가 나오게 채운다
(function () {
  function group(v) { if (!isFinite(v)) return String(v); var neg = v < 0, r = Math.round(Math.abs(v) * 1000) / 1000, s = String(r).split('.');
    s[0] = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, ','); return (neg && r ? '-' : '') + s.join('.'); }
  Number.prototype.toLocaleString = function () { return group(Number(this)); };
  if (!Array.prototype.at) Object.defineProperty(Array.prototype, 'at', { value: function (i) { i = Math.trunc(i) || 0; if (i < 0) i += this.length; return this[i]; }, writable: true, configurable: true });
  if (!String.prototype.at) Object.defineProperty(String.prototype, 'at', { value: function (i) { i = Math.trunc(i) || 0; if (i < 0) i += this.length; return this.charAt(i) || undefined; }, writable: true, configurable: true });
  if (!Array.prototype.findLast) Object.defineProperty(Array.prototype, 'findLast', { value: function (f, t) { for (var i = this.length - 1; i >= 0; i--) if (f.call(t, this[i], i, this)) return this[i]; }, writable: true, configurable: true });
  if (!Object.hasOwn) Object.hasOwn = function (o, k) { return Object.prototype.hasOwnProperty.call(o, k); };
})();
var __store = {}, __none = function () { return null; };
globalThis.localStorage = { getItem: function (k) { return Object.prototype.hasOwnProperty.call(__store, k) ? __store[k] : null; }, setItem: function (k, v) { __store[k] = String(v); }, removeItem: function (k) { delete __store[k]; } };
globalThis.sessionStorage = { getItem: __none, setItem: function () {}, removeItem: function () {} };
globalThis.document = { getElementById: __none, querySelector: __none, querySelectorAll: function () { return []; }, title: '', body: {}, addEventListener: function () {},
  createElement: function () { return { style: {}, click: function () {}, remove: function () {}, setAttribute: function () {}, appendChild: function () {} }; } };
globalThis.window = { scrollY: 0, scrollTo: function () {}, innerWidth: 1440, addEventListener: function () {} };
globalThis.location = { hash: '' }; globalThis.navigator = {};
globalThis.confirm = function () { return true; }; globalThis.alert = function () {};
globalThis.requestAnimationFrame = function (f) { return setTimeout(f, 0); };
globalThis.escHtml = function (s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); };
globalThis.argAttr = function (s) { return String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;'); };
globalThis.getAiSettings = function () { return {}; };
globalThis._toast = globalThis._copyText = globalThis.openAiModal = function () {};
globalThis.console = { log: function () {}, info: function () {}, warn: function () {}, error: function () {} };
"""


def quickjs_ready() -> bool:
    try:
        import quickjs  # noqa: F401
        return True
    except Exception:
        return False


def _run_quickjs(inp: dict, fetch=local_fetch, deadline=None, script=None, timeout=None) -> dict:
    import quickjs
    timeout = timeout or TIMEOUT
    deadline = deadline or (time.monotonic() + timeout)
    ctx = quickjs.Context()
    ctx.set_memory_limit(MEM_LIMIT)
    ctx.set_max_stack_size(1024 * 1024)
    ctx.set_time_limit(EVAL_LIMIT)
    try:
        ctx.eval(_PRELUDE)
        if script is None:
            reg, core = _src()
            ctx.eval(reg)
            ctx.eval(core)
            ctx.set("__inp", json.dumps(inp, ensure_ascii=False))
            ctx.eval("__engineRun(JSON.parse(__inp)).then(function (r) { __out = JSON.stringify(r); }, function (e) { __out = JSON.stringify({ error: '엔진 오류: ' + ((e && e.message) || e) }); });")
        else:                                            # 시험용: 임의 스크립트(끝나면 __out 에 글을 넣는다)
            ctx.eval(script)
        ticks = 0
        while True:
            n = 0
            while ctx.execute_pending_job():
                n += 1
                if n % 2000 == 0 and time.monotonic() > deadline:
                    raise TimeoutError
            out = ctx.eval("__out")
            if out is not None:
                return json.loads(out)
            if time.monotonic() > deadline:
                raise TimeoutError
            q = json.loads(ctx.eval("__ftake()"))
            if q:
                for req in q:
                    try:
                        st, text, ctype = fetch(req["method"], req["url"], req.get("body"))
                    except Exception as e:                # 연결 실패는 브라우저처럼 fetch 가 거부되게
                        st, text, ctype = -1, f"요청 실패: {type(e).__name__}", ""
                    ctx.set("__fx", text)
                    ctx.eval(f"__fdeliver({int(req['id'])}, {int(st)}, __fx, {json.dumps(ctype or '')})")
                continue
            if ctx.eval("__tick()"):
                ticks += 1
                if ticks > MAX_TICKS:
                    return {"error": "엔진이 끝나지 않는 대기에 걸렸습니다."}
                continue
            return {"error": "엔진이 결과를 내지 못했습니다(기다리는 작업이 없음)."}
    except TimeoutError:
        return {"error": f"엔진이 {timeout}초 안에 끝나지 않았습니다."}
    except quickjs.JSException as e:
        msg = str(e).splitlines()[0] if str(e) else "JS 오류"
        if "interrupted" in msg:
            return {"error": f"엔진 계산이 {EVAL_LIMIT}초를 넘어 멈췄습니다."}
        return {"error": f"엔진 오류: {msg}"}
    except MemoryError:
        return {"error": "엔진이 메모리 한도를 넘었습니다."}


# ── Node.js(대체) ─────────────────────────────────────────────────────────────
_HTTP = {}
_HTTP_LOCK = threading.Lock()


def _base():
    """Node 엔진이 부를 내부 주소 — 같은 컴퓨터 안에서만(127.0.0.1, 빈 포트). 처음 한 번만 띄운다."""
    with _HTTP_LOCK:
        if "base" not in _HTTP:
            import logging
            from werkzeug.serving import make_server
            logging.getLogger("werkzeug").setLevel(logging.WARNING)
            srv = make_server("127.0.0.1", 0, _app(), threaded=True)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _HTTP["base"] = f"http://127.0.0.1:{srv.server_port}"
        return _HTTP["base"]


NO_ENGINE = ("서버에 화면 엔진이 없어 이 도구를 쓸 수 없습니다(다른 도구는 됩니다). 관리자: Python 3.12 로 실행·배포하면 requirements.txt 의 quickjs 가 함께 "
             "설치됩니다(Vercel 은 .python-version). 3.13 이상이면 `pip install quickjs`(C 컴파일러 필요)나 Node.js 18 이상을 설치하세요.")


def _run_node(inp: dict, timeout=None) -> dict:
    node = shutil.which("node")
    if not node:
        return {"error": NO_ENGINE}
    timeout = timeout or TIMEOUT
    try:
        p = subprocess.run([node, os.path.join(HERE, "engine.mjs")], input=json.dumps({**inp, "base": _base()}, ensure_ascii=False),
                           capture_output=True, text=True, timeout=timeout, encoding="utf-8")
    except subprocess.TimeoutExpired:
        return {"error": f"엔진이 {timeout}초 안에 끝나지 않았습니다."}
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return {"error": "엔진 응답을 읽지 못했습니다.", "detail": (p.stderr or "")[-500:]}


def backend() -> str:
    want = (os.environ.get("MCP_ENGINE") or "auto").strip().lower()
    if want == "node":
        return "node"
    if want == "quickjs" or quickjs_ready():
        return "quickjs"
    return "node"


def run(op: str, inp: dict | None = None, timeout=None, **kw) -> dict:
    """엔진 작업 하나(op: agent|amend|enact) → 결과 dict. 오류도 {"error": …} 로 돌려준다. timeout: 이번 실행의 전체 제한(초)."""
    inp = {**(inp or {}), **kw}
    inp.pop("base", None)                               # 내부 주소는 실행기만 정한다
    inp["op"] = op
    timeout = min(timeout or TIMEOUT, TIMEOUT)
    if backend() == "quickjs":
        if not quickjs_ready():
            return {"error": "MCP_ENGINE=quickjs 인데 quickjs 패키지가 없습니다. " + NO_ENGINE}
        return _run_quickjs(inp, deadline=time.monotonic() + timeout, timeout=timeout)
    return _run_node(inp, timeout)
