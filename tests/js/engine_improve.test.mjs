// 개정문 규칙 엔진(assets/reg_agent.js) 개선 시험 — 각각 문형·조 묶음·별표 머리·삭제 문형·낱말 바꾸기. 불러오기는 reg_agent.test.mjs 와 같다
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
  vm.runInContext(src + '\n;globalThis.__RA=()=>RA; globalThis.__setOrg=o=>{RA_ORG=o;}; globalThis.__setArts=a=>{_raArts=a;};', ctx);
  const fmt = o => typeof o === 'string' ? o.replace(/\{head\}/g, cfg.head).replace(/\{deputy\}/g, cfg.deputy).replace(/\{notice_days\}/g, cfg.notice_days).replace(/\{staff_days\}/g, cfg.staff_days)
    : Array.isArray(o) ? o.map(fmt) : o && typeof o === 'object' ? Object.fromEntries(Object.entries(o).map(([k, v]) => [k, fmt(v)])) : o;
  ctx.__setOrg(fmt(cfg));
  return ctx;
}

const c = load(); const RA = c.__RA();
const A = (no, title, body) => ({ no, title, body, chapter: '', deleted: false });
// 수정안 → 개정문(머리·부칙 앞까지)과 왕복 검증
function run(arts, changes, opt = {}) {
  c.__setArts({ title: '시험규정', revision: '', articles: arts, appendix: opt.appendix || [] });
  Object.assign(RA.amend, { slug: 't', title: '시험규정', lawStyle: opt.style || 'fine', fullRev: false, abbr: true, addenda: '', purpose: '', main: [], appx: opt.appx || [], selx: {}, mv: {} });
  RA.amend.changes = changes.map(x => ({ type: 'modify', why: '', ...x }));
  const law = c.raDocLaw(c.raDocCtx('amend')); const rt = c.raRoundTrip();
  return { law: law.split('\n').slice(4).join('\n').split('부    칙')[0].trim(), full: law, rt };
}
const okRt = r => assert.ok(r.rt.ok, r.law + '\n' + JSON.stringify(r.rt.diffs) + JSON.stringify(r.rt.errors));

test('1·3 같은 바꿈이 한 단위에 여러 번 — “각각”', () => {
  let r = run([A('1', '목적', '① 직원은 2만원, 임원은 2만원을 받는다.\n② 기타.')], [{ no: '1', title: '목적', body: '① 직원은 3만원, 임원은 3만원을 받는다.\n② 기타.' }]);
  assert.equal(r.law, '제1조제1항 중 “2만원”을 각각 “3만원”으로 한다.'); okRt(r);
  r = run([A('1', '목적', '직원은 2만원, 임원은 2만원을 받는다.')], [{ no: '1', title: '목적', body: '직원은 3만원, 임원은 3만원을 받는다.' }]);
  assert.equal(r.law, '제1조 중 “2만원”을 각각 “3만원”으로 한다.'); okRt(r);
  // 본문과 단서에 같은 낱말 — 항째 고쳐 쓰지 않는다
  r = run([A('4', '업무', '① 원장이 정한다. 다만, 원장이 없으면 따로 정한다.\n② 끝.')], [{ no: '4', title: '업무', body: '① 부원장이 정한다. 다만, 부원장이 없으면 따로 정한다.\n② 끝.' }]);
  assert.equal(r.law, '제4조제1항 중 “원장”을 각각 “부원장”으로 한다.'); okRt(r);
  // 한 곳만 바꾸면 지금처럼
  r = run([A('1', '목적', '① 직원은 2만원을 받고 부서장은 2만원을 받는다.')], [{ no: '1', title: '목적', body: '① 직원은 2만원을 받고 부서장은 3만원을 받는다.' }]);
  assert.equal(r.law, '제1조제1항 중 “부서장은 2만원”을 “부서장은 3만원”으로 한다.'); okRt(r);
});

test('2 여러 조의 같은 바꿈 — “제5조 및 제6조 중 … 각각”', () => {
  let r = run([A('5', '가', '원장이 정한다.'), A('6', '나', '원장이 승인한다.'), A('7', '다', '기타')],
    [{ no: '5', title: '가', body: '부원장이 정한다.' }, { no: '6', title: '나', body: '부원장이 승인한다.' }]);
  assert.equal(r.law, '제5조 및 제6조 중 “원장”을 각각 “부원장”으로 한다.'); okRt(r);
  r = run([A('5', '가', '원장이 정한다.'), A('6', '나', '원장이 승인한다.'), A('7', '다', '기타 처장이 한다.'), A('8', '라', '① 원장이 한다.\n② 끝.')],
    [{ no: '5', title: '가', body: '부원장이 정한다.' }, { no: '6', title: '나', body: '부원장이 승인한다.' }, { no: '7', title: '다', body: '기타 실장이 한다.' }, { no: '8', title: '라', body: '① 부원장이 한다.\n② 끝.' }]);
  assert.equal(r.law, '제5조·제6조 및 제8조제1항 중 “원장”을 각각 “부원장”으로 한다.\n\n제7조 중 “처장”을 “실장”으로 한다.'); okRt(r);
});

