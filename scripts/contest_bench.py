"""출품용 정량 성과 측정(서버 쪽) — 오류 주입 적발률과 주요 기능의 처리 시간.

사용법
    python scripts/contest_bench.py [--json 결과.json]

무엇을 재나
    1. 오류 주입 적발률: 등록된 모든 내규에 사람이 흔히 내는 오류 10종을 하나씩 심고, 조문 점검(lint)이 그 오류를
       새로 짚는지 본다. 같은 종류의 문제가 원래 있던 곳은 빼고 “새로 생긴 것”만 센다(심은 조를 정확히 짚었는지도 본다).
    2. 처리 시간: 내규 한 건 조문 점검, 전체 내규 건강검진, 전체 내규 일괄 정비(명칭 찾기), 인용 영향 분석, 제정 초안 틀.
결과는 화면에 표로 내고 --json 이면 파일로도 남긴다. 수치는 실행한 컴퓨터에 따라 달라진다.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reg_agent as ra  # noqa: E402

# (코드, 이름, 심는 방법) — 심는 방법은 (조문 목록, 부칙, 내규, 다른 내규 이름) → (조문, 부칙, 짚어야 할 조 번호 | None) 또는 None(적용 불가)


def _live(arts):
    return [i for i, a in enumerate(arts) if not a["deleted"] and a["no"].isdigit()]


def inj_ref(arts, add, reg, other):
    L = _live(arts)
    a = arts[L[len(L) // 2]]
    a["body"] += " 세부 사항은 제999조에 따른다."
    return arts, add, a["no"]


def inj_ref_deleted(arts, add, reg, other):
    L = _live(arts)
    x, a = arts[L[1]], arts[L[-1]]
    if x is a:
        return None
    x["deleted"], x["body"], x["title"] = True, "삭제", ""
    a["body"] += f" 이 경우 제{x['no']}조를 준용한다."
    return arts, add, a["no"]


def inj_dup(arts, add, reg, other):
    L = _live(arts)
    i = L[len(L) // 2]
    if i + 1 >= len(arts):
        return None
    arts[i + 1]["no"] = arts[i]["no"]
    return arts, add, arts[i]["no"]


def inj_order(arts, add, reg, other):
    L = _live(arts)
    i, j = L[len(L) // 2], L[len(L) // 2 + 1] if len(L) // 2 + 1 < len(L) else None
    if j is None:
        return None
    arts[i]["no"], arts[j]["no"] = arts[j]["no"], arts[i]["no"]
    return arts, add, None


def inj_title(arts, add, reg, other):
    L = _live(arts)
    a = arts[L[len(L) // 2]]
    if not a["title"]:
        return None
    a["title"] = ""
    return arts, add, a["no"]


def inj_addenda(arts, add, reg, other):
    if not (add or "").strip():
        return None
    return arts, "", None


def inj_hang(arts, add, reg, other):
    for i in _live(arts):
        b = arts[i]["body"]
        if "①" in b and "②" in b and "③" not in b:
            arts[i]["body"] = b.replace("②", "③", 1)
            return arts, add, arts[i]["no"]
    return None


def inj_stale(arts, add, reg, other):
    old = next((o for o, _ in ra.ORG.get("stale_terms") or []), "")
    if not old:
        return None
    a = arts[_live(arts)[0]]
    a["body"] += f" {old}의 업무는 따로 정한다."
    return arts, add, a["no"]


def inj_xref(arts, add, reg, other):
    a = arts[_live(arts)[-1]]
    a["body"] += f" 다만, 「{other}」 제999조의 경우는 예외로 한다."
    return arts, add, a["no"]


def inj_empty(arts, add, reg, other):
    a = arts[_live(arts)[len(_live(arts)) // 2]]
    a["body"] = ""
    return arts, add, a["no"]


INJECT = [("ref", "없는 조문 인용", inj_ref), ("ref", "삭제된 조문 인용", inj_ref_deleted), ("dup", "조 번호 중복", inj_dup),
          ("order", "조 번호 순서 뒤바뀜", inj_order), ("title", "조 제목 누락", inj_title), ("addenda", "부칙 누락", inj_addenda),
          ("hang", "항 번호 건너뜀(①→③)", inj_hang), ("stale", "옛 기관 명칭 사용", inj_stale),
          ("xref", "다른 내규의 없는 조문 인용", inj_xref), ("empty", "본문 빈 조", inj_empty)]


def _codes(issues, code):
    return [i for i in issues if i["code"] == code]


def inject_bench(regs):
    out = []
    for code, name, fn in INJECT:
        n = hit = exact = 0
        miss = []
        for k, r in enumerate(regs):
            if len(_live(r["articles"])) < 3:
                continue
            other = next(x["title"] for x in regs[k + 1:] + regs[:k] if x["articles"])   # 조문 체계가 있는 다른 내규(매뉴얼형은 조 번호를 견줄 수 없다)
            base = _codes(ra.lint_articles(r["articles"], r.get("addenda", ""), r.get("appendix", ""), r["title"]), code)
            res = fn(copy.deepcopy(r["articles"]), r.get("addenda", ""), r, other)
            if res is None:
                continue
            arts, add, target = res
            n += 1
            got = _codes(ra.lint_articles(arts, add, r.get("appendix", ""), r["title"]), code)
            new = [i for i in got if (i["no"], i["msg"]) not in {(b["no"], b["msg"]) for b in base}]
            if new:
                hit += 1
                exact += bool(target is None or any(str(i["no"]) == str(target) for i in new))
            else:
                miss.append(r["title"])
        out.append({"code": code, "name": name, "n": n, "hit": hit, "exact": exact, "miss": miss[:5]})
    return out


def _t(fn, rep=1):
    ts = []
    for _ in range(rep):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return statistics.median(ts)


def timing_bench(regs):
    from api_server import app
    c = app.test_client()
    r = ra.find_reg(title="여비규정") or regs[0]
    out = []
    lint_ts = [_t(lambda r=x: ra.lint_articles(r["articles"], r.get("addenda", ""), r.get("appendix", ""), r["title"])) for x in regs]
    out.append(("조문 점검(내규 1건, 전체 평균)", statistics.mean(lint_ts), f"{len(regs)}건 평균, 최대 {max(lint_ts):.2f}초"))
    out.append(("건강검진(전체 내규 진단)", _t(lambda: c.post("/api/regagent/health", json={}).get_json(), 3), f"{len(regs)}건"))
    out.append(("일괄 정비 — 모든 내규에서 명칭 찾기", _t(lambda: c.post("/api/regagent/bulk", json={"old": "기획운영본부", "new": "경영기획본부", "whole": True}).get_json(), 3), "“기획운영본부”→“경영기획본부”"))
    out.append(("인용 영향 분석(같은 내규·다른 내규)", _t(lambda: c.post("/api/regagent/impact", json={"slug": r["slug"], "nos": ["15"]}).get_json(), 3), f"「{r['title']}」 제15조"))
    out.append(("상위법 영향 조문 찾기", _t(lambda: c.post("/api/regagent/upper", json={"law": "근로기준법"}).get_json(), 3), "「근로기준법」"))
    out.append(("제정 초안 틀(AI 없이)", _t(lambda: ra.template_enact({"title": "업무용 드론 운영지침", "purpose": "드론 운영"}), 3), "업무용 드론 운영지침"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="정량 성과 측정(서버 쪽)")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    regs = ra.all_regs()
    inj = inject_bench(regs)
    tim = timing_bench(regs)
    env = {"python": platform.python_version(), "os": platform.platform(), "cpu": os.cpu_count(), "regs": len(regs),
           "articles": sum(len(r["articles"]) for r in regs), "at": time.strftime("%Y-%m-%d %H:%M")}
    print(f"환경: {env}\n")
    print("■ 오류 주입 적발률")
    tn = th = te = 0
    for x in inj:
        tn, th, te = tn + x["n"], th + x["hit"], te + x["exact"]
        print(f"  {x['name']:<22} {x['hit']:>4}/{x['n']:<4} ({x['hit'] / max(x['n'], 1) * 100:5.1f}%)  위치 정확 {x['exact']}" + (f"  놓침 예: {', '.join(x['miss'][:3])}" if x["miss"] else ""))
    print(f"  {'합계':<22} {th:>4}/{tn:<4} ({th / max(tn, 1) * 100:5.1f}%)  위치 정확 {te}")
    print("\n■ 처리 시간(중앙값)")
    for name, sec, note in tim:
        print(f"  {name:<30} {sec:7.3f}초  ({note})")
    print(f"\n전체 측정 {time.perf_counter() - t0:.1f}초")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"env": env, "inject": inj, "timing": [{"name": n, "sec": round(s, 4), "note": t} for n, s, t in tim]}, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
