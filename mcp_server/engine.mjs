// MCP 서버가 부르는 화면 엔진 실행기(Node 판) — QuickJS 를 쓸 수 없을 때의 대체 경로(mcp_server/engine.py 가 고른다).
// 웹 화면과 똑같은 엔진(assets/reg_agent.js)과 MCP 작업(mcp_server/engine_core.js)을 브라우저 없이 Node 에서 돌린다.
// 입력: 표준 입력 JSON {op, base, ...}  출력: 표준 출력 JSON. 서버 API 는 base(같은 컴퓨터의 내부 주소)로만 부른다.
import fs from 'node:fs'; import path from 'node:path'; import vm from 'node:vm'; import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url)), ROOT = path.resolve(HERE, '..');
const inp = JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
const BASE = String(inp.base || '');
// 엔진이 부를 수 있는 곳은 이 서버의 내규 API 뿐이다(외부 주소·다른 경로는 막는다 — mcp_server/engine.py 의 allowed 와 같은 규칙)
const ALLOWED = u => /^\/api\/(?:regagent|law)\//.test(u) && !/^\/api\/regagent\/ledger/.test(u);

function loadEngine() {
  const store = {}, none = () => null;
  const ctx = {
    console: { log() {}, info() {}, warn() {}, error: (...a) => process.stderr.write(a.join(' ') + '\n') },
    Date, Math, JSON, setTimeout, clearTimeout, setInterval, clearInterval, AbortController, URLSearchParams, encodeURIComponent, decodeURIComponent, Blob,
    // 다른 기관 규정 작업이면(ra_ctx) 서버가 그 요청에서만 그 기관 이름을 쓰고 우리 내규와 대조하지 않게 X-RA-Ctx 를 붙인다
    fetch: (u, o) => ALLOWED(String(u))
      ? fetch(BASE + u, inp.ra_ctx ? Object.assign({}, o, { headers: Object.assign({}, (o && o.headers) || {}, { 'X-RA-Ctx': String(inp.ra_ctx) }) }) : o)
      : Promise.reject(new TypeError('허용되지 않은 주소: ' + String(u).slice(0, 80))),
    localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: { getElementById: none, querySelector: none, querySelectorAll: () => [], title: '', body: {}, addEventListener() {},
      createElement: () => ({ style: {}, click() {}, remove() {}, setAttribute() {}, appendChild() {} }) },
    window: { scrollY: 0, scrollTo() {}, innerWidth: 1440, addEventListener() {} }, location: { hash: '' }, navigator: {},
    confirm: () => true, alert() {}, requestAnimationFrame: f => setTimeout(f, 0),
    escHtml: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'),
    argAttr: s => String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;'),
    getAiSettings: () => ({}), _toast() {}, _copyText() {}, openAiModal() {},
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'assets/reg_agent.js'), 'utf8'), ctx, { filename: 'reg_agent.js' });
  vm.runInContext(fs.readFileSync(path.join(HERE, 'engine_core.js'), 'utf8'), ctx, { filename: 'engine_core.js' });
  return ctx;
}

// 결과를 다 쓰면 바로 끝낸다(열린 연결이 저절로 닫힐 때까지 몇 초씩 기다리지 않게)
const done = (obj, code) => process.stdout.write(JSON.stringify(obj), () => process.exit(code));
try {
  if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(BASE)) throw new Error('base 는 같은 컴퓨터의 내부 주소(http://127.0.0.1:포트)여야 합니다.');
  const ctx = loadEngine();
  done(await ctx.__engineRun(inp), 0);
} catch (e) {
  done({ error: `엔진 오류: ${e && e.message || e}` }, 1);
}
