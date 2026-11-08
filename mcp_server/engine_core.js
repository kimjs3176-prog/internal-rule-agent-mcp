// MCP 도구가 쓰는 화면 엔진 작업 — 웹 화면의 엔진(assets/reg_agent.js)과 같은 전역에서 돈다.
// Node(vm, mcp_server/engine.mjs)와 QuickJS(파이썬 안, mcp_server/engine.py)가 이 파일을 똑같이 읽어 쓴다.
// 서버 API 는 상대 주소(/api/...)로 부른다. 어디로 보낼지는 바깥 실행기가 정한다(외부 주소는 막는다).
// 입력: __engineRun({op:'agent'|'amend', ...})  출력: 결과 객체(실행기가 JSON 으로 바꾼다)
(function () {
  const plain = s => String(s == null ? '' : s).replace(/<br\s*\/?>/g, '\n').replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
  const oneLine = s => plain(s).replace(/\s+/g, ' ').trim();
  const getJ = async url => (await fetch(url)).json();
  const postJ = async (url, body) => (await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();

  async function init() {
    const cfg = await getJ('/api/regagent/config');
    RA_ORG = Object.assign(cfg.org, { _count: cfg.reg_count, _law: cfg.law !== false });
    return RA;
  }

  // 개정 결과: 개정문·신구조문대비표(글)·개정문 검증
  function amendResult() {
    const rows = raCmpRows().map(r => ({ current: r[2], amended: r[3] }));
    const rt = raRoundTrip();
    return {
      regulation: RA.amend.title,
      amendment_text: raDocLaw(raDocCtx('amend')),
      comparison_table: rows,
      verification: rt ? { ok: !!rt.ok, articles: rt.n, appendices: rt.nx, diffs: (rt.diffs || []).slice(0, 5), errors: (rt.errors || []).slice(0, 5) } : null,
    };
  }

  const lv = { error: '오류', warn: '주의', info: '표기 제안' };
  const checkOf = (iss, keep) => {
    const is = (iss || []).filter(keep || (() => true));
    return { errors: is.filter(i => i.level === 'error').length, warnings: is.filter(i => i.level === 'warn').length, suggestions: is.filter(i => i.level === 'info').length,
      items: is.slice(0, 15).map(i => `${lv[i.level] || i.level}: ${i.msg}`) };
  };
  const reviewOf = rv => rv && rv.success ? {
    ok: rv.rows.filter(r => r.status === 'ok').length, check: rv.rows.filter(r => r.status === 'check').length, warn: rv.rows.filter(r => r.status === 'warn').length,
    criteria: rv.rows.map(r => ({ criterion: r.t, basis: r.ref || '', status: ({ ok: '적합', check: '확인 필요', warn: '보완 필요' })[r.status] || r.status,
      notes: (r.items || []).filter(i => i.status !== 'ok' || /알리오|다른 공공기관/.test(i.msg)).slice(0, 3).map(i => i.msg) })) } : null;
  const refsOut = mode => raAlioRefList(mode).map(r => ({ agency: r.org, regulation: r.reg, article: r.no ? raLbl(r.no) : '', title: r.title || '' }));
  const refsIn = (list, prefix) => Object.fromEntries((list || []).filter(r => r && r.org && r.reg).slice(0, 12)
    .map((r, i) => [`alio|${prefix}|${i}`, { org: String(r.org), reg: String(r.reg), no: String(r.no || ''), title: String(r.title || ''), body: String(r.body || ''), src: 'alio' }]));
  const alioId = h => [h.orgId, h.idx, h.category || '', h.table || 'COMM_RULE', h.idxName || 'RULE_NO', String(h.mod || '').slice(0, 40)].join('|');

  // 문서 세트(심의안건서·개정문·대비표·이유서 등)의 내용. 한글·Word 파일은 바깥 실행기가 서버 API(/api/regagent/hwpx|docx)로 만든다
  function docPayload(mode) {
    const B = raDocsBuild(mode);
    const picks = raPicks(mode).filter(k => k !== 'review' || RA[mode].review);
    const names = Object.fromEntries(RA_DOCS[mode]);
    return { filename: `${B.c.title}_${B.c.word}안`, blocks: raDocBlocks(B, picks), documents: picks.map(k => names[k] || k) };
  }

  async function opAgent(inp, RA) {
    RA.agent.req = String(inp.request || '').slice(0, 500); RA.tab = 'agent';
    const t0 = Date.now(); await raAgentRun();
    const G = RA.agent, mode = G.plan && G.plan.mode;
    const out = {
      mode, seconds: (Date.now() - t0) / 1000,
      conclusion: G.done ? { title: oneLine(G.done.title), detail: oneLine(G.done.sub) } : null,
      steps: (G.steps || []).map(s => ({ step: s.t, status: s.st, detail: oneLine(s.d).slice(0, 400) })),
    };
    const changed = mode === 'amend' && (raEffChanges().length + raEffAppx().length) > 0;
    if (changed) Object.assign(out, amendResult());
    if (mode === 'enact' && RA.enact.draft) out.draft = { title: RA.enact.title, text: RA.enact.draft.text, addenda: RA.enact.draft.addenda || '' };
    if (mode === 'bulk' && RA.bulk.res) out.bulk = { old: RA.bulk.res.old, new: RA.bulk.res.new, regulations: RA.bulk.res.reg_count, places: RA.bulk.res.total,
      amendments: (RA.bulk.res.regs || []).map(r => ({ regulation: r.title, amendment_text: r.amend_text })) };
    if (mode === 'advise' && RA.advise.res) out.advice = { answer: RA.advise.res.answer, conclusion: RA.advise.res.conclusion, basis: (RA.advise.res.basis || []).slice(0, 5) };
    if (mode === 'upper' && RA.upper.res) out.upper = RA.upper.res;
    if (mode === 'compare' && G.pendingAlio) {                  // “다른 기관은 재택근무를 어떻게 규정했어?” — 알리오에서 찾은 규정과 관련 조문
      const P = G.pendingAlio;
      out.compare = { keyword: P.q, agencies_searched: P.R.orgs,
        found: (P.R.hits || []).slice(0, 20).map(h => ({ id: alioId(h), agency: h.org, regulation: alioBase(h.title), enforced: h.enf || '' })),
        opened: (P.R.opened || []).map(({ h, d }) => ({ id: alioId(h), agency: h.org, regulation: alioBase(h.title), url: d.url || '', article_count: d.count,
          articles: (d.articles || []).filter(a => a.rel !== undefined ? a.rel : a.score > 0).slice(0, 3).map(a => ({ article: raLbl(a.no), title: a.title, body: a.body })) })) };
    }
    if ((mode === 'amend' || mode === 'enact') && refsOut(mode).length) out.references = refsOut(mode);
    if (changed || (mode === 'enact' && RA.enact.draft)) out.doc_ready = true;
    if (inp.docs && out.doc_ready) out.doc = docPayload(mode);
    return out;
  }

  async function opAmend(inp, RA) {
    const d = await getJ('/api/regagent/articles?' + (inp.slug ? 'slug=' + encodeURIComponent(inp.slug) : 'title=' + encodeURIComponent(inp.regulation || '')));
    if (!d.success) return { error: d.error || '내규를 찾을 수 없습니다.' };
    _raArts = d;
    const norm = x => String(x || '').replace(/^제\s*/, '').replace(/\s*조$/, '').replace(/\s+/g, '');
    const changes = [], errors = [];
    for (const c of inp.changes || []) {
      const no = norm(c.article), type = c.type || (c.delete ? 'delete' : 'modify');
      const old = raOld(no);
      if (type !== 'insert' && !old) { errors.push(`제${no}조가 「${d.title}」에 없습니다.`); continue; }
      if (type === 'delete') { changes.push({ type, no, title: old.title, body: '' }); continue; }
      if (!String(c.body || '').trim()) { errors.push(`제${no}조의 새 본문(body)이 비었습니다.`); continue; }
      const tt = c.title != null && String(c.title).trim() ? String(c.title) : (old ? old.title : '');      // 비우면 현행 제목
      changes.push({ type, no, title: tt, body: String(c.body).replace(/\r/g, '') });
    }
    const appx = [];
    for (const x of inp.appendix_changes || []) {
      const key = String(x.id || '').replace(/\s+/g, '');                  // “별표2”·“별표 2” 모두
      const ox = raArr(_raArts && _raArts.appendix).find(y => String(y.id || '').replace(/\s+/g, '') === key);
      if (!ox) { errors.push(`${x.id}가 「${d.title}」에 없습니다.`); continue; }
      appx.push({ type: 'modify', id: ox.id, head: x.head != null ? String(x.head) : ox.head, body: String(x.body || '') });
    }
    if (errors.length && !changes.length && !appx.length) return { error: errors.join(' ') };
    Object.assign(RA.amend, { src: 'reg', slug: d.slug, title: d.title, lawStyle: 'fine', fullRev: false, abbr: true, sel: {}, selx: {}, mv: {},
      changes, appx, addenda: String(inp.addenda || ''), purpose: String(inp.reason || ''), main: [], effective: String(inp.effective || ''), intent: String(inp.reason || ''),
      alioRefs: refsIn(inp.references, 'amend') });
    const out = Object.assign({ warnings: errors }, amendResult());
    // 화면의 “조문 점검”과 같은 입력(문서에 실리는 부칙 포함). 오류는 어느 조든 보여 주고, 주의·표기 제안은 고친 조만
    const full = raAmendFullText();
    if (full) {
      const lint = await postJ('/api/regagent/lint', { text: full.text, addenda: raDocCtx('amend').addenda, title: d.title, base_slug: d.slug });
      if (lint.success) {
        const mine = new Set(changes.map(c => c.no));
        RA.amend.lint = lint.issues;
        out.check = checkOf(lint.issues, i => i.level === 'error' || !i.no || mine.has(i.no));
      }
      // 심의 사전검토(기관 심의기준) — 다른 기관 참고 조문을 주면 ‘다른 공공기관 운영 사례’로 들어간다
      const rv = await postJ('/api/regagent/review', Object.assign(raReviewPayload('amend'), { ans: RA.proc.ans || {}, ai: false }));
      if (rv.success) { RA.amend.review = rv; out.review = reviewOf(rv); }
    }
    if (refsOut('amend').length) out.references = refsOut('amend');
    const nos = changes.filter(c => c.type !== 'insert').map(c => c.no);
    if (nos.length) {
      const im = await postJ('/api/regagent/impact', { slug: d.slug, nos, moves: {} });
      if (im.success) out.citation_impact = { summary: im.summary,
        same_regulation: (im.inner || []).slice(0, 10).map(h => `제${h.no}조(${h.title})에서 “${h.text}” 인용${h.suggest ? ' — 제안: ' + h.suggest : ''}`),
        other_regulations: (im.outer || []).slice(0, 10).map(h => `「${h.reg || h.title || ''}」 제${h.no}조에서 “${h.text}” 인용`),
        appendices: (im.appendix || []).slice(0, 10).map(h => typeof h === 'string' ? h : (h.id || h.label || JSON.stringify(h))) };
    }
    out.doc_ready = (raEffChanges().length + raEffAppx().length) > 0;      // 현행과 같은 “수정안”이면 문서를 만들지 않는다(화면과 같음)
    if (!out.doc_ready) out.warnings.push('바뀐 조문·별표가 없습니다(현행과 같음). 고친 본문을 주세요.');
    if (inp.docs && out.doc_ready) { await raResearch('amend'); out.doc = docPayload('amend'); }
    return out;
  }

  // 제정: AI 가 쓴(다른 기관 사례를 참고한) 내규안 → 조문 점검·심의 사전검토·제정 문서 세트
  async function opEnact(inp, RA) {
    const E = RA.enact, text = String(inp.text || '').replace(/\r/g, ''), title = String(inp.title || '').trim().slice(0, 80);
    if (!title) return { error: 'title(만들 내규명)을 주세요.' };
    const p = raParse(text);
    if (!p.articles.length) return { error: 'text 에 “제1조(목적) …” 형식의 조문이 없습니다.' };
    Object.assign(E, { step: 2, title, purpose: String(inp.purpose || ''), background: '', contents: '', dels: [], sim: null, lint: null, review: null, nota: null,
      effective: String(inp.effective || ''), refs: refsIn(inp.references, 'enact') });
    E.category = raCatOf(title) || E.category || '규칙';
    E.draft = { text, addenda: String(inp.addenda || ''), purpose: String(inp.purpose || ''), main: '', notes: [], model: '', template: false, notice: '', ai: '', orig: text, sources: [] };
    const steps = [], step = t => { const s = { t, st: 'run', d: '' }; steps.push(s); return s; }, fin = (s, d, st) => { s.d = d; s.st = st || 'ok'; };
    await raAgCheck('enact', step, fin);
    const out = { title, category: E.category, article_count: p.articles.length, check: checkOf(E.lint), review: reviewOf(E.review) };
    if (refsOut('enact').length) out.references = refsOut('enact');
    out.doc_ready = true;
    if (inp.docs) { await raResearch('enact'); out.doc = docPayload('enact'); }
    return out;
  }

  globalThis.__engineRun = async function (inp) {
    try {
      const RA = await init();
      if (inp.op === 'agent') return await opAgent(inp, RA);
      if (inp.op === 'amend') return await opAmend(inp, RA);
      if (inp.op === 'enact') return await opEnact(inp, RA);
      return { error: `모르는 작업: ${inp.op}` };
    } catch (e) {
      return { error: `엔진 오류: ${(e && e.message) || e}` };
    }
  };
})();
