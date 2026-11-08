// assets/reg_agent.js 의 순수 로직 — 브라우저 없이 node:test 로 확인 (node --test tests/js)
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
  // const/let 최상위 선언을 컨텍스트에서 꺼내 쓰도록 노출
  vm.runInContext(src + '\n;globalThis.__RA=()=>RA; globalThis.__setOrg=o=>{RA_ORG=o;};', ctx);
  // org_config 자리표시자 치환(서버 ofmt 대용)
  const fmt = o => typeof o === 'string' ? o.replace(/\{head\}/g, cfg.head).replace(/\{deputy\}/g, cfg.deputy).replace(/\{notice_days\}/g, cfg.notice_days).replace(/\{staff_days\}/g, cfg.staff_days)
    : Array.isArray(o) ? o.map(fmt) : o && typeof o === 'object' ? Object.fromEntries(Object.entries(o).map(([k, v]) => [k, fmt(v)])) : o;
  ctx.__setOrg(fmt(cfg));
  return ctx;
}

test('raParse: 조·장·부칙 구분', () => {
  const c = load();
  const p = c.raParse('제1장 총칙\n제1조(목적) 가.\n① 나.\n제1조의2(특례) 다.\n제2조 삭제\n부칙\n이 규칙은 발령한 날부터 시행한다.');
  assert.equal(JSON.stringify(p.articles.map(a => a.no)), JSON.stringify(['1', '1의2', '2']));   // vm 컨텍스트 배열은 realm이 달라 deepEqual 불가
  assert.equal(p.articles[0].chapter, '제1장 총칙');
  assert.ok(p.articles[2].deleted);
  assert.match(p.addenda, /^부칙/);
});

test('raCmpCell: 신설·삭제·변경 표시와 (현행과 같음) 축약', () => {
  const c = load();
  const ins = c.raCmpCell(null, { no: '3', title: '신설', body: '내용' }, true);
  assert.equal(ins[2], '<신 설>');
  const del = c.raCmpCell({ no: '3', title: 't', body: 'b' }, { type: 'delete', no: '3' }, true);
  assert.match(del[3], /삭 제/);
  const mod = c.raCmpCell({ no: '2', title: '정의', body: '① 가.\n② 나는 3만원.' }, { no: '2', title: '정의', body: '① 가.\n② 나는 5만원.' }, true);
  assert.match(mod[3], /현행과 같음/);
  assert.match(mod[1], /<u class="ra-i">5만원/);
});

test('raCmpCell: HTML 특수문자 이스케이프', () => {
  const c = load();
  const r = c.raCmpCell({ no: '1', title: 'a', body: '<script>' }, { no: '1', title: 'a', body: '<img onerror=x>' }, false);
  assert.ok(!r[0].includes('<script>') && !r[1].includes('<img'));
});

test('raProcEval: 답하지 않은 조건은 미정, 해당 없음은 사유 포함', () => {
  const c = load();
  let items = c.raProcEval();
  assert.ok(items.some(s => s.st === 'tbd'));
  const RA = c.__RA();
  RA.proc.ans = { level: 'rule', minor: 'n', public: 'n', multi: 'n', impact: 'n', burden: 'n' };
  items = c.raProcEval();
  assert.ok(!items.some(s => s.st === 'tbd'));
  const notice = items.find(s => s.id === 'notice');
  assert.equal(notice.st, 'out');
  assert.ok(notice.why.some(w => w.includes('국민 권리')));
  // 같은 id 의 대안 경로는 하나만 남는다
  assert.equal(items.filter(s => s.id === 'review').length, 1);
});

test('raProcState: 선행 단계가 끝나야 다음 단계가 열린다(선택 단계는 막지 않음)', () => {
  const c = load();
  const RA = c.__RA();
  RA.proc.ans = { level: 'rule', minor: 'n', public: 'y', multi: 'n', impact: 'n', burden: 'n' };
  RA.proc.chk = {};
  let st = c.raProcState();
  const get = id => st.live.find(s => s.id === id);
  assert.equal(st.next.id, 'draft');
  assert.ok(get('check').locked);
  RA.proc.chk = { draft: '2026-10-01' };
  st = c.raProcState();
  assert.ok(!get('check').locked);
  assert.ok(get('notice').locked);                 // 앞 국면 미완료
  RA.proc.chk = { draft: 1, check: 1 };            // pre(선택)는 건너뛰어도 된다
  st = c.raProcState();
  assert.ok(!get('notice').locked);
});

test('raSchedule: 병행 국면은 가장 긴 기간, 나머지는 합산', () => {
  const c = load();
  const RA = c.__RA();
  RA.proc.ans = { level: 'rule', minor: 'n', public: 'y', multi: 'n', impact: 'n', burden: 'n' };
  RA.proc.plan = { start: '2026-10-03', target: '2026-11-15' };
  const st = c.raProcState(), sc = c.raSchedule(st.flow);
  assert.equal(sc.total, cfg.notice_days + 7);
  assert.equal(sc.end, c.raAddD('2026-10-03', sc.total));
  assert.equal(sc.slack, c.raDiffD(sc.end, '2026-11-15'));
});

test('날짜 도우미: 월말·윤년·잘못된 값', () => {
  const c = load();
  assert.equal(c.raAddD('2028-02-28', 1), '2028-02-29');
  assert.equal(c.raAddD('2026-12-31', 1), '2027-01-01');
  assert.equal(c.raDiffD('2026-03-01', '2026-03-31'), 30);
  const RA = c.__RA();
  RA.proc.plan = { start: 'garbage' };
  assert.match(c.raSchedule([]).start, /^\d{4}-\d{2}-\d{2}$/);
});

test('raNormNo: 항·호 번호는 버리고 조 번호만', () => {
  const c = load();
  assert.equal(c.raNormNo('제 7 조 제2항'), '7');
  assert.equal(c.raNormNo('제31조제2항'), '31');
  assert.equal(c.raNormNo('제7조의2'), '7의2');
  assert.equal(c.raNormNo('7의2'), '7의2');
  assert.equal(c.raNormNo('abc'), '');
});

test('raCmpCell: 항 신설로 번호가 밀려도 같은 내용끼리 짝짓는다', () => {
  const c = load();
  const r = c.raCmpCell({ no: '2', title: 't', body: '① 가는 x이다.\n② 나는 y이다.' }, { no: '2', title: 't', body: '① 가는 x이다.\n② 새로 넣은 항이다.\n③ 나는 y이다.' }, false);
  const rows = r[3].split('\n');
  assert.equal(rows.length, 3);
  assert.match(r[1], /<u class="ra-i">② 새로 넣은 항이다\.<\/u>/);   // 신설 항은 통째로 추가 표시
  assert.ok(!/<u class="ra-i">③ 나는 y이다/.test(r[1]));           // 기존 항은 번호만 바뀐 것으로 비교
});

test('raParse: “부칙으로”·“제3조(정의)에 따른”은 본문으로 본다', () => {
  const c = load();
  const p = c.raParse('제1조(목적) 가.\n부칙으로 정하는 사항은 따로 정한다.\n제2조(정의) 나.\n제3조(정의)에 따른 용어는 같다.\n제4조(기타) 다.');
  assert.equal(JSON.stringify(p.articles.map(a => a.no)), JSON.stringify(['1', '2', '4']));
  assert.equal(p.addenda, '');
});

test('raProcEval: unless 조건이 미답변이면 확정하지 않는다(요약 목록에는 포함)', () => {
  const c = load();
  const RA = c.__RA();
  RA.proc.ans = {};
  const confirm = c.raProcEval().find(s => s.id === 'confirm');
  assert.equal(confirm.st, 'tbd');
  RA.proc.ans = { level: 'rule' };
  const staff = c.raProcEval().find(s => s.id === 'staff');
  assert.equal(staff.st, 'tbd');                                    // 경미한 변경 여부 미답변
  assert.ok(c.raProcSteps().some(s => s.id === 'staff'));           // 에이전트 요약에는 포함
});

test('raProcState: 앞 국면의 미정 단계도 관문을 막는다', () => {
  const c = load();
  const RA = c.__RA();
  RA.proc.ans = { level: 'rule', minor: 'n', multi: 'n', impact: 'n', burden: 'n' };   // public 미답변 → 사전예고 미정
  RA.proc.chk = { draft: 1, check: 1, staff: 1 };
  const st = c.raProcState();
  assert.ok(st.live.find(s => s.id === 'review').locked);
});

// ── 공문서 표기(행정업무운영편람): 이유서·사전예고문·공고 ──
function docCtx(c) {
  const RA = c.__RA();
  RA.amend = Object.assign(RA.amend, { title: '여비규정', purpose: '일비를 현실화하려는 것임.', main: ['일비를 3만원으로 상향함(안 제15조)'],
    changes: [{ type: 'modify', no: '15', title: '일비', body: '일비는 3만원으로 한다.' }], addenda: '이 규정은 발령한 날부터 시행한다.' });
  return c.raDocsBuild('amend');
}

test('공문서 문서: 붙임은 쌍점 없이 두 칸, 기간은 물결표 붙여 씀', () => {
  const c = load(); const B = docCtx(c);
  for (const k of ['reason', 'notice', 'staff']) {
    assert.ok(!/붙임\s*:/.test(B[k]), k);
    assert.match(B[k], /붙임 {2}신구조문대비표 1부\. {2}끝\.$/);
  }
  assert.match(B.notice, /\d+\. \d+\. \d+\.∼\d+\. \d+\. \d+\./);
  assert.ok(!/[—–―]/.test(B.reason + B.notice + B.staff));
});

test('raAmendSentences: 바뀐 곳만 짚는 일부개정 문형', () => {
  const c = load();
  const S = (o, n) => { const r = c.raAmendSentences(o, n); return r.head + (r.lines.length ? ' | ' + r.lines.join(' / ') : ''); };
  const base = { no: '5', title: '여비', body: '① 숙박비는 3만원을 한도로 한다.\n② 식비는 실비로 한다.' };
  assert.equal(S(base, { ...base, body: '① 숙박비는 5만원을 한도로 한다.\n② 식비는 실비로 한다.' }), '제5조제1항 중 “3만원”을 “5만원”으로 한다.');
  assert.equal(S(base, { ...base, title: '여비의 지급', body: base.body + '\n③ 교통비는 실비로 한다.' }),
    '제5조의 제목 “여비”를 “여비의 지급”으로 하고, 같은 조에 제3항을 다음과 같이 신설한다. | ③ 교통비는 실비로 한다.');
  // 받침에 따라 모양이 바뀐 조사(으로→로·이→가)는 따옴표 안에 함께 쓴다 — 밖으로 빼면 그대로 적용했을 때 “전자결재으로”가 된다
  assert.equal(S({ no: '7', title: '신청', body: '신청서를 서면으로 제출한다.' }, { no: '7', title: '신청', body: '신청서를 전자결재로 제출한다.' }),
    '제7조 중 “서면으로”를 “전자결재로”로 한다.');
  assert.equal(S({ no: '9', title: '해지', body: '입주기업이 다음에 해당하면 해지한다.' }, { no: '9', title: '해지', body: '입주단체가 다음에 해당하면 해지한다.' }),
    '제9조 중 “입주기업이”를 “입주단체가”로 한다.');
  // 같은 모양 조사는 밖으로
  assert.equal(S({ no: '8', title: '보고', body: '부서장은 보고한다.' }, { no: '8', title: '보고', body: '본부장은 보고한다.' }), '제8조 중 “부서장”을 “본부장”으로 한다.');
  // 단서가 있는 항은 고친 곳이 본문인지 단서인지 밝힌다
  const pv = { no: '8', title: '휴가', body: '① 연차휴가는 15일로 한다. 다만, 신규 직원은 10일로 한다.\n② x' };
  assert.equal(S(pv, { ...pv, body: '① 연차휴가는 15일로 한다. 다만, 신규 직원은 11일로 한다.\n② x' }), '제8조제1항 단서 중 “10일”을 “11일”로 한다.');
  assert.equal(S(pv, { ...pv, body: '① 연차휴가는 20일로 한다. 다만, 신규 직원은 10일로 한다.\n② x' }), '제8조제1항 본문 중 “15일”을 “20일”로 한다.');
  // 같은 바꿈은 “각각”으로 묶는다
  assert.equal(S({ no: '9', title: 'a', body: '① 원장은 정한다.\n② 원장은 승인한다.\n③ x' }, { no: '9', title: 'a', body: '① 기관장은 정한다.\n② 기관장은 승인한다.\n③ x' }),
    '제9조제1항 및 제2항 중 “원장”을 각각 “기관장”으로 한다.');
  // 호가 있으면 “각 호 외의 부분”, 끝에 덧붙인 호는 신설
  assert.equal(S({ no: '8', title: '대상', body: '다음 사람에게 지급한다.\n1. 임원\n2. 직원' }, { no: '8', title: '대상', body: '다음 사람에게 준다.\n1. 임원\n2. 직원\n3. 계약직' }),
    '제8조 각 호 외의 부분 중 “지급한다”를 “준다”로 하고, 같은 조에 제3호를 다음과 같이 신설한다. | 3. 계약직');
  assert.equal(S({ no: '9', title: 'a', body: '① aa\n② bb\n③ cc' }, { no: '9', title: 'a', body: '① aa\n② bb' }), '제9조제3항을 삭제한다.');
  // 중간에 항을 끼우면(번호가 밀림) 밀린 번호를 고치고 신설한다
  assert.equal(S({ no: '4', title: 'a', body: '① 가.\n② 나.' }, { no: '4', title: 'a', body: '① 가.\n② 새 항.\n③ 나.' }), '제4조제2항을 제3항으로 하고, 같은 조에 제2항을 다음과 같이 신설한다. | ② 새 항.');
  // 밀림과 내용 수정이 섞이면 조 전체를 다시 쓴다
  assert.match(S({ no: '4', title: 'a', body: '① 가.\n② 나.' }, { no: '4', title: 'a', body: '① 가가.\n② 새 항.\n③ 나.' }), /^제4조를 다음과 같이 한다\./);
  assert.equal(S({ no: '3', title: 'a', body: 'x' }, { type: 'delete', no: '3' }), '제3조를 삭제한다.');
  assert.match(S(null, { type: 'insert', no: '3의2', title: '특례', body: '내용' }), /^제3조의2를 다음과 같이 신설한다\. \| 제3조의2\(특례\) 내용$/);
});

test('raRo·raEul: 받침·숫자 읽기에 따른 조사', () => {
  const c = load();
  assert.equal(c.raRo('16일'), '로');      // ㄹ 받침
  assert.equal(c.raRo('3만원'), '으로');
  assert.equal(c.raRo('5'), '로');
  assert.equal(c.raRo('3'), '으로');
  assert.equal(c.raEul('규정'), '을');
  assert.equal(c.raEul('규칙서'), '를');
});

test('raAbBuild: 부칙 도우미 — 시행일만이면 한 문장, 여럿이면 조로 나눔', () => {
  const c = load();
  const RA = c.__RA();
  RA.amend.title = '여비규정';
  RA.amend.changes = [{ type: 'modify', no: '5', title: '여비', body: 'x' }];
  RA.amend.ab = { eff: 'after', months: '3', apply: false, trans: false, other: false };
  assert.equal(c.raAbBuild('amend'), '이 규정은 발령 후 3개월이 경과한 날부터 시행한다.');
  Object.assign(RA.amend.ab, { eff: 'date', date: '2027년 1월 1일', apply: true, applyWhat: '출장을 명하는 경우', trans: true });
  const t = c.raAbBuild('amend').split('\n');
  assert.equal(t[0], '제1조(시행일) 이 규정은 2027년 1월 1일부터 시행한다.');
  assert.equal(t[1], '제2조(적용례) 제5조의 개정규정은 이 규정 시행 이후 최초로 출장을 명하는 경우부터 적용한다.');
  assert.match(t[2], /^제3조\(경과조치\) /);
  // 다른 내규의 개정: 영향 분석의 조 인용 정정에서 만든다
  RA.amend.ab = { eff: 'issue', other: true };
  RA.amend.impact = { outer: [{ reg: '국외여비지침', hits: [{ no: '3', cites: '5', text: '「여비규정」 제5조', suggest: '「여비규정」 제5조 → 제6조' }] }] };
  const o = c.raAbBuild('amend').split('\n');
  assert.equal(o[1], '제2조(다른 내규의 개정) 국외여비지침 일부를 다음과 같이 개정한다.');
  assert.equal(o[2], '제3조 중 “「여비규정」 제5조”를 “「여비규정」 제6조”로 한다.');
});

