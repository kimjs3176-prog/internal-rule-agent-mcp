"""기관 프로필 도입 점검 — 다른 기관이 org_config.json 을 고친 뒤, 쓰기 전에 실수를 찾는다.

사용법
    ORG_CONFIG=<프로필> REG_DIR=<내규 폴더> REG_MANIFEST=<매니페스트> python scripts/check_org_config.py

무엇을 보나
    1. 기관명·약칭·기관장 등 기본 항목이 비었거나 기본값(○○기관)인지
    2. 근거 규칙(rules_name, 예: 「내규관리규칙」)이 들여온 내규에 실제로 있는지
    3. 점검·심의·절차·문서의 근거 조항(lint_refs·doc_refs·review_criteria.ref·procedure 의 ref)이 그 규칙에 실제로 있는지
       — 다른 기관 프로필을 베껴 쓰면 조 번호가 남의 규칙을 가리키기 쉽다. 없는 조항은 고치거나 빈칸("")으로 둔다(빈칸이면 화면에 근거를 적지 않는다)
    4. 기관명·약칭이 들여온 내규 글에 나오는지(프로필을 다른 기관 것으로 둔 채 쓰는 실수)
    5. 옛 명칭(stale_terms)이 아직 몇 곳에 남았는지(건강검진에서 짚을 곳)
결과: 오류가 있으면 종료 코드 2, 주의만 있으면 0.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reg_agent as ra  # noqa: E402

_REF_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?(?:\s*제\s*(\d+)\s*호)?")
_HANG = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _refs(org: dict) -> list:
    """(어디에 쓰였나, 근거 문자열) 목록."""
    out = []
    lr = org.get("lint_refs") if isinstance(org.get("lint_refs"), dict) else {}
    out += [(f"lint_refs.{k}", v) for k, v in lr.items() if v]
    dr = org.get("doc_refs") if isinstance(org.get("doc_refs"), dict) else {}
    out += [(f"doc_refs.{k}", v) for k, v in dr.items() if v]          # 문서 문장의 근거 조항(입안·심의·사전예고·의견수렴 …)
    out += [(f"review_criteria[{c.get('id')}]", c.get("ref")) for c in org.get("review_criteria") or [] if c.get("ref")]
    pr = org.get("procedure") or {}
    out += [(f"procedure.questions[{q.get('k')}]", q.get("ref")) for q in pr.get("questions") or [] if q.get("ref")]
    out += [(f"procedure.steps[{s.get('id')}]", s.get("ref")) for s in pr.get("steps") or [] if s.get("ref")]
    return out


def _has(art: dict, hang: str, ho: str) -> bool:
    body = art.get("body") or ""
    if hang:
        h = int(hang)
        if h > len(_HANG) or _HANG[h - 1] not in body:
            return False
        nxt = _HANG[h] if h < len(_HANG) else None
        body = body.split(_HANG[h - 1], 1)[1]
        if nxt and nxt in body:
            body = body.split(nxt, 1)[0]
    if ho:
        return re.search(rf"(?m)^\s*{int(ho)}\.\s", body) is not None
    return True


def check(org: dict, regs: list) -> tuple:
    errs, warns, oks = [], [], []
    for k in ("org_name", "org_short", "head", "deputy", "email_domain"):
        v = org.get(k) or ""
        if not v or v == ra._ORG_DEFAULT.get(k):
            errs.append(f"{k} 가 비었거나 기본값({v})입니다. 기관에 맞게 적으세요.")
    oks.append(f"기관: {org.get('org_name')}(약칭 {org.get('org_short')}), 기관장 {org.get('head')}, 내규 {len(regs)}건")
    rules = next((r for r in regs if r["title"].replace(" ", "") == (org.get("rules_name") or "").replace(" ", "")), None)
    if not rules:
        errs.append(f"근거 규칙 「{org.get('rules_name')}」이 들여온 내규에 없습니다. rules_name 을 기관의 내규관리 규칙 이름으로 고치세요.")
    else:
        oks.append(f"근거 규칙 「{rules['title']}」 확인({len(rules['articles'])}개 조)")
        arts = {a["no"]: a for a in rules["articles"] if not a.get("deleted")}
        bad, n = [], 0
        for where, ref in _refs(org):
            for m in _REF_RE.finditer(str(ref)):
                n += 1
                no = m.group(1) + (f"의{m.group(2)}" if m.group(2) else "")
                a = arts.get(no)
                if not a or not _has(a, m.group(3), m.group(4)):
                    bad.append(f"{where}: “{m.group(0)}”")
        if bad:
            warns.append(f"근거 조항 {len(bad)}/{n}개가 「{rules['title']}」에 없습니다 — 기관 규칙의 조 번호로 고치거나 빈칸(\"\")으로 두세요:\n      "
                         + "\n      ".join(bad[:30]) + (f"\n      … 외 {len(bad) - 30}개" if len(bad) > 30 else ""))
        else:
            oks.append(f"근거 조항 {n}개 모두 「{rules['title']}」에 있음")
    text = "\n".join(a.get("body") or "" for r in regs for a in r["articles"])
    names = [x for x in (org.get("org_name"), org.get("org_short")) if x]
    if regs and not any(x in text for x in names):
        warns.append(f"기관명·약칭({', '.join(names)})이 들여온 내규 어디에도 없습니다. 다른 기관 프로필을 그대로 쓰고 있지 않은지 확인하세요.")
    for old, new in org.get("stale_terms") or []:
        c = text.count(old)
        if c:
            warns.append(f"옛 명칭 “{old}”이 {c}곳에 남아 있습니다(→ “{new}”). 건강검진·일괄 정비에서 고칠 수 있습니다.")
    if not ((org.get("alio") or {}).get("apba_id")):
        warns.append("alio.apba_id(알리오 기관 코드)가 비었습니다. 다른 기관 사례 조사에서 우리 기관을 빼지 못합니다(선택).")
    return errs, warns, oks


def main() -> int:
    regs = ra.all_regs()
    errs, warns, oks = check(ra.ORG, regs)
    for x in oks:
        print(f"  ✓ {x}")
    for x in warns:
        print(f"  ⚠ {x}")
    for x in errs:
        print(f"  ✗ {x}")
    print(f"\n결과: 오류 {len(errs)}, 주의 {len(warns)}")
    return 2 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
