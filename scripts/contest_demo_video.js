// 시연영상 녹화 v2 — docs/contest/시연대본.md 장면 6개를 실제로 눌러 1920x1080으로 녹화한다.
// - 자막: 화면 위에 직접 그린다(반투명·둥근 상자, 앱 색: 남색 바탕 + 숫자만 밝은 파랑 강조, 어두운 화면에서는 흰 반투명).
// - 음성: 로컬 TTS 서버(scripts/contest_demo_tts.py, Supertonic 3 오프라인)가 자막 한 줄마다 음성을 만들고, 음성 길이에 맞춰 장면을 진행한다.
// - 설계 규칙은 digitalsamba/claude-code-video-toolkit(MIT)의 video-design·playwright-recording 스킬, alirezarezvani/claude-skills(MIT) demo-video 스킬을 따랐다.
// 준비: 서버(python run_local.py), 음성 서버(python scripts/contest_demo_tts.py), Playwright(npm i playwright)
// 실행: node scripts/contest_demo_video.js → demo_out/raw.webm, timing.json(자막·음성 시각), subs.srt, shots/*.png
//       그다음 python scripts/contest_demo_build.py demo_out demo_out/demo.mp4 -0.35 로 음성을 깔아 mp4를 만든다(docs/contest/시연영상.md)
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = require('path').resolve(process.env.DEMO_OUT || 'demo_out'); fs.mkdirSync(OUT + '/shots', { recursive: true });
for (const f of fs.readdirSync(OUT)) if (f.endsWith('.webm')) fs.unlinkSync(OUT + '/' + f);
const URL = process.env.DEMO_URL || 'http://localhost:5100/';
const TTS = process.env.DEMO_TTS || 'http://127.0.0.1:5200/tts';

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1920, height: 1080 }, acceptDownloads: true, recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } } });
  await ctx.addInitScript(() => {
    const css = `
      #__cur{position:fixed;left:0;top:0;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;background:rgba(37,99,235,.30);border:2px solid #2563eb;z-index:2147483647;pointer-events:none;transition:transform .12s}
      #__cur.dn{transform:scale(.7);background:rgba(37,99,235,.55)}
      .__rip{position:fixed;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:3px solid #2563eb;z-index:2147483646;pointer-events:none;animation:__r .6s cubic-bezier(.16,1,.3,1) forwards}
      @keyframes __r{to{transform:scale(4);opacity:0}}
      body.__carded #__cur{display:none}
      /* 자막: 앱의 남색 잉크(#0f172a)를 반투명 바탕으로, 숫자만 브랜드 파랑의 밝은 톤으로 */
      #__cap{position:fixed;left:50%;bottom:40px;transform:translate(-50%,14px);width:max-content;max-width:1560px;z-index:2147483645;pointer-events:none;
        padding:14px 28px 16px;border-radius:16px;background:rgba(15,23,42,.82);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);
        border:1px solid rgba(255,255,255,.10);box-shadow:0 10px 30px rgba(15,23,42,.18);
        font-family:Pretendard,'Malgun Gothic',sans-serif;font-size:34px;line-height:1.45;font-weight:600;letter-spacing:-.01em;color:#fff;text-align:center;
        opacity:0;transition:opacity .35s cubic-bezier(.16,1,.3,1),transform .35s cubic-bezier(.16,1,.3,1);word-break:keep-all}
      #__cap.on{opacity:1;transform:translate(-50%,0)}#__cap span{display:block;white-space:nowrap}
      #__cap em{font-style:normal;color:#93c5fd;font-variant-numeric:tabular-nums}
      body.__carded #__cap{background:rgba(255,255,255,.10);border-color:rgba(255,255,255,.18);box-shadow:none}
      /* 장면 표시: 위 가운데 알약, 브랜드 파랑 반투명 */
      #__scn{position:fixed;left:50%;top:20px;transform:translateX(-50%);z-index:2147483645;pointer-events:none;display:flex;align-items:center;gap:12px;
        padding:9px 22px 9px 10px;border-radius:999px;background:rgba(37,99,235,.86);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
        font-family:Pretendard,'Malgun Gothic',sans-serif;font-size:26px;font-weight:700;color:#fff;letter-spacing:-.01em;opacity:0;transition:opacity .4s}
      #__scn.on{opacity:1}#__scn i{font-style:normal;display:inline-grid;place-items:center;width:38px;height:38px;border-radius:50%;background:rgba(255,255,255,.22);font-size:22px}
      body.__carded #__scn{background:rgba(255,255,255,.12)}
      #__card{position:fixed;inset:0;z-index:2147483640;background:#0f172a;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:Pretendard,'Malgun Gothic',sans-serif;opacity:0;transition:opacity .5s;pointer-events:none}
      #__card.on{opacity:1}#__card h1{font-size:68px;margin:0 0 20px;font-weight:800;letter-spacing:-.03em;color:#fff !important}#__card p{font-size:32px;margin:6px 0;color:#cbd5e1 !important}
      #__card .g{display:grid;grid-template-columns:repeat(2,560px);gap:22px;margin:34px 0 0}#__card .g div{background:#1e293b;border-radius:16px;padding:26px 30px}
      #__card .g b{display:block;font-size:56px;color:#93c5fd;margin-bottom:6px;font-variant-numeric:tabular-nums;letter-spacing:-.02em}#__card .g span{font-size:28px;color:#e2e8f0}
      #__card .t{width:1480px;margin:30px 0 0}#__card .t div{display:flex;gap:28px;align-items:baseline;background:#1e293b;border-radius:14px;padding:20px 30px;margin-top:14px;text-align:left}
      #__card .t b{flex:none;width:96px;font-size:30px;color:#93c5fd}#__card .t span{font-size:30px;color:#e2e8f0;line-height:1.45;word-break:keep-all}
      .__hl{outline:4px solid #f59e0b !important;outline-offset:3px;border-radius:6px}`;
    const add = () => { if (document.getElementById('__cur')) return; const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s);
      for (const id of ['__cur', '__cap', '__scn']) { const d = document.createElement('div'); d.id = id; document.body.appendChild(d); }
      const c = document.getElementById('__cur');
      addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
      addEventListener('mousedown', e => { c.classList.add('dn'); const r = document.createElement('div'); r.className = '__rip'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px'; document.body.appendChild(r); setTimeout(() => r.remove(), 700); }, true);
      addEventListener('mouseup', () => c.classList.remove('dn'), true); };
    if (document.body) add(); else addEventListener('DOMContentLoaded', add);
  });
  const p = await ctx.newPage(); const T0 = Date.now(); const now = () => (Date.now() - T0) / 1000;
  const errs = [], dialogs = []; p.on('pageerror', e => errs.push(e.message)); p.on('dialog', d => { dialogs.push(d.message().slice(0, 90)); d.accept(); });
  const subs = [], scenes = [], timing = {}; let shotN = 0, busyUntil = 0;
  const wait = ms => p.waitForTimeout(ms);
  // 자막 두 줄 이내, 구절에서 끊는다(직접 \n을 넣으면 그대로)
  const lines = s => { if (s.includes('\n') || s.length <= 34) return s.split('\n'); const mid = s.length / 2; let best = -1, bw = 0;
    for (let i = 1; i < s.length - 1; i++) if (s[i] === ' ') { const w = /[.,:]/.test(s[i - 1]) ? 3 : /[다요고며서면]$/.test(s.slice(0, i)) ? 2 : 1; const sc = w * 40 - Math.abs(i - mid); if (best < 0 || sc > bw) { best = i; bw = sc; } }
    return best > 0 ? [s.slice(0, best), s.slice(best + 1)] : [s]; };
  const capHtml = s => lines(s).map(l => l.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/(\d[\d,.~]*\s?(?:초|건|곳|번|단계|원|줄|시간|종|개 내규))/g, '<em>$1</em>')).map(l => `<span>${l}</span>`).join('');
  // 자막 한 줄 + 음성: 앞 음성이 끝날 때까지 기다렸다가, 음성을 받아 자막을 띄운다. wait:false면 화면 조작과 겹쳐 말한다
  const say = async (text, opt = {}) => {
    const lead = busyUntil - Date.now(); if (lead > 0) await wait(lead);
    const r = await (await fetch(TTS, { method: 'POST', body: JSON.stringify({ text: opt.v || text }) })).json();
    const s = now(); await p.evaluate(h => { const c = document.getElementById('__cap'); c.innerHTML = h; c.classList.add('on'); }, capHtml(text));
    const hold = Math.max(opt.ms || 0, r.dur * 1000 + 450); busyUntil = Date.now() + hold;
    subs.push({ s, e: s + hold / 1000, text, audio: r.file, dur: r.dur });
    if (opt.wait !== false) await wait(hold);
  };
  const quiet = async () => { const lead = busyUntil - Date.now(); if (lead > 0) await wait(lead); await p.evaluate(() => document.getElementById('__cap').classList.remove('on')); await wait(350); };
  const scene = async (t, n) => { scenes.push({ s: now(), t }); await p.evaluate(([t, n]) => { const e = document.getElementById('__scn'); e.innerHTML = n ? `<i>${n}</i>${t}` : ''; e.classList.toggle('on', !!n); }, [t, n || '']); };
  const shot = async name => { shotN++; await p.screenshot({ path: `${OUT}/shots/${String(shotN).padStart(2, '0')}-${name}.png` }); };
  let PRESS = 0; const since = () => (Date.now() - PRESS) / 1000;   // 누른 순간부터 잰 소요 시간(포인터 이동 제외)
  const click = async (loc, opt = {}) => { const l = typeof loc === 'string' ? p.locator(loc).first() : loc; await l.scrollIntoViewIfNeeded(); const bb = await l.boundingBox();
    await p.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2, { steps: 18 }); await wait(opt.pause ?? 350); PRESS = Date.now(); await p.mouse.down(); await wait(80); await p.mouse.up(); await wait(150); };
  const type = async (sel, text) => { await click(sel); await p.fill(sel, ''); await p.type(sel, text, { delay: 55 }); };
  const scrollTo = async (sel, block = 'start') => { await p.evaluate(([s, bl]) => { const e = document.querySelector(s); if (e) e.scrollIntoView({ behavior: 'smooth', block: bl }); }, [sel, block]); await wait(900); };
  const scrollBy = async y => { await p.evaluate(y => window.scrollBy({ top: y, behavior: 'smooth' }), y); await wait(900); };
  const hl = async (sel, on = true) => p.evaluate(([s, on]) => document.querySelectorAll(s).forEach(e => e.classList.toggle('__hl', on)), [sel, on]);
  const card = async html => { await p.evaluate(h => { let c = document.getElementById('__card'); if (!c) { c = document.createElement('div'); c.id = '__card'; document.body.appendChild(c); } c.innerHTML = h; document.body.classList.add('__carded'); requestAnimationFrame(() => c.classList.add('on')); }, html); await wait(600); };
  const uncard = async () => { await p.evaluate(() => { const c = document.getElementById('__card'); if (c) c.classList.remove('on'); document.body.classList.remove('__carded'); }); await wait(600); };
  const agentRun = async req => { await type('#raAgIn', req); await click('.ra-ag-go');
    await p.waitForFunction(() => RA.agent && !RA.agent.running && RA.agent.done, null, { timeout: 120000 }); return since(); };
  const SINO = ['영', '일', '이', '삼', '사', '오', '육', '칠', '팔', '구'];
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const natN = n => n >= 10 && n < 20 ? ['열', '열한', '열두', '열세', '열네', '열다섯', '열여섯', '열일곱', '열여덟', '열아홉'][n - 10] : String(n);
  const f1 = x => x.toFixed(1), sp = x => { const t = x.toFixed(1); return x < 1 ? `영 점 ${SINO[+t.slice(-1)]}` : t; }, kr = n => ['영', '한', '두', '세', '네', '다섯', '여섯', '일곱', '여덟', '아홉', '열'][n] || String(n);

  await p.goto(URL, { waitUntil: 'networkidle' }); await p.evaluate(() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }); await p.reload({ waitUntil: 'networkidle' });
  await p.mouse.move(1500, 700);
  // 음성 맞춤용 동기 표시: 왼쪽 위에 0.4초 동안 자홍색 네모를 띄우고 그 시각을 남긴다(contest_demo_build.py가 영상에서 찾아 시각 차이를 잰다)
  await p.evaluate(() => { const d = document.createElement('div'); d.id = '__sync'; d.style.cssText = 'position:fixed;left:0;top:0;width:48px;height:48px;background:#ff00ff;z-index:2147483647'; document.body.appendChild(d); });
  const syncT = now(); await wait(400); await p.evaluate(() => document.getElementById('__sync').remove());
  // ── 제목
  await scene('제목');
  await card(`<h1>규정 제·개정 에이전트</h1><p>2026 공공 AI 대전환 챌린지 · 세션 2 지정과제 ③</p><p style="margin-top:28px;color:#93c5fd !important">AI 키 없이 · 외부망(법제처·알리오) 없이 · 실제 내규 126건</p>`);
  await say('규정 제·개정 에이전트 시연입니다. AI 키와 외부망 없이,\n실제 내규 126건으로 보여 드립니다.', { ms: 5500, v: '규정 제·개정 에이전트 시연입니다. AI 키와 외부망 없이, 실제 내규 백이십육 건으로 보여 드립니다.' });
  await quiet(); await uncard();

  // ── ① 문제 제기
  await scene('문제 제기 — 건강검진', '1');
  await say('규정 하나를 고치려 해도, 고칠 곳을 찾고\n인용하는 다른 조와 다른 규정까지 확인해야 합니다.');
  await say('개정문, 신구조문대비표, 이유서도 직접 씁니다.\n그러다 보니 사람이 하면 틀립니다.', { wait: false });
  await click('.ra-tab[data-k="health"]'); await p.waitForFunction(() => document.querySelector('#raHealth .ra-sec'), null, { timeout: 60000 }); timing.health = since();
  const kpi = await p.evaluate(() => document.querySelector('#raHealth').innerText.replace(/\s+/g, ' ').slice(0, 260));
  const m20 = +(kpi.match(/인용·명칭·번호 문제 (\d+)/) || [])[1], m4 = +(kpi.match(/오류가 있는 내규 (\d+)건/) || [])[1]; timing.healthNums = [m20, m4];
  await shot('health');
  await say(`내규 126건 전체를 ${f1(timing.health)}초 만에 진단했습니다.\n인용·명칭·번호 문제 ${m20}곳, 오류가 있는 내규 ${m4}건입니다.`,
    { v: `내규 126건 전체를 ${f1(timing.health)}초 만에 진단했습니다. 인용·명칭·번호 문제 ${m20}곳, 오류가 있는 내규 ${kr(m4)} 건입니다.` });
  await click(p.locator('#raHealth .ra-hseg button', { hasText: '오류 목록' }));
  await p.waitForFunction(() => RA.check && RA.check.res && document.querySelector('#raChkAll .ra-det'), null, { timeout: 60000 }); timing.errorsTab = since();
  await wait(400); await scrollTo('#raChkAll .ra-detg'); await shot('health-errors'); await hl('#raChkAll details.ra-det[open] summary');
  await say('제16조까지밖에 없는 규칙이 제17조를 인용하고,\n②항이 두 번 나오는 조문도 있습니다.', { v: '제16조까지만 있는 규칙이 제17조를 인용하고, 2항이 두 번 나오는 조문도 있습니다.' });
  await say('이미 확정된 내규에 남아 있는 사람의 실수입니다.');
  await hl('#raChkAll details.ra-det[open] summary', false);

  // ── ② 한 문장 요청
  await scene('한 문장 요청 → 자료조사·보고서', '2');
  await click('.ra-tab[data-k="agent"]'); await p.waitForSelector('#raAgIn');
  await say('담당자가 하는 말 그대로, 한 문장만 넣습니다.', { wait: false });
  timing.agentAmend = await agentRun('여비규정 제15조의 일비를 3만원으로 올려줘');
  const nSteps = await p.evaluate(() => RA.agent.steps.length);
  await wait(300); await shot('agent-done');
  await say(`${f1(timing.agentAmend)}초 만에 에이전트가 ${nSteps}단계를 끝까지 처리했습니다.`, { v: `${sp(timing.agentAmend)}초 만에 에이전트가 ${nSteps}단계를 끝까지 처리했습니다.` });
  await scrollTo('#raAgOut'); await scrollBy(250);
  await say('제15조를 불러오고, 별표 2 표에서 일비 칸만\n25,000원에서 30,000원으로 바꿨습니다.', { v: '제15조를 불러오고, 별표 2 표에서 일비 칸만 2만 5천 원에서 3만 원으로 바꿨습니다.' });
  await scrollBy(350);
  await say('이 조를 인용하는 곳을 확인하고,\n형식 점검·심의 사전검토·절차·문서 세트까지 준비했습니다.');
  await scrollTo('#raAgOut'); await click(p.locator('button', { hasText: '검토 보고서 열기' }).first()); await wait(1000); await shot('report');
  await say('상급자에게 올릴 검토 보고서 초안도 함께 나옵니다.');
  await scrollBy(300);
  await say('현황에는 “일비 25,000원 → 30,000원 조정 필요”,\n자료조사에는 「여비업무 처리지침」이 들어갑니다.', { v: '현황에는 일비 2만 5천 원에서 3만 원 조정 필요, 자료조사에는 여비업무 처리지침이 들어갑니다.' });

  // ── ③ 확인·검토 → 문서 받기
  await scene('대비표·점검·개정문 검증 → 문서 받기', '3');
  await p.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' })); await wait(700);
  await click(p.locator('#raWiz button', { hasText: '확인' }).first()); await wait(700);
  await click(p.locator('.ra-runbar .svc-btn.yes').first());
  await p.waitForFunction(() => !document.querySelector('.ra-runbar .svc-btn[disabled]') && RA.amend.rt, null, { timeout: 90000 }).catch(() => {}); timing.checkAll = since();
  timing.checkSum = await p.evaluate(() => ((document.getElementById('raChkSum') || {}).textContent || '').replace(/\s+/g, ' ').trim().slice(0, 300));
  await wait(300); await shot('amend-check'); await hl('#raChkSum');
  await say(`점검 단추 한 번으로 대비표·인용 영향·형식 점검·\n개정문 검증을 ${f1(timing.checkAll)}초에 끝냅니다.`, { v: `점검 단추 한 번으로 대비표, 인용 영향, 형식 점검, 개정문 검증을 ${sp(timing.checkAll)}초에 끝냅니다.` });
  await hl('#raChkSum', false);
  await say('가장 중요한 것은 개정문 검증입니다. 개정문을 현행에\n다시 적용해, 개정안과 글자 하나까지 같은지 봅니다.');
  await scrollBy(420);
  await say('내규 125건에 조 신설·삭제·항 끼워 넣기 같은 수정을\n619번 해 봤고, 619번 모두 일치했습니다.', { v: '내규 125건에 조 신설, 삭제, 항 끼워 넣기 같은 수정을 육백십구 번 해 봤고, 육백십구 번 모두 일치했습니다.' });
  await p.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' })); await wait(700);
  await click(p.locator('#raWiz button', { hasText: '문서' }).first()); await wait(900); await shot('amend-docs');
  await say('검토 보고서·심의안건서·개정문·이유서·사전예고문 등\n심의에 올릴 문서 11종이 준비돼 있습니다.', { v: '검토 보고서, 심의안건서, 개정문, 이유서, 사전예고문 등 심의에 올릴 문서 열한 종이 준비돼 있습니다.' });
  const dlb = p.locator('button', { hasText: '한글' }).first();
  if (await dlb.count()) { await Promise.all([p.waitForEvent('download', { timeout: 60000 }), click(dlb)]); timing.hwpx = since(); }
  await say('한글 파일 하나로 받습니다.\n개정문·대비표·이유서·의견서까지 들어 있습니다.');

  // ── ④ 일괄 정비
  await scene('모든 내규 일괄 정비', '4');
  await click('.ra-tab[data-k="agent"]'); await p.waitForSelector('#raAgIn');
  await say('부서 이름이 바뀌면 사람은 내규 126건을 하나씩 열어\n찾아야 합니다. 저희 산정으로 약 9.6시간 일입니다.', { wait: false, v: '부서 이름이 바뀌면, 사람은 내규 백이십육 건을 하나씩 열어 찾아야 합니다. 저희 산정으로 약 구 점 육 시간 일입니다.' });
  timing.bulk = await agentRun('모든 내규에서 기획운영본부를 경영기획본부로 바꿔줘');
  const bsub = await p.evaluate(() => RA.agent.done.title + ' / ' + (RA.agent.done.sub || '')); timing.bulkSub = bsub;
  await shot('bulk-done');
  const nb = (bsub.match(/(\d+)개 내규/) || [])[1], np = (bsub.match(/(\d+)곳/) || [])[1];
  await say(`에이전트는 ${f1(timing.bulk)}초 만에 ${nb}개 내규에서 ${np}곳을 찾았습니다.`, { v: `에이전트는 ${sp(timing.bulk)}초 만에 ${nb}개 내규에서 ${np} 곳을 찾았습니다.` });
  const bo = p.locator('#raBody button', { hasText: '일괄 정비' }).filter({ hasText: '열기' }).first();
  if (await bo.count()) { await click(bo); await wait(1000); await shot('bulk-view'); }
  await say('내규별 개정문, “다른 내규의 개정” 부칙,\n통합 신구조문대비표까지 만들었습니다.');
  await scrollBy(400);
  await say('이름이 바뀌면 뒤에 붙는 조사도 맞춥니다.\n“윤리감사실을 둔다” → “감사부를 둔다”', { v: '이름이 바뀌면 뒤에 붙는 조사도 맞춥니다. 윤리감사실을 둔다를 바꾸면, 감사부를 둔다가 됩니다.' });

  // ── ⑤ 조 삭제
  await scene('조 삭제 — 사람이 놓치는 인용', '5');
  await click('.ra-tab[data-k="agent"]'); await p.waitForSelector('#raAgIn');
  await say('조를 지울 때 가장 많이 놓치는 것이,\n그 조를 인용하던 다른 조입니다.', { wait: false });
  const dBefore = dialogs.length;
  timing.del = await agentRun('여비규정 제20조를 삭제해줘'); timing.delDialog = dialogs.slice(dBefore);
  timing.delSteps = await p.evaluate(() => RA.agent.steps.filter(s => /삭제|점검/.test(s.t)).map(s => s.t + ': ' + String(s.d || '').replace(/<[^>]+>/g, '').slice(0, 120)));
  await scrollTo('#raAgOut'); await scrollBy(200); await shot('delete-done');
  await say('에이전트는 제20조를 지우면서, 이 조를 인용하는\n제24조를 찾아 함께 고치도록 담았습니다.', { v: '에이전트는 제20조를 지우면서, 이 조문을 인용하는 제이십사조를 찾아 함께 고치도록 담았습니다.' });
  await say('고치지 않으면 점검에서 오류로 막습니다.\n사람이 놓치는 곳을 먼저 짚습니다.');
  await quiet();

  // ── ⑥ 숫자와 확산
  await scene('숫자와 확산', '6');
  await card(`<h1 style="font-size:56px">모두 실제 내규로, AI 없이 잰 숫자</h1><div class="g">
    <div><b>1,243 / 1,243</b><span>흔한 오류 10종을 심어 모두 적발</span></div>
    <div><b>619 / 619</b><span>개정문 검증 일치</span></div>
    <div><b>0.4~1.4초</b><span>한 문장 요청 → 개정안·검토 보고서</span></div>
    <div><b>코드 수정 0줄</b><span>가상 기관 도입(기관 설정 파일만)</span></div></div>
    <p style="margin-top:32px">AI 모델은 바꿔 끼울 수 있고, AI 없이도 핵심 기능이 동작합니다</p>`);
  await shot('summary');
  await say('흔한 오류 10종을 1,243번 심었는데 모두 잡았고,\n개정문 검증은 619번 모두 일치했습니다.', { v: '흔한 오류 열 종을 천이백사십삼 번 심었는데 모두 잡았고, 개정문 검증은 육백십구 번 모두 일치했습니다.' });
  await say('다른 기관도 바로 쓸 수 있습니다. 가상 기관 내규를\n들여오는 데 코드는 한 줄도 고치지 않았습니다.');
  await say('상위법이 바뀌면 이를 인용한 내규를 찾아 알려 줍니다.');
  await quiet();
  // MCP: 같은 엔진을 AI 도우미의 도구로 — 화면에서 실제로 /mcp 를 불러 받은 결과를 보여 준다
  const mcp = await p.evaluate(async () => {
    const call = async (method, params) => (await (await fetch('/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) })).json()).result;
    const tools = (await call('tools/list', {})).tools.length;
    const t0 = performance.now();
    const d = (await call('tools/call', { name: 'run_agent', arguments: { request: '여비규정 제15조의 일비를 3만원으로 올려줘' } })).structuredContent || {};
    return { tools, sec: (performance.now() - t0) / 1000, law: String(d.amendment_text || '').split('\n').map(x => x.trim()).filter(Boolean).slice(1, 3).join(' '),
      ok: !!(d.verification && d.verification.ok), links: Object.keys(d.download || {}).filter(k => k !== 'note') };
  });
  timing.mcp = mcp.sec; timing.mcpTools = mcp.tools; timing.mcpOk = mcp.ok; timing.mcpLinks = mcp.links;
  await card(`<h1 style="font-size:56px">AI 도우미의 도구로 — MCP</h1><div class="t">
    <div><b>연결</b><span>배포 주소/mcp → claude.ai·ChatGPT 커넥터, Claude Code</span></div>
    <div><b>도구</b><span>${mcp.tools}개: 에이전트 실행 · 개정문·대비표·검증 · 건강검진 · 다른 기관 사규(알리오)</span></div>
    <div><b>요청</b><span>run_agent “여비규정 제15조의 일비를 3만원으로 올려줘”</span></div>
    <div><b>응답</b><span>${esc(mcp.law)} · 개정문 검증 ${mcp.ok ? '일치' : '불일치'} · ${mcp.links.length ? '한글·Word 링크' : '문서 링크 없음'}</span></div></div>`);
  await shot('mcp');
  await say(`AI 도우미에서도 씁니다. 배포 주소의 /mcp를 커넥터로 넣으면\nclaude.ai나 ChatGPT가 도구 ${mcp.tools}개로 부릅니다.`,
    { v: `AI 도우미에서도 씁니다. 배포 주소의 엠씨피를 커넥터로 넣으면, 클로드나 챗지피티가 도구 ${natN(mcp.tools)} 개로 부릅니다.` });
  await say(`같은 요청을 MCP로 보내면 같은 엔진이 ${f1(mcp.sec)}초 만에\n개정문·검증 결과·한글 문서 링크를 돌려줍니다.`,
    { v: `같은 요청을 엠씨피로 보내면, 같은 엔진이 ${sp(mcp.sec)}초 만에 개정문과 검증 결과, 한글 문서 링크를 돌려줍니다.` });
  await say('다른 기관 사규를 알리오에서 찾아 견주는 도구도 있고,\n어떤 AI가 부르든 결과는 같은 규칙 엔진이 만듭니다.',
    { v: '다른 기관 사규를 알리오에서 찾아 견주는 도구도 있고, 어떤 AI가 부르든 결과는 같은 규칙 엔진이 만듭니다.' });
  await say('담당자가 틀리기 쉬운 일을 먼저 막는 에이전트를\n범정부 공공재로 내놓겠습니다. 감사합니다.');
  await quiet(); await wait(600);
  const total = now();
  await p.close(); const vpath = await p.video().path(); await ctx.close(); await b.close();
  fs.renameSync(vpath, OUT + '/raw.webm');
  const ts = x => { const ms = Math.round(x * 1000); const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60; return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms % 1000).padStart(3, '0')}`; };
  fs.writeFileSync(OUT + '/subs.srt', subs.map((x, i) => `${i + 1}\n${ts(x.s)} --> ${ts(x.e)}\n${x.text}\n`).join('\n'));
  fs.writeFileSync(OUT + '/timing.json', JSON.stringify({ total, syncT, scenes, timing, dialogs, errs, subs }, null, 1));
  console.log('총 길이', total.toFixed(1) + 's', '| 자막', subs.length, '| 장면', scenes.map(s => s.t.slice(0, 6) + '@' + s.s.toFixed(0)).join(', '));
  console.log('단계 시간', JSON.stringify({ health: timing.health, errorsTab: timing.errorsTab, agent: timing.agentAmend, check: timing.checkAll, hwpx: timing.hwpx, bulk: timing.bulk, del: timing.del, delDialog: timing.delDialog, mcp: timing.mcp, mcpTools: timing.mcpTools, mcpOk: timing.mcpOk }));
  console.log('대화상자', dialogs.length ? dialogs : '없음', '| 페이지 오류', errs.length ? errs : '없음');
})().catch(e => { console.error('FAILED', e); process.exit(1); });
