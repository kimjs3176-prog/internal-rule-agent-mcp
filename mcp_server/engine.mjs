// MCP 서버(mcp_server/server.py)가 부르는 화면 엔진 실행기.
// 웹 화면과 똑같은 엔진(assets/reg_agent.js)을 브라우저 없이 Node 에서 돌린다 — 에이전트 한 문장 요청, 수정안 → 개정문·신구조문대비표·개정문 검증, 문서 저장.
// 입력: 표준 입력 JSON {op, base, ...}  출력: 표준 출력 JSON. 서버 API 는 base(같은 컴퓨터의 내부 주소)로 부른다.
import fs from 'node:fs'; import path from 'node:path'; import vm from 'node:vm'; import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const inp = JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
const BASE = inp.base;
const plain = s => String(s ?? '').replace(/<br\s*\/?>/g, '\n').replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
const oneLine = s => plain(s).replace(/\s+/g, ' ').trim();

function loadEngine() {
  const store = {}, none = () => null;
  const ctx = {
    console: { log() {}, info() {}, warn() {}, error: (...a) => process.stderr.write(a.join(' ') + '\n') },
    Date, Math, JSON, setTimeout, clearTimeout, AbortController, URLSearchParams, encodeURIComponent, decodeURIComponent, Blob,
    fetch: (u, o) => fetch(/^https?:/.test(u) ? u : BASE + u, o),
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
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'assets/reg_agent.js'), 'utf8') + '\n;globalThis.__RA=()=>RA; globalThis.__setOrg=o=>{RA_ORG=o;}; globalThis.__setArts=d=>{_raArts=d;};', ctx);
  return ctx;
}

async function init(ctx) {
  const cfg = await (await fetch(BASE + '/api/regagent/config')).json();
  ctx.__setOrg(Object.assign(cfg.org, { _count: cfg.reg_count, _law: cfg.law !== false }));
  return ctx.__RA();
}

const run = (ctx, code) => vm.runInContext(code, ctx);

// 개정 결과: 개정문·신구조문대비표(글)·개정문 검증
function amendResult(ctx) {
  const rows = run(ctx, 'raCmpRows()').map(r => ({ current: r[2], amended: r[3] }));
  const rt = run(ctx, 'raRoundTrip()');
  return {
    regulation: run(ctx, 'RA.amend.title'),
    amendment_text: run(ctx, "raDocLaw(raDocCtx('amend'))"),
    comparison_table: rows,
    verification: rt ? { ok: !!rt.ok, articles: rt.n, appendices: rt.nx, diffs: (rt.diffs || []).slice(0, 5), errors: (rt.errors || []).slice(0, 5) } : null,
  };
}

// 문서 세트를 한글·Word 파일로 저장(서버의 /api/regagent/hwpx|docx 가 파일을 만든다)
async function saveDocs(ctx, mode, dir, fmt) {
  if (!dir) return null;
  fmt = fmt === 'docx' ? 'docx' : 'hwpx';
  const B = run(ctx, `raDocsBuild('${mode}')`);
  ctx.__B = B;
  const picks = run(ctx, `raPicks('${mode}').filter(k=>k!=='review'||RA['${mode}'].review)`);
  const blocks = run(ctx, `raDocBlocks(globalThis.__B, ${JSON.stringify(picks)})`);
  const name = `${B.c.title}_${B.c.word}안`;
  const r = await fetch(`${BASE}/api/regagent/${fmt}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: name, blocks }) });
  if (!r.ok) return { error: `문서 저장 실패(${r.status})` };
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${name.replace(/[\\/:*?"<>|]/g, '_')}.${fmt}`);
  fs.writeFileSync(file, Buffer.from(await r.arrayBuffer()));
  const names = Object.fromEntries(run(ctx, `RA_DOCS['${mode}']`));
  return { file, documents: picks.map(k => names[k] || k) };
}

async function opAgent(ctx, RA) {
  RA.agent.req = String(inp.request || '').slice(0, 500); RA.tab = 'agent';
  const t0 = Date.now(); await ctx.raAgentRun();
  const G = RA.agent, mode = G.plan && G.plan.mode;
  const out = {
    mode, seconds: (Date.now() - t0) / 1000,
    conclusion: G.done ? { title: oneLine(G.done.title), detail: oneLine(G.done.sub) } : null,
    steps: (G.steps || []).map(s => ({ step: s.t, status: s.st, detail: oneLine(s.d).slice(0, 400) })),
  };
  const changed = mode === 'amend' && (run(ctx, 'raEffChanges().length+raEffAppx().length') > 0);
  if (changed) Object.assign(out, amendResult(ctx));
  if (mode === 'enact' && RA.enact.draft) out.draft = { title: RA.enact.title, text: RA.enact.draft.text, addenda: RA.enact.draft.addenda || '' };
  if (mode === 'bulk' && RA.bulk.res) out.bulk = { old: RA.bulk.res.old, new: RA.bulk.res.new, regulations: RA.bulk.res.reg_count, places: RA.bulk.res.total,
    amendments: (RA.bulk.res.regs || []).map(r => ({ regulation: r.title, amendment_text: r.amend_text })) };
  if (mode === 'advise' && RA.advise.res) out.advice = { answer: RA.advise.res.answer, conclusion: RA.advise.res.conclusion, basis: (RA.advise.res.basis || []).slice(0, 5) };
  if (mode === 'upper' && RA.upper.res) out.upper = RA.upper.res;
  if (inp.output_dir && (changed || mode === 'enact')) out.saved = await saveDocs(ctx, mode, inp.output_dir, inp.format);
  return out;
}