test('raClauseFmt: 표준 조문 자리표시자와 조사', () => {
  const c = load();
  const t = c.raClauseFmt('{head:이} 정하고 {deputy:은} 돕는다. 이 {kind}에 따른다.', '지침');
  assert.ok(!/[{}]/.test(t));
  assert.match(t, /이 지침에 따른다\.$/);
});

test('완성도: 위임 조항 표시·종류 추정·조 번호 목록', () => {
  const c = load();
  assert.equal(c.raDelArt({ art: '제33조(기술지원)' }), '제33조');
  assert.equal(c.raDelArt({ art: '제33조', title: '기술지원' }), '제33조');
  assert.equal(c.raCatOf('업무용 드론 운영지침'), '지침');
  assert.equal(c.raCatOf('여비규정 시행세칙'), '시행세칙');
  assert.equal(JSON.stringify(c.raArtList('제31조 제2항, 32조의2')), JSON.stringify(['31', '32의2']));
  assert.equal(JSON.stringify(c.raArtList('31, 32')), JSON.stringify(['31', '32']));
});

test('완성도: 개정문 조사(제7조의3을)·대비표 <신 설> 표시·밑줄 구간', () => {
  const c = load();
  assert.equal(c.raAmendSentences(null, { type: 'insert', no: '7의3', title: 't', body: 'b' }).head, '제7조의3을 다음과 같이 신설한다.');
  assert.equal(c.raAmendSentences({ no: '7의6', title: 't', body: 'b' }, { type: 'delete', no: '7의6' }).head, '제7조의6을 삭제한다.');
  const r = c.raCmpCell({ no: '5', title: 'a', body: '① 가.\n② 나.' }, { no: '5', title: 'a', body: '① 가.\n② 나.\n③ 다.' }, false);
  assert.match(r[2], /<신 설>/);
  const runs = c.raHtmlRuns('숙박비 <u class="ra-d">3만원&amp;</u><br>끝');
  assert.equal(JSON.stringify(runs), JSON.stringify([{ s: '숙박비 ', u: '' }, { s: '3만원&', u: 'd' }, { s: '\n끝', u: '' }]));
});

test('완성도: 손대지 않은 조문은 개정 대상에서 뺀다', () => {
  const c = load();
  const RA = c.__RA();
  RA.amend.changes = [{ type: 'modify', no: '1', title: '목적', body: '같음' }, { type: 'insert', no: '1의2', title: 'x', body: 'y' }];
  // _raArts 가 없으면(현행 미상) 모두 바뀐 것으로 본다
  assert.equal(c.raEffChanges().length, 2);
});

test('완성도: 절차 — 대안 단계는 조건이 맞는(soft) 쪽을 고르고, 일정에 미정 단계를 셈한다', () => {
  const c = load();
  const RA = c.__RA();
  RA.proc.ans = { level: 'reg' };
  const ids = c.raProcSteps().map(s => s.id);
  assert.ok(ids.includes('review'), ids.join(','));          // 상급위원회 내규심의가 요약에서 빠지지 않는다
  const st = c.raProcState();
  const sc = c.raSchedule(st.live);
  assert.ok(sc.total > 0);
  assert.equal(typeof sc.tbd, 'number');
});

test('알리오: 검색어 추정·옛 판 괄호 제거', () => {
  const c = load();
  const RA = c.__RA();
  RA.enact.title = '임직원 여비규정'; assert.equal(c.raAlioGuess('enact'), '여비');
  RA.enact.title = '업무용 드론 운영지침'; assert.equal(c.raAlioGuess('enact'), '드론');
  RA.amend.title = '여비규정'; assert.equal(c.raAlioGuess('amend'), '여비');
  assert.equal(c.alioBase('인사규정(2023년 1월 개정)'), '인사규정');
});

test('알리오: 규정 체계 비교 주제어·이유서 다른 기관 사례', () => {
  const c = load();
  const orgs = ['한국농어촌공사'];
  assert.equal(c.raBenchKey('여비규정(2023년 1월 개정)', orgs), '여비');
  assert.equal(c.raBenchKey('한국농어촌공사 인사규정 시행세칙', orgs), '인사');
  assert.equal(c.raBenchKey('임직원 행동강령 운영지침', orgs), '행동강령');
  assert.ok(c.raBenchHas(['개인정보보호'], '개인정보보호') && !c.raBenchHas(['여비'], '인사'));
  const RA = c.__RA();
  RA.enact.refs = { 'alio|C1|9|5': { reg: '드론 운영규정', org: '한국농어촌공사', no: '5', title: '비행 승인', body: '…', src: 'alio' } };
  RA.enact.title = '드론 운영지침';
  const o = c.raOutReason(c.raDocCtx('enact'));
  const it = o.items.find(x => /다른 공공기관 사례/.test(x.t));
  assert.ok(it && it.s[0] === '한국농어촌공사 「드론 운영규정」 제5조(비행 승인)');
});

test('단계별 화면: 앞 단계가 끝나야 넘어가고, 저장된 단계가 막히면 앞으로 돌린다', () => {
  const c = load();
  const RA = c.__RA();
  RA.enact.step = 4;                                   // 초안 없이 문서 단계로 저장돼 있으면
  assert.equal(c.raWizStep('enact'), 2);               // 초안 단계로
  assert.match(c.raWizGate('enact', 3), /초안/);
  RA.enact.draft = { text: '제1조(목적) 가.' };
  assert.equal(c.raWizGate('enact', 4), '');
  assert.equal(c.raWizStep('enact'), 4);
  RA.amend.step = 2; RA.amend.slug = ''; RA.amend.pasted = false; RA.amend.changes = [];
  assert.equal(c.raWizStep('amend'), 0);               // 내규를 고르지 않았으면 첫 단계
  RA.amend.slug = '여비규정';
  assert.equal(c.raWizStep('amend'), 1);               // 수정안이 없으면 고치기 단계
  const html = c.raWiz('enact', [0, 1, 2, 3, 4].map(i => () => `<p>${i}</p>`));
  assert.match(html, /aria-current="step"/);
  assert.match(html, /<p>4<\/p>/);
});

test('raSubst: 분수·낫표는 통째로, 공통 조사는 따옴표 밖으로', () => {
  const c = load();
  const r1 = JSON.stringify(c.raSubst('출석위원 2분의 1 이상의 찬성으로 의결한다.', '출석위원 3분의 1 이상의 찬성으로 의결한다.'));
  assert.ok(r1.includes('2분의 1') && r1.includes('3분의 1'), r1);
  const r2 = JSON.stringify(c.raSubst('「공공기관의 운영에 관한 법률」에 따른다.', '「공공기관의 운영에 관한 법률 시행령」에 따른다.'));
  assert.ok(r2.includes('「공공기관의 운영에 관한 법률」') && r2.includes('시행령」'), r2);
  const r3 = JSON.stringify(c.raSubst('여비는 3만원을 지급한다.', '여비는 5만원을 지급한다.'));
  assert.ok(r3.includes('3만원') && !r3.includes('3만원을'), r3);
});

test('raBenchSame: 같은 조 제목 판정', () => {
  const c = load();
  assert.ok(c.raBenchSame('출장비', '출장비'));
  assert.ok(c.raBenchSame('출장비지급', '출장비지급기준'));
  assert.ok(!c.raBenchSame('목적', '목적외사용금지'));
  assert.ok(!c.raBenchSame('', '목적'));
});

test('_raNormalize: 손상된 저장본은 구역별로 기본값을 채운다', () => {
  const c = load();
  const n = c._raNormalize({ enact: { title: 'X', dels: 'bad' }, amend: { slug: '감사규정', changes: null, sel: 3 }, bulk: 1, tab: 5, extra: 1 });
  assert.equal(n.enact.title, 'X');
  assert.ok(Array.isArray(n.enact.dels) || n.enact.dels.length === 0);
  assert.equal(n.amend.slug, '감사규정');
  assert.equal(n.amend.changes.length, 0);
  assert.equal(typeof n.amend.sel, 'object');
  assert.equal(n.bulk.old, '');
  assert.equal(n.tab, 'agent');
  assert.equal(n.extra, 1);
  assert.equal(c._raNormalize(null).tab, 'agent');
});

test('raParse·raDocLaw: 조문 칸의 부칙과 별표를 살린다', () => {
  const c = load();
  const p = c.raParse('제1조(목적) 가.\n제2조(지급) 수당은 별표 1과 같다.\n[별표 1] 수당 지급 기준\n구분 금액');
  assert.equal(p.articles.length, 2);
  assert.ok(!p.articles[1].body.includes('별표 1]'));
  assert.match(p.appendix, /^\[별표 1\]/);
  const RA = c.__RA();
  RA.enact.title = '수당 규칙';
  RA.enact.draft = { text: '제1조(목적) 가.\n부    칙\n이 규칙은 2027년 1월 1일부터 시행한다.\n[별표 1] 수당 지급 기준', addenda: '' };
  const law = c.raDocLaw(c.raDocCtx('enact'));
  assert.match(law, /2027년 1월 1일부터 시행한다/);
  assert.match(law, /부 {4}칙[\s\S]*\[별표 1\] 수당 지급 기준/);
});

test('raSwapTerm: 낱말을 바꾸고 뒤 조사를 맞춘다', () => {
  const c = load();
  assert.equal(c.raSwapTerm('재단은 재단이사장을 둔다. 재단의 장', '재단', '농진원', true).text, '농진원은 재단이사장을 둔다. 농진원의 장');
  assert.equal(c.raSwapTerm('위원회를 둔다', '위원회', '심의단', true).text, '심의단을 둔다');
  assert.equal(c.raSwapTerm('「구 지침」으로 정한다', '구 지침', '새 지침서', false).text, '「새 지침서」으로 정한다');
});

test('raQtyDiff: 금액·기간·분수 바뀜을 찾는다', () => {
  const c = load();
  const d = c.raQtyDiff('숙박비는 3만원, 기간은 30일로 한다.', '숙박비는 5만원, 기간은 30일로 한다.');
  assert.equal(JSON.stringify(d), JSON.stringify({ from: ['3만원'], to: ['5만원'] }));
  assert.equal(c.raQtyDiff('2분의 1 이상', '3분의 2 이상').to[0], '3분의2');
  assert.equal(c.raQtyDiff('원장이 정한다', '기관장이 정한다'), null);
});

test('raAmendSentences: 삭제 문형·단서·순서·끝에 덧붙인 항·별표 괄호', () => {
  const c = load();
  const S = (o, n) => c.raAmendSentences(o, n).head;
  const b = { no: '7', title: 't', body: '① 가는 한다.\n② 나는 한다.\n③ 다는 한다.' };
  assert.equal(S(b, { ...b, body: '① 가는 한다.\n② 삭제\n③ 다는 한다.' }), '제7조제2항을 삭제한다.');
  const d = { no: '25', title: 't', body: '① 가.\n② 여비를 지급할 수 있다. 다만, 해당 여비는 받을 수 없다.' };
  assert.equal(S(d, { ...d, body: '① 가.\n② 여비를 지급할 수 있다.' }), '제25조제2항 단서를 삭제한다.');
  assert.equal(S({ ...d, body: '① 가.\n② 여비를 지급할 수 있다.' }, d), '제25조제2항에 단서를 다음과 같이 신설한다.');
  const t = { no: '28', title: 't', body: '① 가는 3일로 한다.\n② 나는 2만원으로 한다.' };
  assert.equal(S(t, { ...t, body: t.body + '\n③ 다.\n④ 라.' }), '제28조에 제3항 및 제4항을 각각 다음과 같이 신설한다.');
  const r = c.raAmendSentences(t, { ...t, body: '① 가는 5일로 한다.\n② 나는 3만원으로 한다.' }).head;
  assert.ok(r.indexOf('“3일”') < r.indexOf('“2만원”'), r);
  const x = { no: '11', title: 't', body: '수수료는 〔별표 2〕와 같다. 기타 사항은 따로 정한다.' };
  assert.equal(S(x, { ...x, body: '수수료는 〔별표 3〕와 같다. 기타 사항은 따로 정한다.' }), '제11조 중 “〔별표 2〕”를 “〔별표 3〕”으로 한다.');
});

test('raFullRenumber: 전부개정은 조 번호를 다시 매기고 내부 인용도 고친다', () => {
  const c = load();
  const F = { arts: [
    { no: '1', title: '목적', body: '이 규칙은 …' },
    { no: '2', title: '', body: '', deleted: true },
    { no: '3', title: '위원회', body: '제4조에 따른 위원과 「상법」 제4조를 본다.' },
    { no: '3의2', title: '간사', body: '제3조의 위원회에 간사를 둔다.' },
    { no: '4', title: '위원', body: '가.' }] };
  const r = c.raFullRenumber(F);
  assert.equal(r.arts.map(a => a.no).join(','), '1,2,3,4');
  assert.equal(r.arts[1].body, '제4조에 따른 위원과 「상법」 제4조를 본다.');
  assert.equal(r.arts[2].body, '제2조의 위원회에 간사를 둔다.');
});

test('경과조치·조사 교체: ①② 부칙 변환, 최대 조 번호, 금액 쉼표·연도, 괄호 붙은 내규명', () => {
  const c = load();
  vm.runInContext(`raTransItems=()=>[{no:'5',txt:'x'}]; raDirty=()=>{}; _raSave=()=>{}; raRerender=()=>{};`, c);
  const add = (title, addenda) => vm.runInContext(`RA.amend.title=${JSON.stringify(title)}; RA.amend.addenda=${JSON.stringify(addenda)}; raTransAdd(); RA.amend.addenda`, c);
  assert.equal(add('업무처리 규칙(구 직무발명 보상규칙)', '①(시행일) 이 규칙은 2024. 1. 1.부터 시행한다.\n②(적용례) 가.'),
    '제1조(시행일) 이 규칙은 2024. 1. 1.부터 시행한다.\n제2조(적용례) 가.\n제3조(경과조치) 이 규칙 시행 당시 종전의 제5조에 따라 진행 중인 사항에 대해서는 종전의 규정에 따른다.');
  assert.match(add('여비규정', '제1조(시행일) 가.\n제3조(경과) 나.\n제5조는 다.'), /\n제4조\(경과조치\)/);
  assert.equal(c.raQtyDiff('1,000원 2024년', '1000원 2025년'), null);
  assert.equal(c.raSwapTerm('재단으로서 재단이었다', '재단', '농진원', false).text, '농진원으로서 농진원이었다');
});

test('개정문 문형: 어미를 조사로 떼지 않음·낱말 삭제·안쪽 따옴표·같은 항', () => {
  const c = load();
  const S = (no, ob, nb) => c.raAmendSentences({ no, title: 't', body: ob }, { no, title: 't', body: nb, type: 'modify' }).head;
  assert.equal(S('4', '원장은 수당을 지급하는 경우 통보한다.', '원장은 수당을 지급할 수 있는 경우 통보한다.'), '제4조 중 “지급하는”을 “지급할 수 있는”으로 한다.');
  assert.equal(S('9', '원장은 예산의 범위에서 수당을 지급할 수 있다.', '원장은 수당을 지급할 수 있다.'), '제9조 중 “예산의 범위에서 ”를 삭제한다.');
  assert.ok(!/““/.test(S('11', '용어는 다음과 같다.\n1. “직원”이란 정규직을 말한다.\n2. “부서”란 팀을 말한다.', '용어는 다음과 같다.\n1. “직원”이란 정규직을 말한다.\n2. “부서”란 팀과 실을 말한다.')));
  assert.equal(S('8', '① 가.\n② 다음 각 호.\n1. 갑\n2. 을\n3. 병', '① 가.\n② 다음 각 호.\n1. 갑\n2. 삭제\n3. 병\n4. 정'), '제8조제2항제2호를 삭제하고, 같은 항에 제4호를 다음과 같이 신설한다.');
  const B = '① 위원회는 7명으로 구성한다.\n② 위원장은 원장이 된다.';
  const r = c.raCmpCell({ no: '5', title: '위원회', body: B }, { no: '5', title: '위원회의 구성', body: B }, true);
  assert.equal(r[3], '제5조(위원회의 구성) ① (현행과 같음)\n② (현행과 같음)');
  assert.equal(r[2], '제5조(위원회) ① (생 략)\n② (생 략)');
});

