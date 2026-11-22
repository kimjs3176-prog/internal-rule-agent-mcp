"""상위법 개정 감시 — 사내 서버에서 정해진 때(하루 한 번 등) 돌려, 우리 내규가 인용하는 법령·행정규칙이
지난번 확인 이후 새로 공포됐거나 시행됐는지 찾아 알린다.

사용법
    python scripts/watch_laws.py [--state 기준파일] [--webhook URL] [--dry-run]

    · 기준파일(기본: 환경변수 WATCH_STATE, 없으면 저장소의 law_watch_state.json)에 지난 확인 결과를 남긴다.
      처음 돌리면 기준만 만들고 알림은 없다.
    · 바뀐 것이 있으면 화면에 출력하고, --webhook(또는 WATCH_WEBHOOK)이 있으면 {"text": 보고} 를 POST 한다
      (사내 메신저·협업 도구의 수신 웹훅).
    · 리눅스 cron 예: 매일 08:10  →  10 8 * * *  cd /srv/regagent && .venv/bin/python scripts/watch_laws.py
      윈도 작업 스케줄러도 같은 명령을 등록하면 된다.
결과: 0 정상(바뀐 것 없음 포함) · 3 법제처 조회가 모두 실패(망 차단 등) · 4 알림(webhook) 전송 실패(기준은 그대로 둔다).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_KST = timezone(timedelta(hours=9))


def _dot(ymd: str) -> str:
    return f"{ymd[:4]}. {int(ymd[4:6])}. {int(ymd[6:8])}." if len(ymd or "") == 8 else ""


def collect(look_law, look_rule, names, workers: int = 6) -> tuple:
    import reg_agent as ra
    cur, fail = {}, 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for nm, v in zip(names, ex.map(lambda n: ra.law_fresh_one(n, look_law, look_rule), names)):
            if v.get("error"):
                fail += 1
            else:
                cur[nm] = v
    return cur, fail


def report(org: dict, res: dict, checked: int, fail: int) -> str:
    word = org.get("reg_word") or "내규"
    head = f"[{org.get('org_name', '')}] 상위법 개정 감시 {datetime.now(_KST).strftime('%Y-%m-%d %H:%M')} — 확인 {checked}건"
    if fail:
        head += f", 조회 실패 {fail}건"
    if res["first"]:
        return head + "\n처음 확인이라 기준만 저장했습니다. 다음 확인부터 새로 공포·시행된 개정을 알립니다."
    if not res["changes"]:
        return head + "\n지난 확인 이후 바뀐 상위법·행정규칙이 없습니다."
    lines = [head, f"바뀐 상위법·행정규칙 {len(res['changes'])}건 — 인용하는 {word}를 정비하세요."]
    for c in res["changes"]:
        what = (f"새 개정 공포({_dot(c['anc'])} 공포, {_dot(c['ef'])} 시행 예정{', ' + c['type'] if c.get('type') else ''})"
                if c["kind"] == "promulgated" else f"개정 시행({_dot(c['prev_ef'])} → {_dot(c['ef'])})")
        regs = ", ".join("「" + r["title"] + "」" for r in c.get("regs", [])[:6]) + (" 외" if len(c.get("regs", [])) > 6 else "")
        lines.append(f"- 「{c['law']}」 {what}" + (f" · 인용: {regs}" if regs else ""))
    lines.append("화면의 건강검진 → 상위법 변경 알림에서 “영향 조문 찾기”로 고칠 조문을 바로 엽니다.")
    return "\n".join(lines)


def main(argv=None, look_law=None, look_rule=None) -> int:
    ap = argparse.ArgumentParser(description="상위법 개정 감시")
    ap.add_argument("--state", default=os.environ.get("WATCH_STATE") or os.path.join(ROOT, "law_watch_state.json"))
    ap.add_argument("--webhook", default=os.environ.get("WATCH_WEBHOOK", ""))
    ap.add_argument("--dry-run", action="store_true", help="기준파일을 바꾸지 않고 결과만 본다")
    a = ap.parse_args(argv)
    import reg_agent as ra
    if look_law is None:
        import api_server as A
        look_law, look_rule = (lambda n: A._lookup_law(n, "law")), A._lookup_rule
    idx = ra.law_cite_index()
    names = sorted(idx)
    cur, fail = collect(look_law, look_rule, names)
    prev = None
    if os.path.exists(a.state):
        try:
            with open(a.state, encoding="utf-8") as f:
                prev = (json.load(f) or {}).get("laws")
        except Exception as e:
            print(f"  ⚠ 기준파일을 읽지 못해 새로 만듭니다: {e}")
    if names and not cur:
        print(f"법제처 조회가 모두 실패했습니다({fail}건). 망에서 law.go.kr 이 허용됐는지 확인하세요. 기준은 그대로 둡니다.")
        return 3
    res = ra.law_watch_diff(prev, cur, idx)
    text = report(ra.ORG, res, len(cur), fail)
    print(text)
    # 알림을 먼저 보내고, 성공(2xx)했을 때만 기준을 바꾼다 — 실패하면 다음 실행에서 같은 변경을 다시 알린다
    if res["changes"] and a.webhook:
        try:
            import requests
            r = requests.post(a.webhook, json={"text": text}, timeout=10)
            print(f"  → 알림 전송 {r.status_code}")
            sent = 200 <= r.status_code < 300
        except Exception as e:
            print(f"  ⚠ 알림 전송 실패: {e}")
            sent = False
        if not sent:
            print("  ⚠ 알림이 전달되지 않아 기준은 그대로 둡니다.")
            return 4
    if not a.dry_run:
        tmp = a.state + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"at": datetime.now(_KST).isoformat(timespec="seconds"), "laws": res["snapshot"]}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, a.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
