// 개정문 규칙 엔진(assets/reg_agent.js) 결함 수정 회귀 시험 — 불러오기는 reg_agent.test.mjs 와 같다
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const cfg = JSON.parse(fs.readFileSync(path.join(root, 'org_config.json'), 'utf8'));

function load() {
  const store = {};
  const ctx = {
    console, Date, Math, JSON, setTimeout, clearTimeout,
    localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
    sessionStorage: { getItem: () => null, setItem() {} },
    document: { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [], title: '' },
    window: { scrollY: 0, scrollTo() {} },
    escHtml: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'),
    argAttr: s => String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;'),
    getAiSettings: () => ({}), _toast() {}, _copyText() {}, openAiModal() {},
  };
  vm.createContext(ctx);
  const src = fs.readFileSync(path.join(root, 'assets/reg_agent.js'), 'utf8');
  vm.runInContext(src + '\n;globalThis.__RA=()=>RA; globalThis.__setOrg=o=>{RA_ORG=o;};', ctx);
  const fmt = o => typeof o === 'string' ? o.replace(/\{head\}/g, cfg.head).replace(/\{deputy\}/g, cfg.deputy).replace(/\{notice_days\}/g, cfg.notice_days).replace(/\{staff_days\}/g, cfg.staff_days)
    : Array.isArray(o) ? o.map(fmt) : o && typeof o === 'object' ? Object.fromEntries(Object.entries(o).map(([k, v]) => [k, fmt(v)])) : o;
  ctx.__setOrg(fmt(cfg));
  return ctx;
}

// 현행 조 하나 → 수정안 → {law: 개정문 본문, rt: 왕복 검증}
function amend(no, oldA, newA) {
  const c = load(); const RA = c.__RA();
  vm.runInContext(`_raArts=${JSON.stringify({ title: '시험규정', articles: [{ no, chapter: '', deleted: false, ...oldA }], appendix: [] })}`, c);
  Object.assign(RA.amend, { slug: 's', title: '시험규정', lawStyle: 'fine', fullRev: false, addenda: '', purpose: '', main: [], selx: {}, appx: [], mv: {},
    changes: [{ type: 'modify', no, why: '', ...newA }] });
  const law = c.raDocLaw(c.raDocCtx('amend'));
  return { c, law, rt: c.raRoundTrip() };
}
const rtOk = rt => assert.ok(rt.ok, JSON.stringify(rt.diffs) + JSON.stringify(rt.errors));

test('글귀 삭제 “X 중 “A”를 삭제한다”를 단위 삭제로 읽지 않는다(왕복 일치)', () => {
  const { law, rt } = amend('3', { title: '수당', body: '① 직원은 예산의 범위에서 수당을 받는다.\n② 끝.' }, { title: '수당', body: '① 직원은 수당을 받는다.\n② 끝.' });
  assert.match(law, /제3조제1항 중 “예산의 범위에서 ”를 삭제한다\./);
  rtOk(rt);
});

test('raUnits: ㉑ 이상 항도 제21항으로 센다', () => {
  const hs = Array.from({ length: 22 }, (_, i) => '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒'[i] + ` 항${i + 1}이다.`);
  const { c, law, rt } = amend('5', { title: '항', body: hs.join('\n') }, { title: '항', body: hs.map((x, i) => i === 20 ? '㉑ 항21은 바뀐다.' : x).join('\n') });
  const us = c.raUnits(hs.join('\n'));
  assert.equal(us.length, 22); assert.equal(us[20].h, 21); assert.equal(us[21].h, 22);
  assert.match(law, /제5조제21항/); assert.doesNotMatch(law, /제20항/);
  rtOk(rt);
});

test('제목 없는 조에 제목을 붙이면 조 전체를 고쳐 쓰고, 빈 제목은 “제5조()”로 찍지 않는다', () => {
  const { c, law, rt } = amend('3', { title: '', body: '직원은 근무한다.' }, { title: '근무', body: '직원은 근무한다.' });
  assert.doesNotMatch(law, /“”/);
  assert.match(law, /제3조를 다음과 같이 한다\.\n제3조\(근무\) 직원은 근무한다\./);
  rtOk(rt);
  assert.equal(c.raArtText({ no: '5', title: '', body: '직원은 근무한다.' }), '제5조 직원은 근무한다.');
  const r2 = amend('3', { title: '근무', body: '직원은 근무한다.\n다만, 예외로 한다.' }, { title: '', body: '직원은 근무한다.\n다만, 예외로 한다.' });
  assert.doesNotMatch(r2.law, /제3조\(\)/); rtOk(r2.rt);
});

test('raSubst: 괄호 안에서 끊긴 글귀는 괄호 앞까지만 인용한다', () => {
  const c = load();
  const r = c.raSubst('① 원장(부원장을 포함한다)이 정한다.', '① 이사장(부원장을 포함한다)이 정한다.');
  assert.equal(r.a, '원장'); assert.equal(r.b, '이사장');
  const { law, rt } = amend('4', { title: '결정', body: '① 원장(부원장을 포함한다)이 정한다.\n② 끝.' }, { title: '결정', body: '① 이사장(부원장을 포함한다)이 정한다.\n② 끝.' });
  assert.match(law, /제4조제1항 중 “원장”을 “이사장”으로 한다\./);
  rtOk(rt);
});

test('띄어쓰기만 바뀐 항은 개정 문장을 만들지 않는다', () => {
  const { law } = amend('2', { title: '수당', body: '① 직원은  수당을 받는다.\n② 임원은 수당을 받는다.' }, { title: '수당', body: '① 직원은 수당을 받는다.\n② 임원은 보수를 받는다.' });
  assert.doesNotMatch(law, /“직원은”을 “직원은”으로/);
  assert.doesNotMatch(law, /제1항/);
  assert.match(law, /제2조제2항 중 “수당을”을 “보수를”로 한다\./);
});

test('raRtNorm: 다음 항이 있어도 항 끝의 “N. 삭제” 호는 지운 것과 같게 본다', () => {
  const { c, law, rt } = amend('7', { title: '대상', body: '① 다음과 같다.\n1. 가\n2. 나\n3. 다\n② 끝.' }, { title: '대상', body: '① 다음과 같다.\n1. 가\n2. 나\n② 끝.' });
  assert.match(law, /제7조제1항제3호를 삭제한다\./);
  rtOk(rt);
  const base = { no: '7', title: '대상', body: '① 다음과 같다.\n1. 가\n2. 나\n② 끝.' };
  assert.equal(c.raRtNorm({ ...base, body: '① 다음과 같다.\n1. 가\n2. 나\n3. 삭제 <2026. 1. 1.>\n② 끝.' }), c.raRtNorm(base));
  assert.notEqual(c.raRtNorm({ ...base, body: '① 다음과 같다.\n1. 삭제\n2. 나\n② 끝.' }), c.raRtNorm({ ...base, body: '① 다음과 같다.\n2. 나\n② 끝.' }));   // 중간 호의 “삭제”는 그대로
});

test('raRepJosa: 숫자로 끝나는 말 뒤 ‘으로/로’는 받침대로', () => {
  const c = load();
  assert.equal(c.raRepJosa('일비는 2만원으로 한다.', '2만원', '30000').s, '일비는 30000으로 한다.');
  assert.equal(c.raRepJosa('일비는 2만원으로 한다.', '2만원', '5').s, '일비는 5로 한다.');
  assert.equal(c.raRepJosa('기간은 3년으로 한다.', '3년', '1일').s, '기간은 1일로 한다.');
  assert.equal(c.raRepJosa('기간은 3일로 한다.', '3일', '3년').s, '기간은 3년으로 한다.');
});