async function opAmend(ctx, RA) {
  const q = new URLSearchParams(inp.slug ? { slug: inp.slug } : { title: inp.regulation || '' });
  const d = await (await fetch(`${BASE}/api/regagent/articles?${q}`)).json();
  if (!d.success) return { error: d.error || '내규를 찾을 수 없습니다.' };
  ctx.__setArts(d);
  const norm = x => String(x || '').replace(/^제\s*/, '').replace(/\s*조$/, '').replace(/\s+/g, '');
  const changes = [], errors = [];
  for (const c of inp.changes || []) {
    const no = norm(c.article), type = c.type || (c.delete ? 'delete' : 'modify');
    const old = run(ctx, `raOld(${JSON.stringify(no)})`);
    if (type !== 'insert' && !old) { errors.push(`제${no}조가 「${d.title}」에 없습니다.`); continue; }
    if (type === 'delete') { changes.push({ type, no, title: old.title, body: '' }); continue; }
    if (!String(c.body || '').trim()) { errors.push(`제${no}조의 새 본문(body)이 비었습니다.`); continue; }
    changes.push({ type, no, title: c.title != null ? String(c.title) : (old ? old.title : ''), body: String(c.body).replace(/\r/g, '') });
  }
  const appx = [];
  for (const x of inp.appendix_changes || []) {
    const ox = run(ctx, `raOldX(${JSON.stringify(String(x.id || ''))})`);
    if (!ox) { errors.push(`${x.id}가 「${d.title}」에 없습니다.`); continue; }
    appx.push({ type: 'modify', id: ox.id, head: x.head != null ? String(x.head) : ox.head, body: String(x.body || '') });
  }
  if (errors.length && !changes.length && !appx.length) return { error: errors.join(' ') };
  Object.assign(RA.amend, { src: 'reg', slug: d.slug, title: d.title, lawStyle: 'fine', fullRev: false, abbr: true, sel: {}, selx: {}, mv: {},
    changes, appx, addenda: String(inp.addenda || ''), purpose: String(inp.reason || ''), main: [], effective: String(inp.effective || ''), intent: String(inp.reason || '') });
  const out = Object.assign({ warnings: errors }, amendResult(ctx));
  // 화면의 “조문 점검”과 같은 입력(문서에 실리는 부칙 포함). 오류는 어느 조든 보여 주고, 주의·표기 제안은 고친 조만
  const full = run(ctx, 'raAmendFullText()');
  if (full) {
    const lint = await (await fetch(`${BASE}/api/regagent/lint`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: full.text, addenda: run(ctx, "raDocCtx('amend').addenda"), title: d.title, base_slug: d.slug }) })).json();
    if (lint.success) {
      const mine = new Set(changes.map(c => c.no));
      const is = (lint.issues || []).filter(i => i.level === 'error' || !i.no || mine.has(i.no));
      out.check = { errors: is.filter(i => i.level === 'error').length, warnings: is.filter(i => i.level === 'warn').length, suggestions: is.filter(i => i.level === 'info').length,
        items: is.slice(0, 15).map(i => `${({ error: '오류', warn: '주의', info: '표기 제안' })[i.level] || i.level}: ${i.msg}`) };
    }
  }
  const nos = changes.filter(c => c.type !== 'insert').map(c => c.no);
  if (nos.length) {
    const im = await (await fetch(`${BASE}/api/regagent/impact`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slug: d.slug, nos, moves: {} }) })).json();
    if (im.success) out.citation_impact = { summary: im.summary,
      same_regulation: (im.inner || []).slice(0, 10).map(h => `제${h.no}조(${h.title})에서 “${h.text}” 인용${h.suggest ? ' — 제안: ' + h.suggest : ''}`),
      other_regulations: (im.outer || []).slice(0, 10).map(h => `「${h.reg || h.title || ''}」 제${h.no}조에서 “${h.text}” 인용`),
      appendices: (im.appendix || []).slice(0, 10).map(h => typeof h === 'string' ? h : (h.id || h.label || JSON.stringify(h))) };
  }
  if (inp.output_dir) out.saved = await saveDocs(ctx, 'amend', inp.output_dir, inp.format);
  return out;
}

// 결과를 다 쓰면 바로 끝낸다(열린 연결이 저절로 닫힐 때까지 몇 초씩 기다리지 않게)
const done = (obj, code) => process.stdout.write(JSON.stringify(obj), () => process.exit(code));
try {
  const ctx = loadEngine(); const RA = await init(ctx);
  done(inp.op === 'agent' ? await opAgent(ctx, RA) : inp.op === 'amend' ? await opAmend(ctx, RA) : { error: `모르는 작업: ${inp.op}` }, 0);
} catch (e) {
  done({ error: `엔진 오류: ${e && e.message || e}` }, 1);
}