test('항·호 중간 신설: 번호 밀림 문형과 대비표 “(현행 제N항과 같음)”', () => {
  const c = load();
  const S = (no, ob, nb) => c.raAmendSentences({ no, title: 't', body: ob }, { no, title: 't', body: nb, type: 'modify' });
  const O = '① 위원회는 7명으로 구성한다.\n② 위원장은 원장이 된다.\n③ 위원은 원장이 임명한다.';
  const N = '① 위원회는 7명으로 구성한다.\n② 간사 1명을 둔다.\n③ 위원장은 원장이 된다.\n④ 위원은 원장이 임명한다.';
  const r = S('5', O, N);
  assert.equal(r.head, '제5조제3항을 제4항으로, 제2항을 제3항으로 하고, 같은 조에 제2항을 다음과 같이 신설한다.');
  assert.deepEqual([...r.lines], ['② 간사 1명을 둔다.']);
  assert.equal(S('8', '① 가.\n② 다음 각 호와 같다.\n1. 갑\n2. 을\n3. 병', '① 가.\n② 다음 각 호와 같다.\n1. 갑\n2. 새\n3. 을\n4. 병').head,
    '제8조제2항제3호를 제4호로, 제2호를 제3호로 하고, 같은 항에 제2호를 다음과 같이 신설한다.');
  const t = c.raCmpCell({ no: '5', title: 't', body: O }, { no: '5', title: 't', body: N }, true);
  assert.match(t[3], /③ \(현행 제2항과 같음\)\n④ \(현행 제3항과 같음\)$/);
  assert.match(t[2], /<신 설>/);
});

test('심의 제출: 심의안건서·규제심사서·부패영향평가 기초자료·점검표', () => {
  const c = load();
  vm.runInContext(`_raArts={articles:[{no:'15',title:'숙박비',body:'① 숙박비는 실비로 지급한다.\\n② 추가 지급은 10분의 3 범위에서 한다.\\n③ 받으려는 자는 증빙을 제출하여야 한다.'}]};
    RA.amend.title='여비규정'; RA.amend.slug='여비규정'; RA.amend.purpose='추가 지급 한도를 현실화하려는 것임.';
    RA.amend.changes=[{type:'modify',no:'15',title:'숙박비',body:'① 숙박비는 실비로 지급한다.\\n② 추가 지급은 10분의 5 범위에서 한다.\\n③ 받으려는 자는 증빙을 제출하여야 한다.\\n④ 원장의 승인을 받아야 한다.'}];
    RA.proc.ans={level:'rule',minor:'n',public:'n',multi:'y',impact:'y',burden:'y'};
    Object.assign(raSub_('amend'),{dept:'경영지원팀',proposer:'팀장 홍길동',meet:'2026-11-30'});`, c);
  const B = c.raDocsBuild('amend');
  assert.match(B.agenda, /「여비규정」 일부개정\(안\)을 붙임과 같이 의결한다\./);
  assert.match(B.agenda, /한국농업기술진흥원 경영지원팀 팀장 홍길동/);
  assert.match(B.agenda, /숙박비 조정\(10분의3 → 10분의5\)\(안 제15조\)/);
  assert.match(B.regul, /제15조\(숙박비\): ④ 원장의 승인을 받아야 한다\./);   // 바뀐 항만(그대로 둔 ③ 제출 의무는 빼고)
  assert.ok(!/증빙을 제출/.test(B.regul));
  assert.match(B.corrupt, /■ 개정/);
  const ck = c.raSubmitCheck('amend', B).map(x => x.st + ':' + x.t).join('\n');
  assert.match(ck, /warn:여러 부서 소관/);
  assert.match(ck, /제출 기한: 2026\. 11\. 23\./);
  const blocks = c.raDocBlocks(B, ['agenda', 'law', 'cmp', 'regul']);
  assert.ok(blocks.filter(b => b.t === 'table').length >= 3 && blocks.some(b => b.t === 'break'));
});

test('심의 제출: 절차 미답은 단정하지 않고, 의견 집계·붙임·규제 판단 기본값', () => {
  const c = load();
  vm.runInContext(`_raArts={articles:[{no:'17',title:'근무지내 출장',body:'① 4시간 이상인 자에게는 1만원을 지급한다.'}]};
    RA.amend.title='여비규정'; RA.amend.changes=[{type:'modify',no:'17',title:'근무지내 출장',body:'① 4시간 이상인 자에게는 1만5천원을 지급한다.'}]; RA.proc.ans={};
    Object.assign(raSub_('amend'),{opinions:[{who:'갑',what:'찬성',res:'일부 반영'},{who:'을',what:'반대',res:'검토 중'}]});`, c);
  const B = c.raDocsBuild('amend');
  assert.match(B.agenda, /대국민 사전예고: ○○\(해당 여부 확인\)/);
  assert.match(B.agenda, /일부 반영 1건, 미반영 0건, 검토 중 1건/);
  assert.match(B.agenda, /조정\(1만원 → 1만5천원\)/);
  assert.match(B.agenda, /재정 소요: 연간 ○○원/);                     // 금액이 바뀌면 재정 소요 자리
  assert.match(B.regul, /\| -$/m);                                    // 규제가 없으면 판단 기본값은 “-”
  const ag = c.raAgendaBlocks(B.c, 'amend', ['agenda', 'law']);
  assert.match(c.raBlocksText(ag), /붙임  개정안 1부\.  끝\./);       // 한 건이면 번호 없이
  assert.ok(c.raSubmitCheck('amend', B).some(x => x.st === 'err' && /반영 여부를 정하지 않은 의견 1건/.test(x.t)));
  assert.equal(c.raLawDate('2027. 1. 1.'), '2027년 1월 1일');
});

