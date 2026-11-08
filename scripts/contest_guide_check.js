// 구동안내서(docs/contest/구동안내서.md)의 절차를 사람이 하듯 화면 단추를 눌러 그대로 따라 하고, 적힌 결과가 나오는지 16개 항목으로 확인한다.
// 실행: python run_local.py 를 켠 뒤 node scripts/contest_guide_check.js  (결과: guide_out/result.json, 내려받은 한글·Word 파일)
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const OUT = require('path').resolve(process.env.GUIDE_OUT || 'guide_out'); fs.mkdirSync(OUT, { recursive: true });
const URL = process.env.GUIDE_URL || 'http://localhost:5100/';
const R = []; const rec = (id, ok, got) => { R.push({ id, ok, got }); console.log(ok ? '  ✅' : '  ❌', id, '—', got); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const prompts = []; const dialogs = []; p.on('dialog', d => { dialogs.push(d.type() + ':' + d.message().slice(0, 60)); d.type() === 'prompt' ? d.accept(prompts.shift() ?? '') : d.accept(); });
  const btn = (txt, scope = 'body') => p.locator(`${scope} button`, { hasText: txt }).first();
  const T = () => Date.now(); let t;
  await p.goto(URL, { waitUntil: 'networkidle' }); await p.evaluate(() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }); await p.reload({ waitUntil: 'networkidle' });

  console.log('[설치·실행 5] 첫 화면');
  const side = await p.evaluate(() => (document.querySelector('.ra-side') || document.body).innerText.replace(/\s+/g, ' '));
  rec('왼쪽 아래 “한국농업기술진흥원 · 등록 내규 126건”', /한국농업기술진흥원/.test(side) && /등록 내규 126건/.test(side), (side.match(/한국농업기술진흥원[^]{0,40}/) || [''])[0]);

  console.log('[LLM 연결 설정]');
  const pill = await p.evaluate(() => { const e = document.querySelector('.ra-ai-pill'); if (!e) return null; const r = e.getBoundingClientRect(); return { text: e.textContent.trim(), x: Math.round(r.x), y: Math.round(r.y) }; });
  const sideBtn = await p.evaluate(() => [...document.querySelectorAll('button')].filter(e => e.offsetParent && /AI 설정/.test(e.textContent)).map(e => { const r = e.getBoundingClientRect(); return e.textContent.trim() + '@' + Math.round(r.x) + ',' + Math.round(r.y); }));
  rec('화면 오른쪽 위 [AI 설정] 단추', !!pill && pill.x > 1000 && pill.y < 120, `오른쪽 위 단추 글자 “${pill && pill.text}” (${pill && pill.x},${pill && pill.y}) · “AI 설정” 글자 단추: ${sideBtn.join(', ')}`);
  await p.click('.ra-ai-pill'); await p.waitForSelector('#aiModalBg.show', { timeout: 5000 });
  const tabs = await p.$$eval('.prov-tab', es => es.map(e => e.textContent.trim()));
  const hasKey = !!(await p.$('#aiKey')), hasModel = await p.evaluate(() => !!document.querySelector('#aiModalBg select, #aiModel'));
  rec('제공자 Gemini·Claude·GPT·사내·공통기반, 키 입력칸, 모델 선택', tabs.join(',') === 'Gemini,Claude,GPT,사내·공통기반' && hasKey && hasModel, `탭 ${tabs.join('·')} · 키칸 ${hasKey} · 모델 선택 ${hasModel}`);
  await p.fill('#aiKey', 'TEST-KEY-123');
  const save = p.locator('#aiModalBg button', { hasText: /저장|적용|확인/ }).first(); const saveTxt = (await save.textContent()).trim(); await save.click(); await p.waitForTimeout(300);
  const st = await p.evaluate(() => ({ ss: sessionStorage.getItem('aiKeys') || '', ls: JSON.stringify(Object.assign({}, localStorage)) }));
  const p2 = await ctx.newPage(); await p2.goto(URL, { waitUntil: 'networkidle' }); const ss2 = await p2.evaluate(() => sessionStorage.getItem('aiKeys') || ''); await p2.close();
  rec('키는 브라우저 세션에만(탭을 닫으면 지워짐), 서버·영구 저장소에 없음', st.ss.includes('TEST-KEY-123') && !st.ls.includes('TEST-KEY-123') && !ss2.includes('TEST-KEY-123'), `“${saveTxt}” 후 sessionStorage ${st.ss.includes('TEST-KEY-123')} · localStorage ${st.ls.includes('TEST-KEY-123')} · 새 탭 ${ss2.includes('TEST-KEY-123')}`);
  await p.evaluate(() => { sessionStorage.removeItem('aiKeys'); localStorage.removeItem('aiSettings'); }); await p.reload({ waitUntil: 'networkidle' });

  console.log('[기능 ① 한 문장 개정]');
  await p.click('.ra-tab[data-k="agent"]'); await p.fill('#raAgIn', '여비규정 제15조의 일비를 3만원으로 올려줘');
  t = T(); await btn('에이전트 실행').click(); await p.waitForFunction(() => RA.agent && !RA.agent.running && RA.agent.done, null, { timeout: 60000 }); const ta = (T() - t) / 1000;
  const ag = await p.evaluate(() => ({ n: RA.agent.steps.length, title: RA.agent.done.title, appx: raEffAppx().map(x => ({ id: x.id, has30: /30,000/.test(x.body), has25: /25,000/.test(raOldX(x.id).body) })) }));
  rec('0.6초 안팎, 별표 2 일비 25,000 → 30,000, 14단계', ag.n === 14 && ag.appx.some(x => x.has30 && x.has25), `${ta.toFixed(2)}초 · ${ag.n}단계 · ${ag.title} · 별표 ${JSON.stringify(ag.appx)}`);
  await btn('검토 보고서 열기').click(); await p.waitForTimeout(800);
  const rep = await p.evaluate(() => document.body.innerText.includes('검토 보고서') && /25,000원?\s*→\s*30,000/.test(document.body.innerText));
  rec('검토 보고서 열기', rep, '보고서 화면·현황(25,000 → 30,000) 표시 ' + rep);
  await p.locator('#raWiz button', { hasText: '확인·검토' }).first().click(); await p.waitForTimeout(500);
  const rb = p.locator('.ra-runbar .svc-btn.yes').first(); const rbTxt = (await rb.textContent()).trim();
  t = T(); await rb.click(); await p.waitForFunction(() => !document.querySelector('.ra-runbar .svc-btn[disabled]') && RA.amend.rt, null, { timeout: 60000 }); const tc = (T() - t) / 1000;
  const sum = await p.evaluate(() => (document.getElementById('raChkSum') || {}).textContent.replace(/\s+/g, ' ').trim());
  rec('확인·검토 점검 단추(약 0.4초) → 개정문 검증 “일치”', /개정문 일치/.test(sum), `단추 “${rbTxt}” ${tc.toFixed(2)}초 · ${sum}`);
  await p.locator('#raWiz button', { hasText: '문서 받기' }).first().click(); await p.waitForTimeout(800);
  for (const [lab, ext] of [['한글(.hwpx)', 'hwpx'], ['Word(.docx)', 'docx']]) {
    const bl = p.locator('#raBody button', { hasText: lab }).first(); const exists = await bl.count();
    if (!exists) { rec(`문서 받기 ${lab}`, false, '단추 없음'); continue; }
    const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 30000 }), bl.click()]); const f = `${OUT}/amend.${ext}`; await dl.saveAs(f);
    const head = fs.readFileSync(f).subarray(0, 2).toString(); rec(`문서 받기 ${lab}`, head === 'PK' && fs.statSync(f).size > 3000, `${fs.statSync(f).size}B (zip ${head === 'PK'})`);
  }

  console.log('[기능 ② 제정]');
  await p.click('.ra-tab[data-k="enact"]'); await p.waitForTimeout(400);
  await p.fill('input[oninput*="enact.title"]', '업무용 드론 운영지침');
  await p.locator('#raWiz button', { hasText: '참고 자료' }).first().click(); await p.waitForTimeout(500);
  const manual = p.locator('#raBody button', { hasText: '직접' }).first(); const manTxt = (await manual.count()) ? (await manual.textContent()).trim() : '';
  if (manTxt) { const d0 = dialogs.length; await manual.click(); await p.waitForSelector('#raManLaw', { timeout: 5000 });
    await p.fill('#raManLaw', '드론 활용의 촉진 및 기반조성에 관한 법률'); await p.fill('#raManArt', '제13조'); await p.fill('#raManText', '드론 사용사업의 안전관리에 필요한 사항은 대통령령으로 정한다.');
    await p.locator('.ra-man button', { hasText: '추가' }).click(); await p.waitForTimeout(400);
    const dels = await p.evaluate(() => (RA.enact.dels || []).map(d => d.law + ' ' + (d.art || d.no || '')));
    rec('(선택) 위임 조항 직접 입력(화면 입력칸)', dels.some(x => /드론 활용/.test(x)) && dialogs.length === d0, `단추 “${manTxt}” · 입력칸 3개 · 대화상자 ${dialogs.length - d0}번 · 담긴 위임 조항 ${JSON.stringify(dels)}`); }
  else rec('(선택) 위임 조항 직접 추가', false, '“직접” 단추 없음');
  t = T(); await p.locator('#raWiz button', { hasText: '조문 초안' }).first().click(); await p.waitForFunction(() => RA.enact.draft && RA.enact.draft.text, null, { timeout: 30000 });
  const arts = await p.evaluate(() => raParse(RA.enact.draft.text).articles.length);
  const delInDraft = await p.evaluate(() => /드론 활용의 촉진/.test(RA.enact.draft.text));
  await p.locator('#raWiz button', { hasText: '점검·검토' }).first().click(); await p.waitForFunction(() => RA.enact.lint, null, { timeout: 30000 }).catch(() => {});
  const lintErr = await p.evaluate(() => (RA.enact.lint || []).filter(i => i.level === 'error').length);
  await p.locator('#raWiz button', { hasText: '문서 받기' }).first().click(); await p.waitForTimeout(400);
  const eb = p.locator('#raBody button', { hasText: '한글(.hwpx)' }).first();
  const [edl] = await Promise.all([p.waitForEvent('download', { timeout: 30000 }), eb.click()]); const te = (T() - t) / 1000; await edl.saveAs(`${OUT}/enact.hwpx`);
  rec('조문 초안 → 점검·심의 → 문서(초안·점검·한글 약 0.8초)', arts >= 4 && lintErr === 0 && fs.statSync(`${OUT}/enact.hwpx`).size > 3000, `조 ${arts}개 · 점검 오류 ${lintErr} · 위임 근거 초안 반영 ${delInDraft} · 한글 ${fs.statSync(OUT + '/enact.hwpx').size}B · 단추 이동 포함 ${te.toFixed(2)}초`);

  console.log('[기능 ③ 정비·점검]');
  t = T(); await p.click('.ra-tab[data-k="health"]'); await p.waitForFunction(() => document.querySelector('#raHealth .ra-sec'), null, { timeout: 60000 }); const th = (T() - t) / 1000;
  t = T(); await p.locator('#raHealth .ra-hseg button', { hasText: '오류 목록' }).click(); await p.waitForFunction(() => RA.check && RA.check.res && document.querySelector('#raChkAll .ra-det'), null, { timeout: 60000 }); const tl = (T() - t) / 1000;
  const errTxt = await p.evaluate(() => document.querySelector('#raChkAll').innerText.replace(/\s+/g, ' '));
  rec('건강검진(약 1초) → 오류 목록 누르면 바로 점검, 없는 조문 인용·항 번호 오류', th < 3 && /오류/.test(errTxt) && /(없는|삭제된) 조/.test(errTxt), `진단 ${th.toFixed(2)}초 · 오류 목록 ${tl.toFixed(2)}초 · 결과 “${errTxt.slice(0, 90)}…”`);
  await p.click('.ra-tab[data-k="agent"]'); await p.fill('#raAgIn', '모든 내규에서 기획운영본부를 경영기획본부로 바꿔줘'); await btn('에이전트 실행').click();
  await p.waitForFunction(() => RA.agent && !RA.agent.running && RA.agent.done, null, { timeout: 60000 });
  const bk = await p.evaluate(() => ({ sub: RA.agent.done.title + ' / ' + RA.agent.done.sub, steps: RA.agent.steps.map(s => s.t).join(' · ') }));
  rec('일괄 정비 25개 내규 35곳(별표·서식 포함), 개정문·부칙·통합 대비표', /25개 내규, 35곳/.test(bk.sub), bk.sub + ' | ' + bk.steps);
  const d1 = dialogs.length; await p.fill('#raAgIn', '여비규정 제20조를 삭제해줘'); await btn('에이전트 실행').click();
  await p.waitForFunction(() => RA.agent && !RA.agent.running && RA.agent.done, null, { timeout: 60000 });
  const dl2 = await p.evaluate(() => RA.agent.steps.filter(s => /삭제/.test(s.t)).map(s => String(s.d || '').replace(/<[^>]+>/g, '')).join(' '));
  rec('조 삭제: 인용하는 제24조도 수정 대상', /제24조/.test(dl2), dl2.slice(0, 80) + ` · 대화상자 ${dialogs.length - d1}번`);

  console.log('[실행 환경] 휴대폰 화면');
  const m = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true }); const mp = await m.newPage();
  await mp.goto(URL, { waitUntil: 'networkidle' }); const ov1 = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  await mp.evaluate(() => raTab('health')); await mp.waitForFunction(() => document.querySelector('#raHealth .ra-sec'), null, { timeout: 60000 }); const ov2 = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  await mp.screenshot({ path: OUT + '/phone-health.png' }); await m.close();
  rec('휴대폰 폭(390px)에서 가로 넘침 없음', ov1 <= 0 && ov2 <= 0, `첫 화면 ${ov1}px · 건강검진 ${ov2}px`);
  rec('페이지 오류 없음', errs.length === 0, errs.length ? errs.join(' | ') : '없음');
  console.log('대화상자', dialogs);
  fs.writeFileSync(OUT + '/result.json', JSON.stringify(R, null, 1));
  console.log(`합계 ${R.filter(x => x.ok).length}/${R.length} 통과`); await b.close();
})().catch(e => { console.error('FAILED', e); fs.writeFileSync(OUT + '/result.json', JSON.stringify(R, null, 1)); process.exit(1); });