test('4 호가 딸린 항을 삭제 — 아래 호 삭제는 세지 않는다', () => {
  const r = run([A('4', '업무', '① 가.\n② 다음과 같다.\n1. 기획\n2. 예산\n3. 인사\n③ 다.')], [{ no: '4', title: '업무', body: '① 가.\n② 삭제\n③ 다.' }]);
  assert.equal(r.law, '제4조제2항을 삭제한다.'); okRt(r);
});

test('5 항 번호가 밀렸는데 같은 조가 옛 번호를 인용하면 경고', () => {
  const r = run([A('4', '업무', '① 가.\n② 나.\n③ 제2항에 따른 다.')], [{ no: '4', title: '업무', body: '① 가.\n② 새.\n③ 나.\n④ 제2항에 따른 다.' }]);
  okRt(r);
  const s = c.raAmendSentences(c.raOld('4'), RA.amend.changes[0]);
  assert.ok(s.warns && s.warns.some(w => w.includes('제2항') && w.includes('제3항')), JSON.stringify(s.warns));
  assert.ok(r.rt.warns.length >= 1);
  // 인용이 없으면 경고 없음
  const r2 = run([A('4', '업무', '① 가.\n② 나.')], [{ no: '4', title: '업무', body: '① 새.\n② 가.\n③ 나.' }]);
  okRt(r2); assert.equal(r2.rt.warns.length, 0);
});

test('6 괄호 없는 별표 머리·번호가 다른 머리도 검증 통과', () => {
  let r = run([A('4', '업무', '별표 1에 따른다.')], [], { appendix: [{ id: '별표 1', head: '별표 1 수당표', body: '가 1000' }], appx: [{ type: 'modify', id: '별표 1', head: '별표 1 수당표', body: '가 2000' }] });
  okRt(r); assert.match(r.full, /〔별표 1〕 수당표\n가 2000/);
  r = run([A('4', '업무', '별표 1에 따른다.')], [], { appendix: [{ id: '별표 1', head: '[별표 2] 수당표', body: '가 1000' }], appx: [{ type: 'modify', id: '별표 1', head: '[별표 2] 수당표', body: '가 2000' }] });
  okRt(r);
  r = run([A('4', '업무', '별표 1에 따른다.')], [], { appendix: [{ id: '별표 1', head: '〔별표 1〕〈 제4조 관련 〉', body: '가 1000' }], appx: [{ type: 'modify', id: '별표 1', head: '〔별표 1〕〈 제4조 관련 〉', body: '가 2000' }] });
  okRt(r); assert.match(r.full, /\n〔별표 1〕〈 제4조 관련 〉\n가 2000/);
});

test('7 제목 속 큰따옴표는 작은따옴표로', () => {
  const r = run([A('3', '“가”의 정의', '직원은 근무한다.')], [{ no: '3', title: '“나”의 정의', body: '직원은 근무한다.' }]);
  assert.equal(r.law, '제3조의 제목 “‘가’의 정의”를 “‘나’의 정의”로 한다.'); okRt(r);
});

test('8 본문을 비우면 조 삭제', () => {
  let r = run([A('3', '근무', '직원은 근무한다.'), A('4', '끝', '끝.')], [{ no: '3', title: '근무', body: '' }]);
  assert.equal(r.law, '제3조를 삭제한다.'); okRt(r);
  r = run([A('3', '근무', '직원은 근무한다.'), A('4', '끝', '끝.')], [{ no: '3', title: '근무', body: '  ' }], { style: 'art' });
  assert.equal(r.law, '제3조를 삭제한다.'); okRt(r);
});

test('9 raSwapTerm — 짧은 말은 다른 낱말 속에서 바꾸지 않고, 조사를 맞춘다', () => {
  assert.equal(c.raSwapTerm('원장이라고 부르며 부원장은 원장을 보좌한다.', '원장', '이사', false).text, '이사라고 부르며 부원장은 이사를 보좌한다.');
  assert.equal(c.raSwapTerm('이사라고 한다', '이사', '원장', true).text, '원장이라고 한다');
  // 긴 명칭(기관 설정 stale_terms)은 파생어까지: 부이사장 → 부원장
  assert.equal(c.raSwapTerm('이사장과 부이사장은 이사장이라면', '이사장', '원장', false).text, '원장과 부원장은 원장이라면');
  assert.equal(c.raSwapTerm('재단으로서 재단이었다', '재단', '농진원', false).text, '농진원으로서 농진원이었다');
});

test('10 이미 “삭제 <날짜>”인 항·새로 날짜를 단 삭제 — 날짜 표기를 지킨다', () => {
  let r = run([A('4', '업무', '① 가.\n② 나.\n③ 다.')], [{ no: '4', title: '업무', body: '① 가.\n② 삭제 <2024. 1. 1.>\n③ 다.' }]);
  assert.equal(r.law, '제4조제2항을 삭제한다.'); okRt(r);
  // 현행이 이미 “② 삭제 <날짜>”면 역적용이 날짜를 지운 “② 삭제”로 덮지 않는다
  const arts = [A('4', '업무', '① 가.\n② 삭제 <2024. 1. 1.>\n③ 다.\n1. 하나\n2. 둘')];
  const ap = c.raApplyAmend(arts, '시험규정 일부를 다음과 같이 개정한다.\n\n제4조제2항을 삭제한다.\n\n부    칙\n시행한다.', []);
  assert.equal(ap.errors.length, 0); assert.equal(ap.arts[0].body.split('\n')[1], '② 삭제 <2024. 1. 1.>');
});
