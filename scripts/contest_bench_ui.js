// 출품용 정량 성과 측정(화면 쪽) — 실제 화면 코드로 대표 과제를 끝까지 처리한 시간과 정확도, 전 내규 개정문 왕복 검증.
//
// 사용법(로컬 서버를 띄운 뒤):  node scripts/contest_bench_ui.js [http://localhost:5100/] [결과.json]
//   · Playwright가 필요하다(npm i playwright 또는 설치된 것 사용). AI 키 없이(규칙 기반) 잰다.
//   · 대표 과제 9건: 에이전트 요청(수치·낱말·조 삭제) / 조 신설 / 조 맞교환 / 부칙 자동 / 검토 보고서 / 문서 내려받기 / 제정 초안
//   · 개정문 왕복 검증: 모든 내규에 조 신설·항 끼워 넣기·조 삭제·문장 추가·조 맞교환을 하나씩 해 보고,
//     만든 개정문을 현행에 다시 적용한 결과가 수정안과 같은지(raRoundTrip) 센다.
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = process.argv[2] || 'http://localhost:5100/';
const OUT = process.argv[3] || '';
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 1000 } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('dialog', d => d.accept());
  await p.goto(BASE, { waitUntil: 'networkidle' }); await p.evaluate(() => { try { localStorage.clear(); } catch (e) {} }); await p.reload({ waitUntil: 'networkidle' });
  const tasks = [];
  const T = async (name, fn) => { const t = Date.now(); let r; try { r = await fn(); } catch (e) { r = { ok: false, note: '오류: ' + e.message.slice(0, 120) }; } tasks.push({ name, sec: +((Date.now() - t) / 1000).toFixed(2), ...r }); };
  const agent = async (q) => { await p.evaluate(() => raTab('agent')); await p.waitForSelector('#raAgIn'); await p.fill('#raAgIn', q); await p.click('.ra-ag-go');
    await p.waitForFunction(() => RA.agent && !RA.agent.running && RA.agent.done, null, { timeout: 120000 });
    return p.evaluate(() => { const rt = raRoundTrip(); return { title: RA.agent.done.title, ch: raEffChanges().map(c => c.type + ':' + c.no), all: RA.amend.changes.map(c => c.type + ':' + c.no), ax: raEffAppx().map(x => x.id),
      body: RA.amend.changes.map(c => c.body).concat(raEffAppx().map(x => x.body)).join('\n'), rt: !!(rt && rt.ok), steps: RA.agent.steps.length }; }); };
  // 1~3) 에이전트 한 문장 요청 → 자료조사·수정안·점검·개정문 검증·검토 보고서까지
  await T('수치 바꾸기 — “여비규정 제15조의 일비를 3만원으로 올려줘”', async () => { const r = await agent('여비규정 제15조의 일비를 3만원으로 올려줘');
    return { ok: /30,000/.test(r.body) && r.rt, note: `별표 ${r.ax.join('·')} 25,000→30,000, 개정문 검증 ${r.rt ? '일치' : '불일치'}, 단계 ${r.steps}개` }; });
  const rep = await p.evaluate(() => { const t = performance.now(); const bl = raReportBlocks(raDocCtx('amend'), 'amend'); let heads = [...new Set((JSON.stringify(bl).match(/\d\. [가-힣 ·및]{2,20}/g) || []))]; const cut = heads.findIndex((h, i) => i > 0 && h.startsWith('1.')); if (cut > 0) heads = heads.slice(0, cut); return { ms: performance.now() - t, n: heads.length, heads }; });
  tasks.push({ name: '검토 보고서 초안(위 요청 결과로)', sec: +(rep.ms / 1000).toFixed(3), ok: rep.n >= 4, note: `${rep.n}개 장: ${rep.heads.join(' / ')}` });
  const ad = await p.evaluate(() => String(RA.amend.addenda || raDocCtx('amend').addenda || ''));
  tasks.push({ name: '부칙(시행일) 자동 작성', sec: 0, ok: /시행한다/.test(ad), note: (ad.split('\n').find(l => /시행한다/.test(l)) || '없음').slice(0, 60) });
  await T('문서 내려받기 — 개정 문서 묶음(한글)', async () => { const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 60000 }), p.evaluate(() => raExport('amend', 'hwpx'))]);
    const f = await dl.path(); const sz = fs.statSync(f).size; return { ok: sz > 2000, note: `${(sz / 1024).toFixed(0)}KB` }; });
  await T('낱말 바꾸기 — “여비규정에서 여비를 출장비로 바꿔줘”', async () => { const r = await agent('여비규정에서 여비를 출장비로 바꿔줘');
    return { ok: r.ch.length > 0 && /출장비/.test(r.body) && r.rt, note: `${r.ch.length}개 조·별표 ${r.ax.length}개, 조사 맞춤, 개정문 검증 ${r.rt ? '일치' : '불일치'}` }; });
  await T('조 삭제 — “여비규정 제20조를 삭제해줘”', async () => { const r = await agent('여비규정 제20조를 삭제해줘');
    return { ok: r.ch.includes('delete:20') && r.rt, note: `삭제 ${r.ch.filter(x => /^delete/.test(x)).join(',')}, 인용하는 조를 수정안 칸에 함께 담음 ${r.all.filter(x => !/^delete/.test(x)).map(x => x.split(':')[1]).join(',') || '없음'}, 개정문 검증 ${r.rt ? '일치' : '불일치'}` }; });
  // 4~5) 개정 화면 — 조 신설·조 맞교환(인용 자동 정정)
  await p.evaluate(async () => { await raAmendStart('여비규정', '여비규정', { force: true, fresh: true }); });
  await p.waitForFunction(() => _raArts && _raArts.articles && _raArts.title === '여비규정', null, { timeout: 30000 });
  await T('조 신설 — 제15조의2 신설 → 개정문·검증', async () => p.evaluate(() => { const A = RA.amend; A.changes = [{ type: 'insert', no: '15의2', title: '숙박비의 정산', body: '숙박비는 출장을 마친 날부터 7일 이내에 정산한다.' }]; A.appx = []; A.mv = {};
    const law = raDocLaw(raDocCtx('amend')), rt = raRoundTrip(); return { ok: /제15조의2를 다음과 같이 신설한다/.test(law) && rt.ok, note: (law.split('\n').find(l => /신설한다/.test(l)) || '').slice(0, 50) + ` / 검증 ${rt.ok ? '일치' : '불일치'}` }; }));
  await T('조 맞교환 — 제16조↔제17조, 인용 자동 정정', async () => p.evaluate(() => { const A = RA.amend; A.changes = []; A.appx = []; A.mv = {}; raMvSet('16', '17'); raMvSet('17', '16');
    const fix = raEffAll().filter(x => x.mvfix).map(x => x.no), rt = raRoundTrip(); return { ok: rt.ok, note: `이동 ${JSON.stringify(raMoves())}, 인용 정정 ${fix.length ? fix.join('·') : '해당 없음'}, 검증 ${rt.ok ? '일치' : '불일치'}` }; }));
  // 6) 제정 — 이름만 넣고 초안 → 점검 → 한글 문서
  await T('제정 초안 — “업무용 드론 운영지침” 초안·점검·문서', async () => { await p.evaluate(() => raTab('enact')); await p.waitForTimeout(300);
    await (await p.$('input[oninput*="enact.title"]')).fill('업무용 드론 운영지침');
    await p.evaluate(() => raWizGo('enact', 2)); await p.waitForFunction(() => RA.enact.draft && RA.enact.draft.text, null, { timeout: 60000 });
    await p.evaluate(() => raWizGo('enact', 3)); await p.waitForFunction(() => RA.enact.lint, null, { timeout: 60000 });
    await p.evaluate(() => raWizGo('enact', 4));
    const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 60000 }), p.evaluate(() => raExport('enact', 'hwpx'))]); const sz = fs.statSync(await dl.path()).size;
    const r = await p.evaluate(() => ({ arts: raParse(RA.enact.draft.text).articles.length, err: raArr(RA.enact.lint).filter(i => i.level === 'error').length }));
    return { ok: r.arts >= 3 && sz > 2000, note: `조 ${r.arts}개, 점검 오류 ${r.err}, 한글 ${(sz / 1024).toFixed(0)}KB` }; });
  // 7) 전 내규 개정문 왕복 검증
  await p.evaluate(() => raTab('amend')); await p.waitForTimeout(400);
  const fz = await p.evaluate(async () => {
    const cat = await raGet('/api/regagent/catalog'); const ops = { ins: [0, 0], hang: [0, 0], del: [0, 0], mod: [0, 0], swap: [0, 0] }, fails = []; let regs = 0;
    const H = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
    for (const g of cat.regs) { const d = await raGet('/api/regagent/articles?slug=' + encodeURIComponent(g.slug)); if (!d.success) continue; _raArts = d; const A = RA.amend;
      const live = d.articles.filter(a => !a.deleted && /^\d+$/.test(a.no)); if (live.length < 3) continue; regs++;
      const reset = () => Object.assign(A, { src: 'reg', slug: d.slug, title: d.title, sel: {}, selx: {}, changes: [], appx: [], mv: {}, purpose: '', main: [], addenda: '', notes: [], valNote: '', lawStyle: 'fine', fullRev: false });
      const run = (k, set) => { reset(); if (set() === false) return; ops[k][1]++; const rt = raRoundTrip(); if (rt && rt.ok) ops[k][0]++; else fails.push(`${k} ${d.title}`); };
      const mid = live[Math.floor(live.length / 2)];
      run('ins', () => { const no = mid.no + '의2'; if (d.articles.some(a => a.no === no)) return false; A.changes = [{ type: 'insert', no, title: '신설 조', body: '필요한 사항은 따로 정한다.' }]; });
      run('hang', () => { const ha = live.find(a => /^①/.test(String(a.body)) && /\n②/.test(String(a.body))); if (!ha) return false; const L = String(ha.body).split('\n'), i = L.findIndex(x => /^②/.test(x));
        A.changes = [{ type: 'modify', no: ha.no, title: ha.title, body: [...L.slice(0, i), '② 새로 넣은 항이다.', ...L.slice(i).map(x => { const k = H.indexOf(x[0]); return k >= 0 && k < 19 ? H[k + 1] + x.slice(1) : x; })].join('\n') }]; });
      run('del', () => { A.changes = [{ type: 'delete', no: mid.no, title: mid.title, body: mid.body }]; });
      run('mod', () => { const a = live[0]; A.changes = [{ type: 'modify', no: a.no, title: a.title, body: String(a.body).replace(/\s*$/, '') + ' 다만, 세부 사항은 따로 정한다.' }]; });
      run('swap', () => { const i = live.indexOf(mid), nx = live[i + 1]; if (!nx || +nx.no !== +mid.no + 1) return false; A.mv = { [mid.no]: nx.no, [nx.no]: mid.no }; });
    }
    return { regs, ops, fails: fails.slice(0, 10) }; });
  const NAME = { ins: '조 신설', hang: '항 끼워 넣기(번호 밀림)', del: '조 삭제', mod: '조문 문장 추가', swap: '조 맞교환(인용 정정)' };
  console.log('■ 대표 과제(AI 키 없이, 화면 코드로 끝까지)');
  tasks.forEach(t => console.log(`  ${t.ok ? '✓' : '✗'} ${t.name.padEnd(36)} ${String(t.sec).padStart(6)}초  ${t.note || ''}`));
  console.log(`\n■ 개정문 왕복 검증(내규 ${fz.regs}건)`);
  let a = 0, n = 0; Object.entries(fz.ops).forEach(([k, [ok, tot]]) => { a += ok; n += tot; console.log(`  ${NAME[k].padEnd(20)} ${ok}/${tot} 일치`); });
  console.log(`  합계 ${a}/${n} (${(a / Math.max(n, 1) * 100).toFixed(1)}%)` + (fz.fails.length ? `  불일치 예: ${fz.fails.join(', ')}` : ''));
  console.log('[페이지 오류]', errs.length ? errs.slice(0, 3) : '없음');
  if (OUT) fs.writeFileSync(OUT, JSON.stringify({ base: BASE, at: new Date().toISOString(), tasks, roundtrip: fz, errors: errs }, null, 1));
  await b.close(); process.exit(tasks.every(t => t.ok) && !errs.length ? 0 : 1);
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