test('AI 산출물 검토: 원문 대비 수정 집계·검토 확인·문서 표기', () => {
  const c = load();
  const RA = c.__RA();
  RA.amend.model = 'gemini:x';
  RA.amend.changes = [
    { type: 'modify', no: '5', title: '일비', body: '일비는 3만원으로 한다.', ai: '일비는 3만원으로 한다.', aiTitle: '일비' },
    { type: 'modify', no: '6', title: '숙박비', body: '숙박비는 실비로 한다.', ai: '숙박비는 7만원으로 한다.', aiTitle: '숙박비' },
    { type: 'modify', no: '7', title: '식비', body: '식비는 2만원으로 한다.' },          // 사람이 직접 고친 조(AI 원문 없음)
  ];
  const pv = c.raAiProv('amend');
  assert.equal(`${pv.total}/${pv.same}/${pv.edited}`, '2/1/1');
  assert.match(c.raAiChip(RA.amend.changes[0], 0), /AI 원문 그대로/);
  assert.match(c.raAiChip(RA.amend.changes[1], 1), /사람이 고침/);
  assert.equal(c.raAiChip(RA.amend.changes[2], 2), '');
  assert.match(c.raAiMarkText('amend'), /AI가 쓴 조문 2개 중 1개 담당자 수정.*검토 확인 전/);
  c.raMeSet('주임 홍길동'); c.raAiConfirm('amend', true);
  assert.match(c.raAiMarkText('amend'), /검토: 주임 홍길동 \(/);
  RA.amend.changes[0].body = '일비는 4만원으로 한다.';                          // 확인 뒤 조문을 고치면 확인이 풀린다
  assert.equal(c.raAiOk('amend'), false);
  assert.match(c.raAiMarkText('amend'), /검토 확인 전/);
  c.raAiConfirm('amend', true);
  assert.equal(c.raAiOk('amend'), true);
  RA.amend.aiMark = false;
  assert.equal(c.raAiMarkBlocks('amend').length, 0);
  // 제정: 초안 원문과 조별로 견준다
  RA.enact.draft = { text: '제1조(목적) 가.\n제2조(정의) 나를 고침.', ai: '제1조(목적) 가.\n제2조(정의) 나.', model: 'gemini:x' };
  const pe = c.raAiProv('enact');
  assert.equal(`${pe.total}/${pe.same}/${pe.edited}`, '2/1/1');
  RA.enact.draft = { text: '제1조(목적) 가.', ai: '', template: true };
  assert.equal(c.raAiProv('enact'), null);                                   // 표준 골격(규칙 기반)은 AI 산출물이 아니다
});

test('AI 검토 보완: 사전검토 AI 의견·이유 수정 시 확인 해제·자문 회신 수정', () => {
  const c = load();
  const RA = c.__RA();
  // 조문은 사람이 썼어도 AI 사전검토 의견을 쓰면 확인 대상
  RA.amend.changes = [{ type: 'modify', no: '5', title: '일비', body: '일비는 3만원으로 한다.' }];
  RA.amend.review = { model: 'gemini:x', rows: [{ id: 'need', t: '필요성', ref: '제8조', status: 'ok', items: [], ai: '필요성이 인정됨' }], overall: '적합' };
  const pv = c.raAiProv('amend');
  assert.equal(`${pv.total}/${pv.review}`, '0/gemini:x');
  assert.match(c.raAiMarkText('amend', ['law', 'review']), /AI 사전검토 의견 활용\(gemini:x\)/);
  assert.match(c.raAiMarkText('amend', ['law']), /규칙 기반/);                    // 의견서를 넣지 않으면 AI 표기 없음
  assert.equal(c.raLedgerMeta('amend', 'amend', ['law', 'review']).ai, 'gemini:x');
  // 확인 뒤 개정 이유를 고치면 확인이 풀린다
  c.raMeSet('주임 홍길동'); c.raAiConfirm('amend', true);
  assert.equal(c.raAiOk('amend'), true);
  RA.amend.purpose = '이유를 고침';
  assert.equal(c.raAiOk('amend'), false);
  // 자문 회신: 고치면 담당자 수정으로 남고 검토 확인이 풀린다
  RA.advise.res = { question: 'q', conclusion: '가능', answer: 'a [1]', ai: true, model: 'gemini:x', reviewed: true,
    sources: [{ id: 1, reg: '여비규정', no: '15', title: '여비' }], basis: [{ src: 1, point: 'x', verified: false }, { src: 1, point: 'y', verified: true }], cite_check: { n: 2, ok: 1 } };
  c.raAdvSet('answer', '고친 회신 [1]');
  const d = RA.advise.res;
  assert.equal(`${d.edited}/${d.reviewed}`, 'true/false');
  c.raAdvBasisDel(0);
  assert.equal(`${d.cite_check.n}/${d.cite_check.ok}`, '1/1');
  assert.match(c.raAdvText(d), /담당자 수정 · 검토: 주임 홍길동\(검토 확인 전\)/);
});

test('자문 회신: 근거를 빼면 인용 안내도 남은 근거에 맞춘다', () => {
  const c = load();
  const RA = c.__RA();
  RA.advise.res = { question: 'q', conclusion: '해당 규정', answer: 'a [1]', ai: true, model: 'm', sources: [{ id: 1, reg: '여비규정', no: '15', title: '여비' }],
    basis: [{ src: 1, point: 'x', verified: false }, { src: 1, point: 'y', verified: false }, { src: 1, point: 'z', verified: true }],
    cite_check: { n: 3, ok: 1 }, caveats: ['AI가 인용한 문장 2건은 근거 조문에서 그대로 확인하지 못했습니다. 해당 조문 원문과 대조하세요.', '기타'] };
  c.raAdvBasisDel(0);
  assert.match(RA.advise.res.caveats[0], /^AI가 인용한 문장 1건은/);
  c.raAdvBasisDel(0);
  assert.equal(JSON.stringify(RA.advise.res.caveats), JSON.stringify(['기타']));
});

test('자문 회신: 고른 법령해석례만 회신서 참고로 넣고 번호를 이어 간다', () => {
  const c = load();
  const d = { question: 'q', conclusion: '가능', answer: 'a [1]', ai: false, sources: [{ id: 1, reg: '여비규정', no: '15', title: '여비', role: 'main' }],
    basis: [{ src: 1, point: 'x' }], conditions: ['조건'], caveats: ['유의'],
    expc: { items: [{ id: '1', title: '해석례 하나', by: '법제처', date: '2021.02.24', no: '21-0001', pick: true }, { id: '2', title: '해석례 둘' }] } };
  const t = c.raAdvText(d);
  assert.match(t, /4\. 근거[\s\S]*5\. 참고\(법제처 법령해석례 — 정부 법령에 대한 해석으로, 내규에 그대로 적용되지 않을 수 있음\)\n  가\. 해석례 하나 \(법제처 2021\.02\.24 회신, 안건번호 21-0001\)\n\n6\. 유의사항/);
  assert.doesNotMatch(t, /해석례 둘/);
  d.expc.items[0].pick = false;
  assert.match(c.raAdvText(d), /4\. 근거[\s\S]*\n\n5\. 유의사항/);
  const v = c.raAdvExpcView(d);
  assert.match(v, /expcInfoP|해석례 하나/);
  assert.match(c.raAdvExpcView({ expc: { loading: 1 } }), /찾는 중/);
  assert.match(c.raAdvExpcView({ expc: { items: [], error: '' } }), /찾지 못했습니다/);
  assert.equal(c.raAdvExpcView({}), '<div id="raAdvExpc"></div>');
});

test('건강검진: 시행일 확인 대상은 법령과 행정규칙 등', () => {
  const c = load();
  assert.equal(c.raHealthNorms({ laws: ['국가공무원법'], rules: ['종자관리요강'] }).join(','), '국가공무원법,종자관리요강');
  assert.equal(c.raHealthNorms({ laws: ['국가공무원법'] }).join(','), '국가공무원법');
});

test('같은 문장 찾기: 결과 표시와 수정안이 바뀌면 다시 찾으라는 안내', () => {
  const c = load();
  const RA = c.__RA();
  RA.amend.changes = [{ type: 'modify', no: '9', title: '회의', body: '개최 14일 전까지 통보한다.' }];
  assert.match(c.raCfView(), /다른 곳에도 있는지 찾습니다/);
  RA.amend.cf = { sig: c.raCfSig(), items: [{ no: '9', old_vals: ['10일'], new_vals: ['14일'], text: 't',
    places: [{ slug: 's', title: '가규칙 시행세칙', no: '2', art: '회의', text: '개최 10일 전까지', vals: ['10일'], same_reg: false, related: true }] }] };
  const v = c.raCfView();
  assert.match(v, /10일<\/span> → <span class="ra-val">14일/);
  assert.match(v, /관련 내규/);
  assert.doesNotMatch(v, /다시 찾으세요/);
  RA.amend.changes[0].body = '개최 21일 전까지 통보한다.';
  assert.match(c.raCfView(), /다시 찾으세요/);
  RA.amend.cf = { sig: c.raCfSig(), items: [] };
  assert.match(c.raCfView(), /같은 문장을 가진 다른 곳이 없습니다/);
});

test('곧 시행되는 상위법: 확인 전 안내·D-n·인용 내규·오래된 확인 경고', () => {
  const c = load();
  const RA = c.__RA();
  assert.match(c.raUpcomingView({ upcoming: [] }, 0), /아직 법제처에서 확인하지 않았습니다/);
  RA.health.law = { '근로기준법': { ef: '20250101', at: Date.now() } };
  assert.match(c.raUpcomingView({ upcoming: [], today: '20261027' }, 1), /180일 안에 시행되는/);
  const v = c.raUpcomingView({ today: '20261027', upcoming: [{ law: '근로기준법', ef: '20261126', anc: '20261001', type: '일부개정', kind: 'law',
    regs: [{ slug: 'a', title: '가규정' }, { slug: 'b', title: '나규정' }, { slug: 'c', title: '다' }, { slug: 'd', title: '라' }, { slug: 'e', title: '마' }] }] }, 1);
  assert.match(v, /D-30/);
  assert.match(v, /2026\. 11\. 26\./);
  assert.match(v, /외 1개/);
  assert.equal(c.raDday('20261231', '20261027'), 65);
  RA.health.law = { '근로기준법': { ef: '20250101', at: Date.now() - 9 * 864e5 } };
  assert.match(c.raUpcomingView({ upcoming: [], today: '20261027' }, 1), /9일 지났습니다/);
});

test('유관기관 수치 비교: 개정안에서 항목·단위 추정, 통계·참고 문장', () => {
  const c = load();
  const RA = c.__RA();
  vm.runInContext("_raArts={articles:[{no:'15',title:'일비',body:'① 국내여행자의 일비는 1일 2만원으로 한다.',deleted:false}]}", c);
  RA.amend.changes = [{ type: 'modify', no: '15', title: '일비', body: '① 국내여행자의 일비는 1일 25,000원으로 한다.' }];
  const g = c.raValGuess();
  assert.equal(`${g.item}|${g.unit}|${g.val}|${g.old}`, '일비|원|25000|20000');
  const st = c.raValStats([20000, 30000, 25000, 25000]);
  assert.equal(`${st.n}|${st.min}|${st.max}|${st.med}`, '4|20000|30000|25000');
  assert.equal(c.raValFmt(25000, '원'), '25,000원');
  const B = { item: '일비', unit: '원', at: '2026. 10. 27.', rows: [
    { org: '가기관', use: true, matches: [{ first: 20000 }] }, { org: '나기관', use: false, matches: [{ first: 90000 }] },
    { org: '다기관', use: true, matches: [{ first: 30000 }] }, { org: '라기관', use: true, matches: [] }] };
  assert.equal(c.raValText(B), '유관 기관 사규(알리오, 2026. 10. 27. 조회)의 일비: 2곳 중앙값 25,000원(20,000원~30,000원). 가기관 20,000원, 다기관 30,000원.');
});

test('조문 연혁: 이전 판이 없을 때 안내, 바뀐 판은 이전·이 판 비교', () => {
  const c = load();
  vm.runInContext(`_raHist={'s|15':{success:true,rows:[{label:'현행',exists:true,title:'일비',body:'일비는 3만원',changed:false}]}}`, c);
  assert.match(c.raHistView('s', '15'), /이전 판이 없습니다/);
  vm.runInContext(`_raHist={'s|15':{success:true,rows:[
    {label:'현행 2026년 개정',date:'',exists:true,title:'일비',body:'일비는 3만원으로 한다.',changed:true},
    {label:'개정 전 보관본',date:'2026-01-01',exists:true,title:'일비',body:'일비는 2만원으로 한다.',changed:false},
    {label:'처음 판',date:'2025-01-01',exists:false,title:'',body:'',changed:false}]}}`, c);
  const v = c.raHistView('s', '15');
  assert.match(v, /바뀜/);
  assert.match(v, /신설/);
  assert.match(v, /이전 판[\s\S]*ra-d[\s\S]*이 판[\s\S]*ra-i/);
});

test('별표·서식 수정: 머리 줄 조 번호·개정문 문형·대비표·전체 반영', () => {
  const c = load();
  // 머리 줄의 관련 조문(범위 포함)
  assert.equal(JSON.stringify(c.raAppxCites('〔별표 2〕〈 제10조부터 제13조까지 및 제15조제1항 관련 〉')), JSON.stringify(['10', '11', '12', '13', '15']));
  assert.equal(JSON.stringify(c.raAppxCites('[별지 제1호 서식] <제7조의2 관련>')), JSON.stringify(['7의2']));
  const RA = c.__RA();
  RA.amend.slug = 's'; RA.amend.title = '여비규정';
  vm.runInContext(`_raArts=${JSON.stringify({ title: '여비규정', articles: [{ no: '15', title: '일비', body: '일비는 별표 2에 따른다.', deleted: false }],
    appendix: [{ id: '별표 2', head: '〔별표 2〕〈 제15조 관련 〉', body: '국내여비지급표\n일 비\n25,000' }, { id: '별표 3', head: '〔별표 3〕〈 제12조 관련 〉', body: '표3' }] })}`, c);
  // 고친 조문과 관련된 별표를 담는다(제15조 → 별표 2만)
  RA.amend.appx = [];
  assert.equal(JSON.stringify(c.raAppxForArts(['15'])), JSON.stringify(['별표 2']));
  assert.equal(RA.amend.appx.length, 1);
  assert.equal(c.raEffAppx().length, 0);                                      // 아직 안 고침 → 개정문·대비표에서 뺀다
  RA.amend.appx[0].body = '국내여비지급표\n일 비\n30,000';
  assert.equal(c.raEffAppx().length, 1);
  assert.equal(c.raAppxSentence(RA.amend.appx[0]), '별표 2를 별지와 같이 한다.');
  assert.equal(c.raAppxSentence({ type: 'delete', id: '별표 3' }), '별표 3을 삭제한다.');
  assert.equal(c.raAppxSentence({ type: 'insert', id: '별지 제4호 서식' }), '별지 제4호 서식을 별지와 같이 신설한다.');
  // 대비표: 바뀐 줄만 남고 나머지는 (생 략)
  RA.amend.abbr = true; RA.amend.changes = [];
  const rows = c.raCmpRows();
  assert.equal(rows.length, 1);
  assert.match(rows[0][2], /25,000/); assert.match(rows[0][3], /30,000/); assert.match(rows[0][2], /\(생 략\)/);
  // 개정문: 조문 문장 뒤에 별표 문장, 부칙 뒤에 바뀐 별표 전체
  const ctx = c.raDocCtx('amend');
  const law = c.raDocLaw(ctx);
  assert.match(law, /별표 2를 별지와 같이 한다\./);
  assert.ok(law.indexOf('부    칙') < law.indexOf('〔별표 2〕'));
  assert.match(law, /30,000/); assert.doesNotMatch(law, /표3/);          // 고치지 않은 별표 3은 일부개정문에 안 붙는다
  // 점검용 전체 글에는 별표가 모두(고친 대로) 붙는다
  const full = c.raAmendFullText();
  assert.match(full.text, /30,000/); assert.match(full.text, /표3/); assert.doesNotMatch(full.text, /25,000/);
  // 삭제·신설까지 반영한 전체 별표
  RA.amend.appx.push({ type: 'delete', id: '별표 3' }, { type: 'insert', id: '별표 4', head: '〔별표 4〕', body: '새 표' });
  assert.equal(JSON.stringify(c.raAppxAll().map(x => x.id)), JSON.stringify(['별표 2', '별표 4']));
  // 같은 문장 찾기 요청에 별표 수정분이 ‘별표’ 번호로 들어간다
  assert.ok(c.raCfChanges().some(x => x.no === '별표' && /30,000/.test(x.body)));
});

test('별표 수정: 대비표는 길잡이 줄만 남기고 접기, 주요 내용 자동 생성, 별표만 고쳐도 다음 단계', () => {
  const c = load();
  const RA = c.__RA();
  RA.amend.slug = 's'; RA.amend.title = '여비규정'; RA.amend.changes = []; RA.amend.abbr = true;
  vm.runInContext(`_raArts=${JSON.stringify({ title: '여비규정', articles: [{ no: '15', title: '일비', body: '일비는 별표 2에 따른다.', deleted: false }],
    appendix: [{ id: '별표 2', head: '〔별표 2〕〈 제15조 관련 〉', body: '국내여비지급표\n(단위 : 원)\n구 분\n철도운임\n일 비\n제1호\n실비\n25,000\n실비\n제2호\n실비\n25,000\n실비' }] })}`, c);
  RA.amend.appx = [{ type: 'modify', id: '별표 2', head: '〔별표 2〕〈 제15조 관련 〉', body: '국내여비지급표\n(단위 : 원)\n구 분\n철도운임\n일 비\n제1호\n실비\n30,000\n실비\n제2호\n실비\n30,000\n실비' }];
  const rows = c.raCmpRows();
  assert.equal(rows.length, 1);
  const cur = rows[0][2].split('\n'), neu = rows[0][3].split('\n');
  assert.equal(cur[0], '〔별표 2〕〈 제15조 관련 〉');                        // 머리 줄은 남는다
  assert.ok(cur.includes('제1호') && cur.includes('제2호') && cur.includes('구 분'));   // 길잡이 줄
  assert.equal(cur.filter(l => l === '(생 략)').length, 6);                    // 바뀌지 않은 줄 묶음(6곳)은 각각 하나로
  assert.equal(cur.filter(l => l === '25,000').length, 2);
  assert.equal(neu.filter(l => l === '30,000').length, 2);
  assert.ok(cur.length < 14);
  // 주요 내용: 표의 숫자 바뀜을 단위와 함께
  const ctx = c.raDocCtx('amend');
  assert.equal(JSON.stringify(c.raMainItems(ctx)), JSON.stringify(['별표 2(국내여비지급표) 조정(25,000원 → 30,000원)']));
  // 별표만 고쳐도 확인·검토 단계로 넘어간다
  assert.equal(c.raWizGate('amend', 2), '');
  assert.equal(c.raWizDone('amend', 1), true);
  RA.amend.appx[0].body = RA.amend.appx[0].body.replace(/30,000/g, '25,000');
  assert.match(c.raWizGate('amend', 2), /수정안/);
});

test('개정문 역적용(raApplyAmend): 글자 바꾸기·단서·항 신설·번호 밀기·조 삭제·별표', () => {
  const c = load();
  const arts = [
    { no: '5', title: '여비', body: '① 일비는 1일 2만원으로 한다.\n② 숙박비는 실비로 한다. 다만, 상한을 둔다.\n③ 식비는 2만원으로 한다.', deleted: false },
    { no: '6', title: '정산', body: '정산은 7일 이내에 한다.', deleted: false },
    { no: '7', title: '폐지', body: '폐지할 조문이다.', deleted: false },
  ];
  const law = ['여비규정 일부를 다음과 같이 개정한다.', '',
    '제5조제1항 중 “2만원”을 “3만원”으로 하고, 같은 조 제2항 단서를 삭제하고, 같은 조에 제4항을 다음과 같이 신설한다.', '④ 교통비는 실비로 한다.', '',
    '제6조의 제목 “정산”을 “정산 등”으로 하고, 같은 조에 단서를 다음과 같이 신설한다.', '다만, 국외여행은 14일 이내에 한다.', '',
    '제7조를 삭제한다.', '',
    '제6조의2를 다음과 같이 신설한다.', '제6조의2(특례) ① 원장이 정한다.', '② 세부사항은 따로 정한다.', '',
    '별표 2를 별지와 같이 한다.', '',
    '부    칙', '이 규정은 발령한 날부터 시행한다.', '',
    '〔별표 2〕〈 제5조 관련 〉', '국내여비지급표', '30,000'].join('\n');
  const r = c.raApplyAmend(arts, law, [{ id: '별표 2', head: '〔별표 2〕〈 제5조 관련 〉', body: '국내여비지급표\n25,000' }]);
  assert.equal(r.errors.length, 0, JSON.stringify(r.errors));
  const by = Object.fromEntries(r.arts.map(a => [a.no, a]));
  assert.equal(by['5'].body, '① 일비는 1일 3만원으로 한다.\n② 숙박비는 실비로 한다.\n③ 식비는 2만원으로 한다.\n④ 교통비는 실비로 한다.');
  assert.equal(by['6'].title, '정산 등'); assert.equal(by['6'].body, '정산은 7일 이내에 한다. 다만, 국외여행은 14일 이내에 한다.');
  assert.ok(by['7'].deleted);
  assert.equal(by['6의2'].title, '특례'); assert.equal(by['6의2'].body, '① 원장이 정한다.\n② 세부사항은 따로 정한다.');
  assert.equal(r.appx[0].body, '국내여비지급표\n30,000');
  // 번호 밀기 + 가운데 신설
  const r2 = c.raApplyAmend(arts, '여비규정 일부를 다음과 같이 개정한다.\n\n제5조제3항을 제4항으로, 제2항을 제3항으로 하고, 같은 조에 제2항을 다음과 같이 신설한다.\n② 끼워 넣는 항이다.\n\n부    칙\n시행한다.', []);
  assert.equal(r2.errors.length, 0);
  assert.equal(r2.arts[0].body, '① 일비는 1일 2만원으로 한다.\n② 끼워 넣는 항이다.\n③ 숙박비는 실비로 한다. 다만, 상한을 둔다.\n④ 식비는 2만원으로 한다.');
  // 지운 항은 번호를 남기고 “삭제”, 비교 정규화는 끝 항의 “삭제”와 지움을 같게 본다
  const r3 = c.raApplyAmend(arts, '여비규정 일부를 다음과 같이 개정한다.\n\n제5조제3항을 삭제한다.\n\n부    칙\n시행한다.', []);
  assert.equal(r3.arts[0].body.split('\n')[2], '③ 삭제');
  assert.equal(c.raRtNorm(r3.arts[0]), c.raRtNorm({ ...arts[0], body: arts[0].body.split('\n').slice(0, 2).join('\n') }));
});

test('raRoundTrip: 수정안으로 만든 개정문을 되돌려 적용하면 일치', () => {
  const c = load(); const RA = c.__RA();
  vm.runInContext(`_raArts=${JSON.stringify({ title: '여비규정', articles: [{ no: '15', title: '일비', body: '① 일비는 1일 2만원으로 한다.\n② 숙박비는 실비로 한다.', deleted: false }], appendix: [{ id: '별표 2', head: '〔별표 2〕〈 제15조 관련 〉', body: '표\n25,000' }] })}`, c);
  Object.assign(RA.amend, { slug: 's', title: '여비규정', lawStyle: 'fine', fullRev: false, addenda: '', purpose: '', main: [], selx: {},
    changes: [{ type: 'modify', no: '15', title: '일비', body: '① 일비는 1일 3만원으로 한다.\n② 숙박비는 실비로 한다.\n③ 식비는 2만원으로 한다.' }],
    appx: [{ type: 'modify', id: '별표 2', head: '〔별표 2〕〈 제15조 관련 〉', body: '표\n30,000' }] });
  const rt = c.raRoundTrip();
  assert.ok(rt.ok, JSON.stringify(rt.diffs) + JSON.stringify(rt.errors));
  assert.equal(rt.n, 1); assert.equal(rt.nx, 1);
  RA.amend.lawStyle = 'art';
  assert.ok(c.raRoundTrip().ok);
});

test('조 번호 도구: 이동·맞교환·빈 번호 메우기 — 인용 자동 정정·개정문·대비표·역적용', () => {
  const c = load(); const RA = c.__RA();
  const arts = [
    { no: '1', title: '신청', body: '① 신청은 제3조에 따라 한다.\n② 제4조를 준용한다.', deleted: false },
    { no: '2', title: '폐지', body: '', deleted: true },
    { no: '3', title: '심사', body: '심사는 위원회가 한다. 「공공기관의 운영에 관한 법률」 제8조는 그대로 둔다.', deleted: false },
    { no: '4', title: '결정', body: '결정은 원장이 한다.', deleted: false },
  ];
  vm.runInContext(`_raArts=${JSON.stringify({ title: '시험규칙', articles: arts, appendix: [] })}`, c);
  Object.assign(RA.amend, { slug: 's', title: '시험규칙', lawStyle: 'fine', fullRev: false, addenda: '', purpose: '', main: [], selx: {}, appx: [], changes: [], mv: {} });
  // 인용 정정은 같은 내규의 조만(「법률」 제8조는 그대로)
  assert.equal(c.raRetargetRefs('제7조와 제8조, 「공공기관의 운영에 관한 법률」 제8조', { '7': '6', '8': '7' }), '제6조와 제7조, 「공공기관의 운영에 관한 법률」 제8조');
  // 빈 번호 메우기: 삭제된 제2조 자리를 채워 3→2, 4→3
  c.raMvFill();
  assert.equal(JSON.stringify(c.raMoves()), JSON.stringify({ '3': '2', '4': '3' }));
  assert.ok(c.raMvValid().ok, JSON.stringify(c.raMvValid()));
  const eff = c.raEffAll();
  assert.equal(JSON.stringify(eff.map(x => [x.no, x.nno, !!x.mvfix, !!x.mvonly])), JSON.stringify([['1', '1', true, false], ['3', '2', false, true], ['4', '3', false, true]]));
  assert.equal(eff[0].body, '① 신청은 제2조에 따라 한다.\n② 제3조를 준용한다.');
  const law = c.raDocLaw(c.raDocCtx('amend'));
  assert.match(law, /제1조제1항 중 “제3조”를 “제2조”로 하고, 같은 조 제2항 중 “제4조”를 “제3조”로 한다\./);
  assert.match(law, /제3조를 제2조로, 제4조를 제3조로 한다\./);                  // 낮은 번호로 내릴 때는 낮은 것부터
  const full = c.raAmendFullText().arts;
  assert.equal(JSON.stringify(full.map(a => a.no)), JSON.stringify(['1', '2', '3']));   // 삭제 표시 제2조는 걷히고 3·4가 2·3으로
  assert.equal(full[1].title, '심사');
  // 대비표: 번호만 바뀌는 조도 행으로(제7조 → 제6조)
  const rows = c.raCmpRows();
  assert.equal(rows.length, 3); assert.match(rows[1][3], /^제2조\(심사\)/);
  // 역적용·왕복
  const rt = c.raRoundTrip(); assert.ok(rt.ok, JSON.stringify(rt.diffs) + JSON.stringify(rt.errors));
  // 맞교환
  RA.amend.mv = { '3': '4', '4': '3' }; RA.amend.changes = [];
  assert.equal(c.raMvSentence(), '제4조를 제3조로, 제3조를 제4조로 한다.');
  const full2 = c.raAmendFullText().arts;
  assert.equal(full2.find(a => a.no === '3').title, '결정'); assert.equal(full2.find(a => a.no === '4').title, '심사');
  assert.equal(full2.find(a => a.no === '1').body, '① 신청은 제4조에 따라 한다.\n② 제3조를 준용한다.');
  const rt2 = c.raRoundTrip(); assert.ok(rt2.ok, JSON.stringify(rt2.diffs) + JSON.stringify(rt2.errors));
  // 유효성: 비어 있지 않은 자리로 옮기면 오류
  RA.amend.mv = { '3': '4' };
  assert.ok(!c.raMvValid().ok);
  // 조 단위 문형에서도 왕복
  RA.amend.mv = { '4': '5' }; RA.amend.lawStyle = 'art';
  assert.ok(c.raRoundTrip().ok);
});

test('자치법규(조례)도 같은 틀: 원문 붙여넣기 → 개정 → “일부개정조례안”·“공포한 날” 부칙·왕복 일치', () => {
  const c = load(); const RA = c.__RA();
  const text = ['제1조(목적) 이 조례는 가온군의 농업기계 임대사업에 필요한 사항을 정함을 목적으로 한다.',
    '제2조(임대 기간) ① 임대 기간은 1회 3일 이내로 한다. 다만, 농번기에는 군수가 5일까지 연장할 수 있다.', '② 기간이 지나면 제3조의 임대료를 더하여 부과한다.',
    '제3조(임대료) 임대료는 [별표 1]과 같다.', '부칙', '이 조례는 공포한 날부터 시행한다.'].join('\n');
  const p = c.raParse(text);
  assert.equal(p.articles.length, 3);
  assert.equal(c.raKind('가온군 농업기계 임대사업 운영 조례'), '조례'); assert.equal(c.raKind('가온군 ○○ 조례 시행규칙'), '규칙'); assert.equal(c.raKind('농림축산식품부 ○○ 훈령'), '훈령');
  assert.equal(c.raEffDefault('조례'), '공포한 날'); assert.equal(c.raEffDefault('규정'), '발령한 날');
  vm.runInContext(`_raArts=${JSON.stringify({ title: '가온군 농업기계 임대사업 운영 조례', revision: '붙여넣은 원문', articles: p.articles, pasted: true, appendix: [] })}`, c);
  Object.assign(RA.amend, { src: 'paste', pasted: true, slug: '', title: '가온군 농업기계 임대사업 운영 조례', lawStyle: 'fine', fullRev: false, addenda: '', purpose: '', main: [], selx: {}, appx: [], mv: {},
    changes: [{ type: 'modify', no: '2', title: '임대 기간', body: '① 임대 기간은 1회 5일 이내로 한다. 다만, 농번기에는 군수가 7일까지 연장할 수 있다.\n② 기간이 지나면 제3조의 임대료를 더하여 부과한다.' }] });
  const ctx = c.raDocCtx('amend'); const law = c.raDocLaw(ctx);
  assert.match(law, /^가온군 농업기계 임대사업 운영 조례 일부개정조례안\n/);
  assert.match(law, /제2조제1항을 다음과 같이 한다\.\n① 임대 기간은 1회 5일 이내로 한다\./);   // 본문·단서 두 곳이 바뀌어 항 전체를 쓴다
  assert.match(law, /부    칙\n이 조례는 공포한 날부터 시행한다\./);
  const rt = c.raRoundTrip(); assert.ok(rt.ok, JSON.stringify(rt.diffs) + JSON.stringify(rt.errors));
});

test('상위법 영향: 한 내규의 후보 조문 여러 개를 한 번에 개정 작업으로', () => {
  const c = load();
  vm.runInContext(`openRegAgent=()=>{}; RA.upper.res={law:'공공기관의 운영에 관한 법률', count:4, reg_count:1, high:2, removed_terms:[], arts:['34'],
    candidates:[{reg:'정관',slug:'jeonggwan',no:'44',title:'준용',specific:[],terms:[],cites:['공운법'],snippet:'…'},
                {reg:'정관',slug:'jeonggwan',no:'11',title:'임원의 결격사유',specific:['제34조'],terms:[],cites:[],snippet:'…'},
                {reg:'정관',slug:'jeonggwan',no:'13의2',title:'노동이사',specific:[],terms:[],cites:['공운법'],snippet:'…'},
                {reg:'정관',slug:'jeonggwan',no:'39',title:'공고',specific:['제11조'],terms:[],cites:[],snippet:'…'}]};`, c);
  const html = c.raUpperResView();
  assert.ok(html.includes('4개 조문 모두 개정'), '묶음 머리에 모두 개정 단추');
  assert.ok(html.includes('이 조만 개정'), '조마다는 “이 조만 개정”');
  c.raUpperToAmend('jeonggwan', '44|11|13의2|39');
  const A = c.__RA().amend;
  assert.equal(A.slug, 'jeonggwan');
  assert.equal(Object.keys(A.sel).sort().join(','), '11,13의2,39,44');
  assert.equal(A.step, 1, '의도와 조문이 있으니 고치기 단계로');
  assert.ok(A.intent.includes('공공기관의 운영에 관한 법률'));
  c.raUpperToAmend('jeonggwan', '11');                       // 한 조만도 그대로
  assert.ok(c.__RA().amend.sel['11']);
});

test('수정안 나눠 요청: 조문 9개 → 4·4·1 묶음, 실패한 묶음은 알림', async () => {
  const c = load();
  const calls = [];
  c.raPost = async (url, b) => { calls.push(b.targets.map(t => t.no).join(','));
    if (b.targets[0].no === '5') return { success: false, error: 'AI 오류: AI 서버 응답이 늦습니다.' };
    return { success: true, draft: { changes: b.targets.map(t => ({ type: 'modify', no: t.no, title: t.title, body: t.body + ' 개정', why: '' })), reason: { purpose: '정비', main: [`${b.targets[0].no} 정비`] }, notes: ['n'], addenda: [] } }; };
  vm.runInContext('raPost=globalThis.raPost', c);
  const T = Array.from({ length: 9 }, (_, i) => ({ no: String(i + 1), title: 't', body: 'b' }));
  const d = await c.raDraftBatched({ mode: 'amend', intent: '정비' }, T);
  assert.equal(calls.length, 3);
  assert.deepEqual(calls.sort(), ['1,2,3,4', '5,6,7,8', '9']);
  assert.equal(d.success, true);
  assert.equal(d.draft.changes.map(x => x.no).join(','), '1,2,3,4,9');
  assert.ok(d.notice.includes('제5조') && d.notice.includes('응답이 늦습니다'));
  assert.equal(d.draft.notes.length, 1);
  const one = await c.raDraftBatched({ mode: 'amend', intent: 'x' }, T.slice(0, 3));   // 4개 이하는 한 번에
  assert.equal(one.success, true); assert.equal(calls.length, 4);
});

test('제정: 열어 본 다른 기관 규정의 조 구성을 초안 요청용으로 모은다', () => {
  const c = load();
  vm.runInContext(`RA.alio={enact:{q:'드론',cat:'',scope:'peer',picked:[],old:false,
    res:{q:'드론',hits:[{orgId:'A1',idx:'7',org:'가공사',title:'드론 운영지침(2025.1.1. 개정)'},{orgId:'B2',idx:'9',org:'나공단',title:'무인비행장치 관리규정'}]},
    open:{'A1|7':{data:{toc:['제1조(목적)','제2조(운영책임자)']}},'B2|9':{loading:true}}}, amend:null};`, c);
  const o = c.raEnactOutline();
  assert.equal(o.length, 1, '불러오지 못한 규정은 뺀다');
  assert.equal(o[0].org, '가공사'); assert.equal(o[0].reg, '드론 운영지침'); assert.equal(o[0].toc.length, 2);
});

test('제정 1단계 안내: 찾는 중·찾음·없음', () => {
  const c = load();
  vm.runInContext(`RA.enact.title='업무용 드론 운영지침'; RA.enact.alioPre={q:'드론',st:'done',orgs:['가공사','나공단'],regs:['가공사 「드론 운영지침」','나공단 「무인비행장치 관리규정」'],refs:3,outline:2};`, c);
  let h = c.raEnactPreView();
  assert.ok(h.includes('<b>2</b>곳') && h.includes('<b>3</b>개') && h.includes('조 구성') && h.includes('보고 고르기'));
  vm.runInContext(`RA.enact.alioPre={q:'드론',st:'none'};`, c); assert.ok(c.raEnactPreView().includes('찾지 못했습니다'));
  vm.runInContext(`RA.enact.alioPre={q:'드론',st:'run'};`, c); assert.ok(c.raEnactPreView().includes('찾는 중'));
});

test('조문별 참고 출처를 입안 시 확인할 점에 넣는다', () => {
  const c = load();
  vm.runInContext(`raRerender=()=>{}; RA.enact.draft={text:'제1조(목적) 가.',notes:['기존'],sources:[{no:'5',title:'비행 승인',src:'다른 기관 2곳 공통 — 가공사 「드론 운영지침」 제4조'}]};`, c);
  assert.ok(c.raEnactSrcView(c.__RA().enact.draft).includes('제5조(비행 승인)'));
  c.raEnactSrcNote(); c.raEnactSrcNote();
  const n = c.__RA().enact.draft.notes;
  assert.equal(n.length, 2, '두 번 눌러도 한 줄');
  assert.ok(n[1].startsWith('다른 기관 참고:') && n[1].includes('가공사'));
});

test('지시문 수치 반영: 표는 열을 맞춰서만, 조문은 낱말 바로 뒤만', () => {
  const c = load();
  const tbl = ['국내여비지급표', '(단위 : 원)', '구 분', '철도운임', '선박운임', '자동차', '운임', '일 비', '(1일당)', '숙박비', '(1야당)', '식 비', '(1일당)',
    '제1호', '실비', '(특실)', '실비', '실비', '25,000', '실비', '25,000',
    '제2호', '실비', '실비', '실비', '25,000', '실비', '(상한액: 서울특별시 100,000, 광역시 80,000,', '그 밖의 지역은 70,000)', '25,000',
    '비고 : 1. 일비는 1일당 지급한다.'].join('\n');
  const q = c.raVqReq('여비규정 제15조의 일비를 3만원으로 올려줘');
  assert.equal(q.key, '일비'); assert.equal(q.val, 30000); assert.equal(q.unit, '원');
  const r = c.raVqInTable(tbl, q);
  assert.equal(r.n, 2); assert.equal(r.where.join(','), '제1호,제2호');
  const L = r.body.split('\n');
  assert.equal(L[18], '30,000'); assert.equal(L[20], '25,000', '식비는 그대로');
  assert.equal(L[25], '30,000'); assert.equal(L[29], '25,000');
  const s = c.raVqInTable(tbl, c.raVqReq('식비를 2만원으로'));
  assert.equal(s.body.split('\n')[20], '20,000'); assert.equal(s.body.split('\n')[18], '25,000');
  // 열 수가 안 맞으면 손대지 않는다
  assert.equal(c.raVqInTable(tbl.replace('\n실비\n25,000\n제2호', '\n25,000\n제2호'), q), null);   // 제1호 칸이 하나 모자람
  // 조문: 낱말 뒤 같은 단위만, 표기 따라
  assert.equal(c.raVqInText('일비는 1일 2만원으로 하고 식비는 1만원으로 한다.', q).body, '일비는 1일 3만원으로 하고 식비는 1만원으로 한다.');
  assert.equal(c.raVqInText('연차휴가는 15일로 한다.', c.raVqReq('연차휴가를 20일로 늘려')).body, '연차휴가는 20일로 한다.');
  assert.equal(c.raVqReq('여비규정을 정비해 줘'), null);
  // 개정 작업에 넣기: 안내·개정 이유
  const A = { title: '여비규정', purpose: '', changes: [{ type: 'modify', no: '15', body: '일비·숙박비 및 식비는 〔별표 2〕에 따라 지급한다.' }], appx: [{ type: 'modify', id: '별표 2', body: tbl, why: '' }] };
  const v = c.raVqApply(A, '일비를 3만원으로 올려줘');
  assert.equal(v.n, 2); assert.ok(A.valNote.includes('별표 2') && A.valNote.includes('확인'));
  assert.equal(A.purpose, '일비를 30,000원으로 조정하려는 것임.');
  assert.equal(A.changes[0].body, '일비·숙박비 및 식비는 〔별표 2〕에 따라 지급한다.', '금액이 없는 조문은 그대로');
  // 검토 보고서 “현황”에 쓸 기록 — 현행 값과 바꿀 값
  assert.equal(A.vqLog.length, 1);
  assert.deepEqual([A.vqLog[0].id, A.vqLog[0].isX, A.vqLog[0].old, A.vqLog[0].neu], ['별표 2', true, '25,000원', '30,000원']);
  const B = { title: 'x', purpose: '', changes: [{ type: 'modify', no: '7', body: '일비는 1일당 25,000원으로 한다.' }], appx: [] };
  c.raVqApply(B, '일비를 3만원으로');
  assert.deepEqual([B.vqLog[0].id, B.vqLog[0].isX, B.vqLog[0].old, B.vqLog[0].neu], ['7', false, '25,000원', '30,000원']);
});

test('대상 고르기: 전부 선택(검색 중이면 찾은 것만, 삭제된 조 빼고)·선택 취소', () => {
  const c = load();
  vm.runInContext(`_raArts={title:'여비규정',articles:[{no:'1',title:'목적',body:'가'},{no:'2',title:'정의',body:'일비'},{no:'3',title:'',body:'삭제',deleted:true}],
    appendix:[{id:'별표 1',head:'',body:'일비 표'},{id:'별지 제1호 서식',head:'',body:'신청서'}]}; RA.amend.slug='여비규정'; RA.amend.sel={}; RA.amend.selx={}; RA.amend.filter='';`, c);
  c.raSelAll(true);
  let A = c.__RA().amend;
  assert.equal(Object.keys(A.sel).sort().join(','), '1,2', '삭제된 조는 빼고');
  assert.equal(Object.keys(A.selx).length, 2);
  c.raSelAll(false); A = c.__RA().amend;
  assert.equal(c.raSelCount(), 0);
  vm.runInContext(`RA.amend.filter='일비';`, c); c.raSelAll(true); A = c.__RA().amend;
  assert.equal(Object.keys(A.sel).join(','), '2'); assert.equal(Object.keys(A.selx).join(','), '별표 1', '찾은 것만');
  assert.ok(c.raArtsView().includes('찾은 것 모두 선택') && c.raArtsView().includes('선택 취소'));
});

test('여러 개 고르는 목록: 전부 선택·선택 취소', () => {
  const c = load();
  vm.runInContext(`raRerender=()=>{}; raRedraw=()=>{};`, c);
  // 문서 받기: 사전검토 전에는 사전검토 의견서를 빼고 전부
  vm.runInContext(`RA.amend.review=null; RA.amend.picks=['law'];`, c);
  c.raPickAll('amend', true);
  let P = c.__RA().amend.picks; assert.ok(P.length > 3 && !P.includes('review'));
  c.raPickAll('amend', false); assert.equal(c.__RA().amend.picks.length, 0);
  // 일괄 정비: 결과의 내규 모두
  vm.runInContext(`raBulkDocsRedraw=()=>{}; RA.bulk.res={regs:[{slug:'a'},{slug:'b'}]}; RA.bulk.sel={a:true};`, c);
  c.raBulkSelAll(true); assert.equal(Object.entries(c.__RA().bulk.sel).filter(([, v]) => v).map(([k]) => k).sort().join(','), ['a', 'b'].join(','));
  c.raBulkSelAll(false); assert.equal(Object.values(c.__RA().bulk.sel).filter(Boolean).length, 0);
  // 제정: 우리 기관 비슷한 규정의 조문(내규별)
  vm.runInContext(`RA.enact.refs={}; RA.enact.sim={regs:[{slug:'s',title:'여비규정',articles:[{no:'1',title:'목적',body:'가'},{no:'2',title:'정의',body:'나'}]}]};`, c);
  c.raRefAll(0, true); assert.equal(Object.keys(c.__RA().enact.refs).length, 2);
  c.raRefAll(0, false); assert.equal(Object.keys(c.__RA().enact.refs).length, 0);
  // 제정: 상위법 위임 조항(검색 중이면 찾은 것만, 다른 법령 고른 것은 그대로)
  vm.runInContext(`raDirty=()=>{}; RA.enact.lawName='농촌진흥법'; RA.enact.lawQ='위임'; RA.enact.dels=[{law:'다른법',art:'제1조'}];
    RA.enact.lawArts=[{label:'제1조',title:'목적',text:'목적'},{label:'제2조',title:'위임',text:'위임한다'},{label:'제3조',title:'',text:'위임된 사항'}];`, c);
  c.raDelAll(true); assert.equal(c.__RA().enact.dels.map(d => d.law + d.art).join(','), ['다른법제1조', '농촌진흥법제2조', '농촌진흥법제3조'].join(','));
  c.raDelAll(false); assert.equal(c.__RA().enact.dels.map(d => d.law).join(','), ['다른법'].join(','));
  // 다른 기관 수치 비교: 수치를 찾은 기관만
  vm.runInContext(`RA.amend.valcmp={item:'일비',unit:'원',rows:[{org:'가',matches:[{first:1}],use:false},{org:'나',matches:[],use:false}]};`, c);
  c.raValUseAll(true); assert.equal(c.__RA().amend.valcmp.rows.map(r => r.use).join(','), [true, false].join(','));
  c.raValUseAll(false); assert.equal(c.__RA().amend.valcmp.rows.map(r => r.use).join(','), [false, false].join(','));
  // 단추 모양: 찾는 중이면 “찾은 것 모두 선택”, 고른 것이 없으면 선택 취소 흐림
  assert.ok(c.raAllNone('a()', 'b()', 0, true).includes('찾은 것 모두 선택'));
  assert.ok(/선택 취소/.test(c.raAllNone('a()', 'b()', 0)) && c.raAllNone('a()', 'b()', 0).includes('disabled'));
  assert.ok(!c.raAllNone('a()', 'b()', 2).includes('disabled'));
});

test('처음 쓰는 사람 안내: 시작 카드·다시 보지 않기·도움말 내용', () => {
  const c = load();
  vm.runInContext(`raRerender=()=>{}; RA.ui={}; RA.agent.steps=[];`, c);
  const h = c.raIntroView();
  assert.ok(h.includes('처음 오셨나요') && h.includes('예시로 해 보기') && h.includes('건강검진 열기') && h.includes('개정 열기') && h.includes('30초 둘러보기'));
  c.raIntroDone(); assert.equal(c.raIntroView(), '', '다시 보지 않기');
  vm.runInContext(`RA.ui={}; RA.agent.steps=[{t:'x',st:'ok',d:''}];`, c);
  assert.equal(c.raIntroView(), '', '에이전트를 한 번 쓴 뒤에는 보이지 않음');
  // 메뉴 설명·용어 풀이
  assert.ok(c.raNavTab('amend').includes('있는 내규 고치기') && c.raNavTab('amend').includes('data-k="amend"'));
  const G = vm.runInContext('RA_GLOSS', c); assert.ok(G.length >= 10 && G.some(([t]) => t === '신구조문대비표'));
  const T = vm.runInContext('RA_TOUR', c); assert.ok(T.length >= 6 && T.every(x => x.length === 3));
  assert.ok(c.raFlow([['x', '한 문장 지시'], ['y', '초안']]).includes('이 화면의 순서'));
});

test('구성 단순화: 메뉴는 작업+더 보기 둘, 예시는 넷만 먼저', () => {
  const c = load();
  vm.runInContext(`raRerender=()=>{}; _raSave=()=>{}; RA.ui={}; RA.agent.steps=[];`, c);
  const N = vm.runInContext('RA_NAV', c);
  assert.equal(N.map(g => g.id).join(','), 'work,more');
  const more = N[1];
  assert.equal(more.parts.flatMap(p => p[1]).join(','), more.tabs.join(','), '소제목 묶음이 더 보기 탭 전체와 같음');
  const nav = c.raNavHtml(true);
  assert.ok(nav.includes('찾아보기') && nav.includes('정비 도구') && nav.includes('관리'));
  const v = c.raAgentView();
  assert.equal((v.match(/class="ra-ag-ex"/g) || []).length, 4, '예시 넷');
  assert.ok(v.includes('예시') && v.includes('더 보기'));
  vm.runInContext(`RA.ui.exMore=true;`, c);
  assert.ok((c.raAgentView().match(/class="ra-ag-ex"/g) || []).length > 4, '더 보기 후 전부');
});

test('고치기 색 표시: 지운 말·넣은 말과 사람이 고친 수정안 판별', () => {
  const c = load();
  const [L, R] = c.raBodyDiff('① 일비는 25,000원으로 한다.\n② 그대로 둔다.', '① 일비는 30,000원으로 한다.\n② 그대로 둔다.\n③ 새 항');
  assert.ok(/<u class="ra-d">25<\/u>/.test(L) && !L.includes('ra-i'), L);
  assert.ok(/<u class="ra-i">30<\/u>/.test(R) && R.includes('<u class="ra-i">③ 새 항</u>') && R.includes('② 그대로 둔다.'), R);
  // 입력칸과 같은 글자·같은 줄 수(뒤 칸 정렬)
  const nb = 'a <b>\n\n둘째 줄', hl = c.raBodyHl('a\n둘째 줄', nb);
  assert.equal(hl.replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>'), nb + '\n');
  assert.equal(c.raBodyHl('', '신설 본문'), '<u class="ra-i">신설 본문</u>\n');
  // AI 수정안은 AI 원문과 견준다
  assert.equal(c.raHumanEdited({ type: 'modify', no: '1', title: 't', body: 'AI 본문', ai: 'AI 본문', aiTitle: 't' }), false);
  assert.equal(c.raHumanEdited({ type: 'modify', no: '1', title: 't', body: 'AI 본문 고침', ai: 'AI 본문', aiTitle: 't' }), true);
});

test('AI 없이 지시문 반영: 낱말 바꾸기·조사 맞춤·대상 자동 찾기·조 삭제', () => {
  const c = load();
  assert.equal(JSON.stringify(c.raRepReq('여비를 출장비로 바꿔')), '{"a":"여비","b":"출장비"}');
  assert.equal(JSON.stringify(c.raRepReq('“기획운영본부”를 “경영기획본부”로 변경')), '{"a":"기획운영본부","b":"경영기획본부"}');
  assert.equal(c.raRepReq('일비를 3만원으로 올려줘'), null, '수치는 낱말 바꾸기가 아님');
  // 조사 맞춤 · 합성어 안쪽은 그대로
  const r = c.raRepJosa('여비는 지급한다. 국내여비와 여비를 정산하고 여비로 쓴다.', '여비', '출장경비');
  assert.equal(r.s, '출장경비는 지급한다. 국내여비와 출장경비를 정산하고 출장경비로 쓴다.'); assert.equal(r.n, 3);
  assert.equal(c.raRepJosa('본부는 여비로', '여비', '출장금').s, '본부는 출장금으로');
  // 고른 조문이 없어도 내규에서 찾아 담고 바꾼다
  vm.runInContext(`_raArts={slug:'s',title:'여비규정',articles:[{no:'1',title:'목적',body:'이 규정은 여비 지급을 정한다.'},{no:'2',title:'정의',body:'용어 뜻'},{no:'7',title:'가족',body:'가족 여비는 지급한다.'}],appendix:[]};
    RA.amend.sel={}; RA.amend.selx={}; RA.amend.changes=[]; RA.amend.appx=[]; RA.amend.purpose='';`, c);
  const A = vm.runInContext('RA.amend', c);
  const v = c.raRuleApply(A, '여비를 출장비로 바꿔');
  assert.equal(v.n, 2); assert.equal(A.changes.map(x => x.no).join(','), '1,7');
  assert.ok(A.changes[0].body.includes('출장비 지급') && A.valNote.includes('2곳') && A.purpose.includes('“출장비”로'));
  // 조 삭제
  vm.runInContext(`RA.amend.changes=[]; RA.amend.sel={};`, c);
  assert.equal(c.raRuleApply(A, '제2조는 삭제해 줘').n, 1); assert.equal(A.changes[0].type, 'delete');
});

test('제정 초안 색 표시: 고친 곳·채울 곳(○○)', () => {
  const c = load();
  const D = { text: '제1조(목적) 이 지침은 비행 계획을 정한다.\n1. ○○\n2. △△', orig: '제1조(목적) 이 지침은 ○○을 정한다.\n1. ○○\n2. △△' };
  const h = c.raEnHl(D);
  assert.ok(h.includes('<mark class="ra-ph">○○</mark>') && h.includes('<mark class="ra-ph">△△</mark>') && /<u class="ra-i">[^<]*비행/.test(h), h);
  assert.equal(c.raPhCount(D.text), 2);
  assert.ok(c.raPhBar(D).includes('<b>2</b>곳') && c.raPhBar(D).includes('다음 채울 곳'));
  assert.ok(c.raPhBar({ text: '끝', orig: '끝' }).includes('채울 곳 없음'));
});

test('사람이 틀리기 쉬운 곳: 애매한 수치는 바꾸지 않고, 낱말은 모든 조사형까지, 없는 말은 알림', () => {
  const c = load();
  // “연차휴가 일수를 20일로” → 일반 낱말(일수)은 앞 낱말을 열쇠로, 낱말 바꾸기로 넘어가지 않음
  assert.equal(c.raVqReq('연차휴가 일수를 20일로 해줘').key, '연차휴가');
  assert.equal(c.raRepReq('일수를 20일로 해줘'), null);
  // 의·에서 같은 조사도 바꾼다
  assert.equal(c.raRepJosa('여비의 지급과 여비에서 뺀다. 여비이나', '여비', '출장비').s, '출장비의 지급과 출장비에서 뺀다. 출장비나');
  vm.runInContext(`_raArts={slug:'s',title:'복무규정',articles:[
      {no:'3',title:'휴가',body:'연차유급휴가 일수는 15일로 한다. 병가 일수는 60일로 한다.'},
      {no:'4',title:'근무',body:'근무시간은 8시간으로 한다.'}],appendix:[]};
    RA.amend.title='복무규정'; RA.amend.sel={}; RA.amend.selx={}; RA.amend.changes=[]; RA.amend.appx=[]; RA.amend.valNote='';`, c);
  const A = vm.runInContext('RA.amend', c);
  // 값이 서로 다른 여러 곳 → 추측하지 않음
  vm.runInContext(`RA.amend.changes=[{type:'modify',no:'3',title:'휴가',body:'연차유급휴가 일수는 15일로 한다. 연차유급휴가 가산 일수는 25일로 한다.'}];`, c);
  const r = c.raRuleApply(A, '연차유급휴가 일수를 20일로');
  assert.equal(r.n, 0); assert.ok(r.ambiguous && A.valNote.includes('자동으로 바꾸지 않았습니다'));
  assert.ok(A.changes[0].body.includes('15일') && A.changes[0].body.includes('25일'));
  // 내규에 없는 말 → 바꾸지 않고 알림, 담았던 카드는 되돌림
  vm.runInContext(`RA.amend.changes=[]; RA.amend.sel={};`, c);
  const m = c.raRuleApply(A, '기획운영본부를 경영기획본부로 바꿔');
  assert.ok(m.missing && A.valNote.includes('일괄 정비')); assert.equal(A.changes.length, 0);
  assert.ok(c.raNear('연차휴가').includes('연차유급휴가'));
});


test('개정문 문형: “같은 항”은 앞 문장의 마지막 항, 통째 괄호 낱말의 조사, 본문이 “제N조”로 시작하는 조', () => {
  const c = load();
  const S = (o, n) => { const r = c.raAmendSentences(o, Object.assign({ type: 'modify' }, n)); return r.head + (r.lines.length ? ' | ' + r.lines.join(' / ') : ''); };
  const o = { no: '16', title: '계약', body: '① 다음과 같다.\n② 다음 각 호의 경우에는 할 수 있다.\n1. 가\n2. 나\n3. 물품매각의 경우에 매수인이 납부한다\n③ 그 밖의 경우에는 정한다.' };
  const h = S(o, { no: '16', title: '계약', body: o.body.replace(/경우에는/g, '때에는').replace('물품매각의 경우에', '물품매각의 때에') });
  assert.ok(!/같은 항 제3호/.test(h) && /제2항제3호|같은 조 제2항제3호/.test(h), h);
  assert.equal(c.raEul('(운영기관)'), '을'); assert.equal(c.raRo('(운영기관)'), '으로');
  const t = S({ no: '6', title: '장소', body: '제4조의 규정에 의하여 의뢰받은 시험은 센터에서 한다.' }, { no: '6', title: '장소', body: '제4조의 규정에 의하여 의뢰받은 시험은 본부에서 한다. 다만, 따로 정한다.' });
  assert.ok(!/^제6조를 다음과 같이 한다\. \| 제4조/.test(t), t);
});

test('조 삭제: 같은 내규에서 그 조를 인용하는 조를 함께 담고, 다른 법령의 같은 번호는 빼기', () => {
  const c = load();
  vm.runInContext(`_raArts={slug:'s',title:'여비규정',articles:[
      {no:'9',title:'가',body:'제20조에 따른 여비를 지급한다.'},
      {no:'10',title:'나',body:'「근로기준법」 제20조에 따른다. 법 제20조도 같다.'},
      {no:'11',title:'다',body:'제20조의2에 따른다.'},
      {no:'20',title:'가족여비',body:'가족에게 지급한다.'},
      {no:'24',title:'사망',body:'① 가족(제20조제1항의 규정에 의한 가족)에게 지급한다.'}],appendix:[]};
    RA.amend.title='여비규정'; RA.amend.sel={}; RA.amend.selx={}; RA.amend.changes=[]; RA.amend.appx=[];`, c);
  assert.equal(c.raCiting('20').map(x => x.no).join(','), '9,24');
  const A = vm.runInContext('RA.amend', c);
  const r = c.raRuleApply(A, '제20조 삭제');
  assert.equal(r.n, 1); assert.equal(r.cites.join(','), '9,24');
  assert.equal(A.changes.map(x => x.no + ':' + x.type).join(','), '9:modify,20:delete,24:modify');
  assert.ok(A.valNote.includes('제9조, 제24조') && A.changes[2].cite === '20');
  assert.ok(c.raChgOldHtml(A.changes[2], c.raOld('24')).includes('<mark class="ra-cite">제20조제1항</mark>'));
});

test('조 번호가 겹치는 내규: 전체 본문에서 빠뜨리지 않고, 왕복 검증이 거짓 불일치를 내지 않음', () => {
  const c = load();
  vm.runInContext(`_raArts={slug:'m',title:'매뉴얼',articles:[
      {no:'4',title:'운영',body:'운영기관은 사업을 관리한다.'},
      {no:'12',title:'계약의 효력',body:'본 협약은 서명한 날부터 효력이 있다.'},
      {no:'12',title:'관계법령의 준수',body:'운영기관은 법령을 지킨다.'}],appendix:[]};
    RA.amend.title='매뉴얼'; RA.amend.slug='m'; RA.amend.lawStyle='fine'; RA.amend.fullRev=false; RA.amend.sel={}; RA.amend.selx={}; RA.amend.appx=[];
    RA.amend.changes=[{type:'modify',no:'4',title:'운영',body:'운영기관은 사업을 총괄한다.'}];`, c);
  const t = c.raAmendFullText();
  assert.equal(t.arts.filter(a => a.no === '12').length, 2, '같은 번호의 두 조가 모두 남음');
  const rt = c.raRoundTrip();
  assert.equal(rt.diffs.length, 0, JSON.stringify(rt.diffs).slice(0, 200));
});

test('조를 적은 요청은 그 조만 바꾸고, 다른 조에 있는 같은 말은 알려만 준다', () => {
  const c = load();
  vm.runInContext(`_raArts={slug:'s',title:'여비규정',articles:[
      {no:'1',title:'목적',body:'여비 지급을 정한다.'},
      {no:'15',title:'일비',body:'여비는 실비로 지급한다. 여비의 정산은 따로 한다.'},
      {no:'20',title:'가족',body:'가족 여비는 지급한다.'}],appendix:[]};
    RA.amend.title='여비규정'; RA.amend.sel={}; RA.amend.selx={}; RA.amend.changes=[]; RA.amend.appx=[]; RA.amend.purpose='';`, c);
  const A = vm.runInContext('RA.amend', c);
  assert.equal(c.raNamedArts('제15조의 여비를 출장비로 바꿔줘').join(','), '15');
  const r = c.raRuleApply(A, '여비규정 제15조의 여비를 출장비로 바꿔줘');
  assert.ok(r.scoped && r.n === 2, JSON.stringify(r));
  assert.equal(A.changes.map(x => x.no).join(','), '15');
  assert.ok(A.changes[0].body.startsWith('출장비는') && A.valNote.includes('다른 조 2곳'), A.valNote);
  // 조 번호가 없으면 내규 전체
  vm.runInContext(`RA.amend.changes=[]; RA.amend.sel={};`, c);
  const r2 = c.raRuleApply(A, '여비를 출장비로 바꿔줘');
  assert.ok(!r2.scoped && A.changes.length >= 2);
  // 적은 조에 없는 말
  vm.runInContext(`RA.amend.changes=[]; RA.amend.sel={};`, c);
  const r3 = c.raRuleApply(A, '제1조의 수당을 보상금으로 바꿔줘');
  assert.ok(r3.missing && r3.scoped && A.valNote.includes('제1조에는'));
});

test('목적만으로 자료조사→보고서: 핵심 낱말·목적 구절·검토 보고서 구성', () => {
  const c = load();
  assert.equal(c.raKeyWords('개인정보 처리지침').join(','), '개인정보');
  assert.ok(!c.raKeyWords('드론 운영지침을 새로 만들어줘').includes('운영'));
  assert.equal(c.raWhyOf('출장비 현실화를 위해 여비규정 제15조의 일비를 3만원으로 올려줘'), '출장비 현실화');
  assert.equal(c.raWhyOf('여비규정 제15조의 일비를 3만원으로'), '');
  vm.runInContext(`RA.enact.title='드론 운영지침'; RA.enact.background='업무용 드론을 안전하게 운영하기';
    RA.enact.draft={text:'제1조(목적) 이 지침은 업무용 드론의 안전한 운영에 필요한 사항을 정함을 목적으로 한다.\\n제2조(비행 승인) 원장이 정한다.',addenda:'',purpose:'업무용 드론의 안전한 운영에 필요한 사항을 정하기 위하여 제정하려는 것임.',main:''};
    RA.enact.research={own:[{reg:'정보보안규칙',slug:'x',arts:[{no:'66',title:'개인정보보호'}]}],laws:[{name:'개인정보 보호법',n:2}],alio:[],alioNote:'알리오에 연결되지 않아 조회하지 못함'};`, c);
  const t = c.raBlocksText(c.raReportBlocks(c.raDocCtx('enact'), 'enact'));
  ['제정 검토 보고', '1. 추진 배경 및 목적', '추진 배경: 업무용 드론을 안전하게 운영하기 위함', '3. 자료조사 결과', '「정보보안규칙」 제66조(개인정보보호)', '「개인정보 보호법」(관련 내규에서 2회 인용)',
    '알리오에 연결되지 않아', '4. 제정 주요 내용', '5. 검토 의견', '6. 향후 추진 일정', '끝.'].forEach(k => assert.ok(t.includes(k), k + '\n' + t));
  assert.equal(vm.runInContext("RA_DOCS.enact[0][0]+RA_DOCS.amend[0][0]", c), 'reportreport');
});

test('웹 인터페이스 지침: 진행 문구는 “…”, 수정안 카드의 입력칸·선택칸에는 이름(aria-label)', () => {
  const src = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '../../assets/reg_agent.js'), 'utf8');
  assert.equal((src.match(/[가-힣A-Za-z)]\.\.\.(?=['`"<)])/g) || []).length, 0, '“...” 대신 “…”');
  const c = load();
  vm.runInContext(`_raArts={slug:'s',title:'여비규정',articles:[{no:'3',title:'정의',body:'여비를 정한다.'}],appendix:[]};
    RA.amend.title='여비규정'; RA.amend.appx=[]; RA.amend.changes=[{type:'modify',no:'3',title:'정의',body:'출장비를 정한다.'}];`, c);
  const h = c.raChangesView();
  ['aria-label="제3조 개정 유형"', 'aria-label="제3조 조 제목"', 'aria-label="제3조 개정안"'].forEach(k => assert.ok(h.includes(k), k));
});

test('수치 지시: 숫자가 낱말 앞에 오는 꼴(“15일의 연차휴가”)도 바꾸고, 낱말 뒤 꼴이 있으면 그쪽만', () => {
  const c = load();
  const q = c.raVqReq('복무규정 제6조의 연차휴가 일수를 20일로 해줘');
  assert.equal(q.key, '연차휴가');
  assert.equal(c.raVqInText('① 1년간 8할 이상 출근한 직원에게는 15일의 연차휴가를 준다.', q).body, '① 1년간 8할 이상 출근한 직원에게는 20일의 연차휴가를 준다.');
  assert.equal(c.raVqInText('15일의 유급 연차휴가를 준다.', q).body, '20일의 유급 연차휴가를 준다.');
  // 낱말 뒤 꼴이 있으면 앞 꼴은 보지 않는다(같은 문장에서 두 번 바꾸지 않음)
  assert.equal(c.raVqInText('연차휴가는 15일로 하고, 10일의 연차휴가는 이월한다.', q).body, '연차휴가는 20일로 하고, 10일의 연차휴가는 이월한다.');
  // 이미 목표 값이면 그대로, 단위가 다르면 손대지 않음
  assert.equal(c.raVqInText('연차휴가는 20일로 한다. 3년의 연차휴가', q).n, 0);
  assert.equal(c.raVqInText('15시간의 연차휴가', q).n, 0);
  // 숫자와 낱말 사이가 멀면 바꾸지 않음
  assert.equal(c.raVqInText('15일 이내에 신청한 직원의 연차휴가', q).n, 0);
});

test('에이전트: 수치 지시를 못 바꾸면 결론 줄에 이유와 비슷한 말 다시 요청 버튼을 둔다', () => {
  const src = fs.readFileSync(path.join(root, 'assets/reg_agent.js'), 'utf8');
  assert.ok(src.includes('값을 찾지 못했습니다`'), '못 찾음 결론');
  assert.ok(src.includes("raAgentRetryKey('${w}')"), '비슷한 말 다시 요청 버튼');
  assert.ok(src.includes('값이 여러 곳에 서로 달라 그대로 두었습니다'), '애매한 값 결론');
  const c = load();
  vm.runInContext(`RA.agent.req='복무규정의 연차휴가 일수를 20일로 해줘'; RA.agent.running=true; _raRetryKey='연차휴가';`, c);
  c.raAgentRetryKey('연차유급휴가');        // 실행 중이면 바꾸지 않는다
  assert.equal(c.__RA().agent.req, '복무규정의 연차휴가 일수를 20일로 해줘');
});

test('다른 기관 프로필: 근거 조항이 빈칸이면 빈 괄호를 쓰지 않고, 기관장 호칭이 달라도 결재선을 알아본다', () => {
  const c = load();
  vm.runInContext(`RA.amend.review={rows:[{t:'내규의 필요성',ref:'',status:'ok',items:[]},{t:'내용의 적합성',ref:'제7조',status:'ok',items:[]}]};`, c);
  const out = c.raOutReview({ title: '복무규정', word: '개정' }, 'amend');
  assert.ok(out.items[0].t.startsWith('내규의 필요성: '), out.items[0].t);
  assert.ok(out.items[1].t.startsWith('내용의 적합성(제7조): '), out.items[1].t);
  vm.runInContext(`RA_ORG=Object.assign({},RA_ORG,{head:'사장'});`, c);
  assert.ok(c.raWho('사장').includes('w-head'));
  assert.ok(c.raWho('주무부서').includes('w-dept'));
});

test('대상 고르기: 조문이 없는 매뉴얼 형식 문서는 빈 목록 대신 이유와 다음 할 일을 알린다', () => {
  const c = load();
  vm.runInContext(`_raArts={slug:'m',title:'여비업무 처리지침',articles:[],appendix:[]}; RA.amend.sel={}; RA.amend.selx={};`, c);
  const h = c.raSelHint();
  assert.ok(h.includes('“제N조” 형식의 조문이 없습니다') && h.includes('원문 붙여넣기'), h);
  vm.runInContext(`_raArts={slug:'s',title:'여비규정',articles:[{no:'1',title:'목적',body:'x'}],appendix:[]};`, c);
  assert.ok(c.raSelHint().includes('고칠 조문이나 별표·서식을 체크하세요'));
});

test('상위법 감시: 확인하지 않은 알림만 세고, 알림 카드에서 영향 조문 찾기로 이어진다', () => {
  const c = load();
  vm.runInContext(`RA.health.watch={at:Date.now(),changes:[
    {law:'근로기준법',kind:'promulgated',ef:'20990301',anc:'20990101',type:'일부개정',prev_ef:'20250101',regs:[{slug:'복무규정',title:'복무규정'}]},
    {law:'국가재정법',kind:'enforced',ef:'20260101',anc:'',type:'',prev_ef:'20240101',regs:[],seen:1}]};`, c);
  assert.equal(c.raWatchNew().length, 1);
  const h = c.raWatchView({ today: '20261104' });
  assert.ok(h.includes('새 개정 공포') && h.includes("raHealthUpper('근로기준법')") && h.includes('복무규정'), h);
  assert.ok(!h.includes('국가재정법'));                 // 확인함 누른 것은 숨김
  vm.runInContext(`RA.health.watch=null;`, c);
  assert.ok(c.raWatchView({ today: '20261104' }).includes('기준으로 저장'));
});

test('에이전트 덮어쓰기 확인: 에이전트가 만든 그대로면 묻지 않고, 사람이 손댄 뒤에만 묻는다', () => {
  const c = load();
  vm.runInContext(`RA.amend.intent='제20조 삭제'; RA.amend.changes=[{type:'delete',no:'20'}]; RA.agent.sig=null;`, c);
  assert.match(c.raAgWorkMsg('amend'), /진행 중인 작업\(수정안 1건\)/);          // 서명이 없으면(사람이 만든 작업) 묻는다
  vm.runInContext(`RA.agent.sig={amend:raWorkSig('amend')};`, c);
  assert.equal(c.raAgWorkMsg('amend'), '');                                       // 에이전트가 만든 그대로
  vm.runInContext(`RA.amend.changes.push({type:'delete',no:'21'});`, c);
  assert.match(c.raAgWorkMsg('amend'), /수정안 2건/);                              // 사람이 손대면 다시 묻는다
  vm.runInContext(`RA.enact.title='드론 지침'; RA.enact.contents='운영';`, c);
  assert.match(c.raAgWorkMsg('enact'), /제정 탭의 진행 중인 작업/);                // 제정 탭 서명은 따로
});

test('건강검진: 오류 목록 탭을 처음 열면 전체 점검을 바로 돌린다(결과가 있으면 다시 돌리지 않음)', () => {
  const c = load();
  const h = c.raHealthSeg('diag');
  assert.match(h, /RA\.health\.v='errors';_raSave\(\);raRerender\('health'\);if\(!RA\.check\.res\)raCheckAll\(\)/);
  assert.ok(!/RA\.health\.v='one'[^"]*raCheckAll/.test(h), '다른 탭은 점검을 돌리지 않는다');
});

test('제정 위임 조항 직접 입력: 대화상자 대신 화면 입력칸(법령명·조항·내용), 법령명이 없으면 담지 않는다', () => {
  const c = load();
  const src = fs.readFileSync(path.join(root, 'assets/reg_agent.js'), 'utf8');
  assert.ok(!/raDelManual\(\)\{[^}]*prompt\(/.test(src), '위임 조항 입력에 prompt 를 쓰지 않는다');
  const form = c.raDelManualForm();
  for (const id of ['raManLaw', 'raManArt', 'raManText']) assert.match(form, new RegExp(`id="${id}"`));
  assert.match(form, /raDelManualAdd\(\)/);
  const vals = { raManLaw: '「드론 활용의 촉진 및 기반조성에 관한 법률」', raManArt: '제13조', raManText: '안전관리에 필요한 사항은 대통령령으로 정한다.' };
  c.document.getElementById = id => (id in vals ? { value: vals[id], focus() {} } : null);
  vm.runInContext(`RA.enact.dels=[]; RA.enact.manOpen=true;`, c);
  c.raDelManualAdd();
  const E = c.__RA().enact;
  assert.equal(JSON.stringify(E.dels), JSON.stringify([{ law: '드론 활용의 촉진 및 기반조성에 관한 법률', art: '제13조', text: '안전관리에 필요한 사항은 대통령령으로 정한다.' }]));
  assert.equal(E.manOpen, false);                                   // 담으면 입력칸을 닫는다
  vals.raManLaw = '  '; E.manOpen = true; c.raDelManualAdd();
  assert.equal(E.dels.length, 1); assert.equal(E.manOpen, true);   // 법령명이 비면 담지 않고 그대로 둔다
});

test('수치 지시: 현행 값을 적으면 그 값만 바꾼다(“2만원을 3만원으로”·“14일에서 30일로”·화살표)', () => {
  const c = load();
  const b17 = '① 근무지내 국내출장의 경우에는 출장여행시간이 4시간 이상인 자에 대하여는 2만원을, 4시간 미만인 자에 대하여는 1만원을 지급한다. 다만, 농진원 차량을 이용하는 경우 등에 대하여는 1만원을 감하여 지급한다.';
  const q = c.raVqReq('여비규정 제17조의 근무지내 출장 여비 2만원을 3만원으로 올려줘');
  assert.equal(q.old, 20000); assert.equal(q.val, 30000); assert.equal(q.unit, '원'); assert.equal(q.key, '여비');
  const r = c.raVqInText(b17, q);
  assert.equal(r.n, 1);
  assert.ok(r.body.includes('4시간 이상인 자에 대하여는 3만원을') && r.body.includes('4시간 미만인 자에 대하여는 1만원을') && r.body.includes('1만원을 감하여'), r.body);
  // 현행 값이 없으면 아무것도 바꾸지 않는다
  assert.equal(c.raVqInText(b17, c.raVqReq('여비 5만원을 6만원으로')).n, 0);
  // “14일에서 30일로”·“N일을 M일로” — 단위 낱말(일에서·원에서)을 찾을 말로 잡지 않는다
  const q2 = c.raVqReq('여비규정 제8조의 정산 기한을 14일에서 30일로 늘려줘');
  assert.equal(q2.old, 14); assert.equal(q2.val, 30); assert.equal(q2.unit, '일');
  assert.equal(c.raVqInText('다음날부터 기산하여 14일 이내 에 정산을 신청하여야 한다. 1일 이상 출장', q2).body, '다음날부터 기산하여 30일 이내 에 정산을 신청하여야 한다. 1일 이상 출장');
  assert.equal(c.raVqReq('연차휴가 15일을 20일로').old, 15);
  // 화살표·“만·천” 섞인 금액·쉼표 숫자
  const q3 = c.raVqReq('일비 2만5천원 → 3만원');
  assert.equal(q3.old, 25000); assert.equal(q3.val, 30000); assert.equal(q3.key, '일비');
  const q4 = c.raVqReq('여비규정의 일비 25,000원→30,000원');
  assert.equal(q4.old, 25000); assert.equal(q4.val, 30000);
  assert.equal(c.raVqInText('일비는 25,000원, 비망가액 1,000원으로 한다.', q4).body, '일비는 30,000원, 비망가액 1,000원으로 한다.');
  // 표: 현행 값을 적었으면 열이 맞고 값도 같은 칸만
  const tbl = ['구 분', '일 비', '식 비', '제1호', '25,000', '25,000', '제2호', '20,000', '25,000', '(단위 : 원)'].join('\n');
  const t = c.raVqInTable(tbl, c.raVqReq('일비 25,000원을 30,000원으로'));
  assert.equal(t.n, 1); assert.equal(t.body.split('\n').slice(3, 9).join(','), '제1호,30,000,25,000,제2호,20,000,25,000');
  // 기존 꼴(현행 값 없이)은 그대로 동작
  assert.equal(c.raVqReq('여비규정 제15조의 일비를 3만원으로 올려줘').old, undefined);
});

test('수치 지시: 같은 현행 값이 여러 조에 있고 무엇인지 적지 않으면 추측하지 않는다', () => {
  const c = load();
  vm.runInContext(`_raArts={slug:'s',title:'여비규정',articles:[
      {no:'17',title:'근무지내 국내출장시의 여비',body:'4시간 이상인 자에 대하여는 2만원을 지급한다.'},
      {no:'30',title:'벌칙',body:'위반하면 2만원을 감한다.'}],appendix:[]};
    RA.amend.title='여비규정'; RA.amend.sel={}; RA.amend.selx={}; RA.amend.changes=[]; RA.amend.appx=[]; RA.amend.valNote=''; RA.amend.purpose='';`, c);
  const A = vm.runInContext('RA.amend', c);
  const r = c.raRuleApply(A, '2만원을 3만원으로 바꿔');
  assert.equal(r.n, 0); assert.ok(r.ambiguous && A.valNote.includes('2곳'), A.valNote); assert.equal(A.changes.length, 0);
  // 무엇인지(여비) 적으면 그 말이 든 조만 바꾼다
  const r2 = c.raRuleApply(A, '출장 여비 2만원을 3만원으로 올려줘');
  assert.equal(r2.n, 1); assert.equal(A.changes.map(x => x.no).join(','), '17');
  assert.ok(A.changes[0].body.includes('3만원을') && A.purpose.includes('2만원을') && A.valNote.includes('현행 2만원'));
});

test('인용 자동 정정: 다른 법률 조에 “및·또는”으로 이어진 조는 건드리지 않는다(AMD-1)', () => {
  const c = load();
  const b32 = '11. 「감염병의 예방 및 관리에 관한 법률」 에 따른 제1급감염병에 대하여 같은 법 제 24조 또는 제25조에 따라 필수예방접종을 할 때';
  const b34 = '병원 진료(「국민건강보험법」 제52조에 따른 건강검진 또는 「감염병의 예방 및 관리에 관한 법률」 제24조 및 제25조에 따른 예방접종을 받는 경우';
  const map = { '25': '26', '26': '25' };
  assert.equal(c.raRetargetRefs(b32, map), b32);
  assert.equal(c.raRetargetRefs(b34, map), b34);
  assert.equal(c.raCiteHits(b32, '25').length, 0); assert.equal(c.raCiteHits(b34, '25').length, 0);
  // 같은 내규 인용은 그대로 정정한다 — 외부 인용 뒤라도 사이에 다른 말이 끼면 내부 인용
  const own = '「국민건강보험법」 제52조에 따른 검진을 받은 사람은 제25조에 따라 신고한다. 제25조 및 제26조를 따른다.';
  assert.equal(c.raRetargetRefs(own, map), '「국민건강보험법」 제52조에 따른 검진을 받은 사람은 제26조에 따라 신고한다. 제26조 및 제25조를 따른다.');
  assert.equal(c.raCiteHits(own, '25').length, 2);
});

test('다른 내규로 바꾸면 앞 내규의 개정 의도·시행일·참고 자료가 남지 않는다(AMD-2)', () => {
  const c = load();
  vm.runInContext(`Object.assign(RA.amend,{slug:'여비규정',title:'여비규정',intent:'제7조 삭제',effective:'2027-01-01',refText:'참고',abbr:false,lawStyle:'plain',rt:{ok:1},cf:{x:1},alioRefs:{a:1},model:'m',vqLog:[1],valNote:'x',changes:[{type:'delete',no:'7'}]});`, c);
  c.raAmendFresh({ slug: '복무규정', title: '복무규정', src: 'reg' });
  const A = vm.runInContext('RA.amend', c);
  assert.equal(A.slug, '복무규정'); assert.equal(A.intent, ''); assert.equal(A.effective, ''); assert.equal(A.refText, '');
  assert.equal(A.changes.length, 0); assert.equal(A.rt, undefined); assert.equal(A.vqLog, undefined); assert.equal(A.valNote, undefined);
  assert.equal(JSON.stringify(A.alioRefs), undefined);
  assert.equal(A.abbr, false); assert.equal(A.lawStyle, 'plain');            // 보기 설정은 유지
});

test('독립 검토 회귀: 현행 값 모드는 적은 말·앞 구절로 가리고, 못 가리면 바꾸지 않는다', () => {
  const c = load();
  vm.runInContext(`_raArts={slug:'s',title:'여비규정',articles:[
      {no:'8',title:'여비의 결제와 정산 등',body:'② 여행을 마친 날부터 14일 이내에 정산을 신청하여야 한다.'},
      {no:'15',title:'일비·숙박비·식비의 지급',body:'② 국외여행자는 귀국 후 14일 이내에 추가지급을 신청한다.'},
      {no:'17',title:'근무지내 국내출장시의 여비',body:'① 4시간 이상인 자에 대하여는 2만원을, 4시간 미만인 자에 대하여는 1만원을 지급한다. 다만, 농진원 차량을 이용하는 경우 등에 대하여는 1만원을 감하여 지급한다.'},
      {no:'34',title:'출산휴가',body:'① 출산전후휴가는 90일로 한다. ② 임신기간이 28주 이상인 경우 유산·사산휴가는 90일까지로 한다.'}],appendix:[]};
    RA.amend.title='여비규정'; RA.amend.sel={}; RA.amend.selx={}; RA.amend.changes=[]; RA.amend.appx=[]; RA.amend.valNote=''; RA.amend.purpose='';`, c);
  const A = vm.runInContext('RA.amend', c);
  // 일비는 2만원인 곳이 없다 — 2만원이 있는 제17조(여비)를 바꾸지 않는다
  let r = c.raRuleApply(A, '일비를 2만원에서 3만원으로 올려줘');
  assert.equal(r.n, 0); assert.ok(r.keyMiss && A.valNote.includes('함께 있는'), A.valNote); assert.equal(A.changes.length, 0);
  // “기한”이 어느 조에도 없으면 14일이 있는 두 조를 모두 바꾸지 않는다
  r = c.raRuleApply(A, '정산 기한 14일을 30일로'); assert.equal(r.n, 0); assert.equal(A.changes.length, 0);
  // 같은 조 안의 1만원 두 곳 — “4시간 미만”으로 가린다
  r = c.raRuleApply(A, '근무지내 출장 4시간 미만 여비 1만원을 2만원으로');
  assert.equal(r.n, 1, A.valNote);
  const b = A.changes.find(x => x.no === '17').body;
  assert.ok(b.includes('미만인 자에 대하여는 2만원을') && b.includes('1만원을 감하여'), b);
  // 가릴 말이 없으면(출산휴가 90일 두 곳) 바꾸지 않는다
  vm.runInContext(`RA.amend.changes=[]; RA.amend.sel={};`, c);
  r = c.raRuleApply(A, '제34조의 90일을 120일로');
  assert.equal(r.n, 0); assert.ok(r.ambiguous && A.valNote.includes('2곳'), A.valNote);
  // 열쇠말 조사: 연차휴가·병가는 그대로, 일반어(시간)는 앞 낱말로
  assert.equal(c.raVqKeyWord('연차휴가'), '연차휴가'); assert.equal(c.raVqKeyWord('병가'), '병가'); assert.equal(c.raVqKeyWord('일비를'), '일비');
  assert.equal(c.raVqReq('복무규정 제14조의 근무 시간을 35시간으로 줄여줘').key, '근무');
  // “2만5천원” 꼴 안내 표기
  vm.runInContext(`_raArts={slug:'x',title:'x',articles:[{no:'5',title:'일비',body:'일비는 2만5천원으로 한다.'}],appendix:[]}; RA.amend.changes=[]; RA.amend.sel={}; RA.amend.valNote='';`, c);
  c.raVqApply(A, '일비 2만5천원을 3만원으로');
  assert.equal(A.changes[0].body, '일비는 3만원으로 한다.'); assert.ok(A.valNote.includes('→ 3만원') && !A.valNote.includes('만천원'), A.valNote);
});

test('독립 검토 회귀: 요청문 가지조 뒤 단위 글자로 시작하는 낱말, 외부 인용 뒤 “의 ○○는”, “이 지침 제N조”', () => {
  const c = load();
  const re = new RegExp(c.RA_REQ_ART ?? vm.runInContext('RA_REQ_ART', c), 'g');
  const nos = t => [...t.matchAll(re)].map(m => m[2] ? `${m[1]}의${m[2]}` : m[1]).join(',');
  assert.equal(nos('사택관리규칙 제6조의3 일반사택 확보 조항 삭제'), '6의3');
  assert.equal(nos('제4조의2 시간외근무 수당'), '4의2');
  assert.equal(nos('제8조의 14일을 30일로'), '8');
  assert.equal(nos('제17조의 2만원을'), '17');
  // 감사규정 시행세칙 제31조② — 앞의 “규정 제25조”(감사규정)는 외부, “제30조제3항”은 같은 세칙
  const t31 = '② 규정 제25조의 이행관리책임자는 제30조제3항에 따라 단기, 중기, 장기로 분류된 사항을 관리한다.';
  assert.equal(c.raCiteHits(t31, '30').length, 1);
  assert.equal(c.raRetargetRefs(t31, { '30': '31' }), t31.replace('제30조제3항', '제31조제3항'));
  // 외부 조 + “의 ○○ 또는” + 조 → 외부
  const t7 = '「근로자참여 및 협력증진에 관한 법률」 제6조제2항의 근로자위원 또는 제26조에 따른 위원';
  assert.equal(c.raCiteHits(t7, '26').length, 0);
  // “이 지침 제6조 … 및 제12조” → 같은 내규
  const t3 = '이 지침 제6조제4호 각목 및 제12조제4항에 따른 조치';
  assert.equal(c.raCiteHits(t3, '12').length, 1);
});

test('현행 값 모드 재검토: 열쇠말 느슨한 일치·내규명 열쇠말·흔한 말 여러 조', () => {
  const c = load();
  vm.runInContext(`_raArts={slug:'s',title:'감사규정',articles:[
      {no:'8',title:'여비의 결제와 정산 등',body:'② 국내 여행자 및 국외 여행자는 여행을 마친 날의 다음날부터 기산하여 14일 이내에 정산을 신청하여야 한다.'},
      {no:'15',title:'일비·숙박비·식비의 지급',body:'② 국외 여행의 경우에는 14일 이내에 추가지급을 신청한다.'},
      {no:'20',title:'전문위원',body:'전문위원의 임기는 2년으로 한다.'},
      {no:'21',title:'전문직위',body:'전문직위에 임용된 사람은 다른 위원회 위원으로 2년 이내 전보할 수 없다.'},
      {no:'24',title:'감사결과 통보',body:'감사결과는 60일 이내에 통보한다.'},
      {no:'27',title:'재심의',body:'재심의 신청은 60일 이내에 처리한다.'}],appendix:[]};
    RA.amend.title='감사규정'; RA.amend.sel={}; RA.amend.selx={}; RA.amend.changes=[]; RA.amend.appx=[]; RA.amend.valNote=''; RA.amend.purpose='';`, c);
  const A = vm.runInContext('RA.amend', c);
  // “국내 … 정산”이 앞 구절·제목에 있는 제8조만(제15조 국외 14일은 그대로)
  let r = c.raRuleApply(A, '국내 출장 정산을 14일에서 30일로');
  assert.equal(r.n, 1, A.valNote); assert.equal(A.changes.map(x => x.no).join(','), '8');
  // “전문위원”이 붙어 있는 조만(전문·위원이 따로 있는 제21조는 아님)
  vm.runInContext(`RA.amend.changes=[]; RA.amend.sel={};`, c);
  r = c.raRuleApply(A, '전문위원 2년을 3년으로');
  assert.equal(r.n, 1, A.valNote); assert.equal(A.changes.map(x => x.no).join(','), '20');
  // 열쇠말이 내규명이면 무엇인지 적지 않은 것 — 60일이 두 조에 있으면 추측하지 않는다(안내 예시에 다른 내규의 말이 박히지 않는다)
  vm.runInContext(`RA.amend.changes=[]; RA.amend.sel={};`, c);
  r = c.raRuleApply(A, '감사규정 60일을 30일로');
  assert.equal(r.n, 0); assert.ok(r.ambiguous && A.valNote.includes('2곳') && !A.valNote.includes('4시간'), A.valNote);
  // 요청문의 다른 말(감사결과·통보)로 가린다
  r = c.raRuleApply(A, '감사결과 통보 60일을 30일로');
  assert.equal(r.n, 1, A.valNote); assert.equal(A.changes.map(x => x.no).join(','), '24');
});

test('문서 근거 조항은 기관 프로필(doc_refs)에서만 — 다른 기관 문서에 농진원 조 번호가 박히지 않는다(ROB-1)', () => {
  const c = load();
  const build = () => { vm.runInContext(`_raArts={slug:'여비규정',title:'여비규정',articles:[{no:'1',title:'목적',body:'이 규정은 여비를 정한다.'},{no:'7',title:'일비',body:'일비는 25,000원으로 한다.'}],appendix:[]};
    Object.assign(RA.amend,{slug:'여비규정',title:'여비규정',sel:{'7':true},changes:[{type:'modify',no:'7',title:'일비',body:'일비는 30,000원으로 한다.',why:''}],appx:[],purpose:'일비 조정',addenda:'이 규정은 발령한 날부터 시행한다.'});`, c);
    return JSON.stringify(c.raDocsBuild('amend')); };
  // 농진원 프로필: 지금까지와 같은 근거(제14조·제16조·제15조의3·제15조의4)
  const koat = build();
  assert.ok(/「내규관리규칙」 제14조\(입안\)·제16조\(내규심의\)/.test(koat) && koat.includes('제15조의4'), koat.slice(0, 300));
  // 가상 기관 프로필: 자기 규칙에 있는 조(제5조·제7조·제6조)만, 없는 조는 근거 문구째 빠진다
  const po = JSON.parse(fs.readFileSync(path.join(root, 'samples/public_org/org_config.json'), 'utf8'));
  c.__setOrg(Object.assign({}, po, { head: po.head, reg_word: po.reg_word || '내규' }));
  const t = build();
  assert.ok(!/제1[4-7]조|제3조의2|제15조의/.test(t), (t.match(/.{30}제1[4-7]조.{20}/) || [''])[0]);
  assert.ok(t.includes('「내규관리규칙」 제5조(제정·개정의 요청)·제7조(심의)'));
  // 근거 조항이 하나도 없는 기관: 근거 문구를 통째로 뺀다
  c.__setOrg(Object.assign({}, po, { doc_refs: {} }));
  assert.equal(c.raRefP('notice'), ''); assert.equal(c.raRefBy('staff'), '');
  assert.ok(!/「내규관리규칙」 제/.test(build()));
});

test('일괄 정비 문서: 별표·서식 바꿈도 정비 대상·대비표에 들어간다(LKP-1)', () => {
  const c = load();
  vm.runInContext(`RA.bulk.res={old:'기획조정실',new:'경영기획실',total:3,reg_count:1,regs:[{slug:'직제규정_시행세칙',reg:'직제규정 시행세칙',count:3,
      articles:[{no:'4',title:'분장',new_title:'분장',old_body:'1. 기획조정실',new_body:'1. 경영기획실',count:1,locs:['제4조']}],
      appx:[{id:'별표 6',head:'[별표 6] 분장업무',new_head:'[별표 6] 분장업무',lines:[['기획조정실 | 예산','경영기획실 | 예산'],['기획조정실 | 감사','경영기획실 | 감사']],count:2}],
      amend_text:'직제규정 시행세칙 일부를 다음과 같이 개정한다.\\n제4조제1호 중 “기획조정실”을 “경영기획실”로 한다.\\n별표 6 중 “기획조정실”을 각각 “경영기획실”로 한다.'}]};
    RA.bulk.sel={'직제규정_시행세칙':true};`, c);
  const D = c.raBulkDocs();
  assert.ok(D.reason.includes('제4조, 별표 6') && D.amend.includes('별표 6 중'), D.reason);
  assert.equal(D.cmp.length, 3);                          // 내규 머리 + 조문 1 + 별표 1
  assert.ok(D.cmp[2][3].includes('경영기획실') && D.cmp[2][2].includes('기획조정실'));
  // 여러 내규를 “다른 내규의 개정” 부칙으로 묶으면 별표 문장도 그 항 안으로 들여 쓴다
  vm.runInContext(`RA.bulk.res.regs.push({slug:'b',reg:'보수규정',count:1,articles:[{no:'2',title:'x',old_body:'기획조정실',new_body:'경영기획실',count:1,locs:['제2조']}],appx:[],amend_text:'보수규정 일부를 다음과 같이 개정한다.\\n제2조 중 “기획조정실”을 “경영기획실”로 한다.'}); RA.bulk.sel.b=true;`, c);
  const D2 = c.raBulkDocs();
  assert.ok(D2.addenda.includes('\n   별표 6 중'), D2.addenda);
});
