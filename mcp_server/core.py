"""MCP(Model Context Protocol) 도구와 메시지 처리 — 표준 입출력(server.py)과 원격 URL(remote.py)이 함께 쓴다.

도구는 웹 서비스와 같은 API 를 같은 프로세스 안에서 부른다(네트워크 없음). 결과는 웹 화면과 같다.
  - stdio: 내 컴퓨터의 AI 도우미(Claude Desktop·Claude Code 등)가 띄운다. 문서는 output_dir 에 파일로 저장한다.
  - http : 배포한 서버의 /mcp 주소를 claude.ai·ChatGPT 커넥터 등에 등록한다. 파일을 쓰지 않고, 문서는 내려받기 링크로 준다.
"""
import base64
import contextvars
import hashlib
import hmac
import json
import os
import re
import zlib
from urllib.parse import quote

from . import engine

VERSION = "1.1.0"
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
MAX_TEXT = 200000
MAX_LINK = 12000                                        # 내려받기 링크(요청을 담은 토큰) 최대 길이 — 주소 길이 제한(약 14KB) 안

_CTX = contextvars.ContextVar("mcp_ctx", default=None)


def _mode():
    c = _CTX.get()
    return (c or {}).get("mode", "stdio")


def _base_url():
    c = _CTX.get()
    return ((c or {}).get("base") or "").rstrip("/")


# ── 웹 서비스 API 를 그대로 부른다(같은 프로세스, 네트워크 없음) ───────────────────────
def _client():
    return engine.app().test_client()                    # 웹 서비스와 같은 앱·블루프린트·데이터(지금 요청을 받는 그 앱)


def _get(path, **q):
    r = _client().get(path, query_string={k: v for k, v in q.items() if v not in (None, "")})
    return r.get_json(silent=True) or {"success": False, "error": f"응답 오류({r.status_code})"}


def _post(path, body):
    r = _client().post(path, json=body)
    return r.get_json(silent=True) or {"success": False, "error": f"응답 오류({r.status_code})"}


def _catalog():
    return _get("/api/regagent/catalog").get("regs", [])


def _find(name):
    """내규명(일부만 적어도 됨) 또는 slug → 내규 하나. 없으면 비슷한 이름 후보."""
    name = str(name or "").strip().strip("「」 ")
    cat = _catalog()
    for r in cat:
        if name in (r["slug"], r["title"]):
            return r, []
    key = name.replace(" ", "")
    hits = [r for r in cat if key and key in r["title"].replace(" ", "")]
    if len(hits) == 1:
        return hits[0], []
    return None, [r["title"] for r in hits][:8]                # 여러 개면 고르게 후보를 준다


def _not_found(regulation, cand):
    return {"error": f"「{regulation}」을(를) 찾지 못했습니다." + (" 아래 후보 중에서 고르세요." if cand else " list_regulations 로 이름을 확인하세요."),
            "candidates": cand}


def _title(slug):
    for r in _catalog():
        if r["slug"] == slug:
            return r["title"]
    return slug


def _list(v):
    """배열 자리에 글 하나가 와도 받아 준다(“제15조” → ["제15조"], “제15조, 제16조” → 둘)."""
    if v is None or v == "":
        return []
    if isinstance(v, str):
        return [x for x in re.split(r"\s*[,，·]\s*", v) if x.strip()]
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _art_no(a):
    return re.sub(r"\s+", "", str(a)).replace("제", "").replace("조", "", 1) if str(a).strip() else ""


def _lbl(no):
    """조 번호 → 인용 꼴(“7의3” → “제7조의3”) — 화면·원문과 같다. 숫자가 아니면(별표 등) 그대로."""
    s = str(no or "")
    if not re.match(r"\d", s):
        return s
    import reg_agent
    return reg_agent.art_label(s)


def _reg_url(slug):
    """원문 보기 주소(원격 연결일 때만 — 서버가 /regulations/ 아래 원문 HTML 을 내준다)."""
    base = _base_url()
    if not base:
        return ""
    try:
        import reg_chunks
        if not os.path.exists(os.path.join(reg_chunks.REG_DIR, slug, "index.html")):
            return ""
    except Exception:
        return ""
    return f"{base}/regulations/{quote(slug)}/index.html"


# ── 읽기 도구 ─────────────────────────────────────────────────────────────────
def _kw_search(query, limit=15):
    """문장으로 물을 때(“출장 숙박비 상한은 얼마인가요”) — 화면의 비슷한 조문 찾기와 같은 검색(드문 낱말에 무게, 동의어 포함). 조문을 점수 순으로."""
    d = _post("/api/regagent/similar", {"query": str(query or "")[:600], "limit": 15})
    rows = [{"slug": r["slug"], "reg": r.get("title", r["slug"]), "no": a["no"], "title": a.get("title", ""), "snip": str(a.get("body", ""))[:120], "score": a.get("score", 0)}
            for r in d.get("regs", []) for a in r.get("articles", [])]
    return sorted(rows, key=lambda e: -e["score"])[:limit]


def t_search_regulations(query, limit=10):
    d = _get("/api/regagent/regs/search", q=query)
    if not d.get("success"):
        return d
    if not d.get("regs") and re.search(r"\S\s+\S", str(query or "")):   # 붙은 말로 없으면 낱말별로(“출장 숙박비 상한”)
        regs = {}
        for e in _kw_search(query, 30):
            g = regs.setdefault(e["slug"], {"slug": e["slug"], "hits": None, "arts": []})
            g["arts"].append({"no": e["no"], "title": e["title"], "snip": e["snip"]})
        d = {"q": d.get("q") or query, "regs": list(regs.values()), "by": "낱말별 검색(점수 순)"}
    out = []
    for r in d.get("regs", [])[: max(1, min(int(limit or 10), 30))]:
        row = {"regulation": _title(r["slug"]), "slug": r["slug"], "hits": r.get("hits"),
               "articles": [{"article": _lbl(a['no']), "title": a["title"], "snippet": a["snip"]} for a in r.get("arts", [])[:5]]}
        if _reg_url(r["slug"]):
            row["url"] = _reg_url(r["slug"])
        out.append(row)
    return {"query": d.get("q"), "count": len(out), "results": out}


def t_list_regulations(category=""):
    regs = _catalog()
    if category:
        regs = [r for r in regs if r.get("category") == category]
    return {"count": len(regs), "regulations": [{"regulation": r["title"], "category": r.get("category"), "revision": r.get("revision"),
                                                  "articles": r.get("live")} for r in regs]}


def t_get_regulation(regulation, articles=None, include_appendix=False, appendices=None):
    r, cand = _find(regulation)
    if not r:
        return _not_found(regulation, cand)
    d = _get("/api/regagent/articles", slug=r["slug"])
    if not d.get("success"):
        return d
    want = {_art_no(a) for a in _list(articles) if _art_no(a)}
    arts = [a for a in d["articles"] if not want or a["no"] in want]
    out = {"regulation": d["title"], "category": d.get("category"), "revision": d.get("revision"),
           "article_count": len(d["articles"]),
           "articles": [{"article": _lbl(a['no']), "title": a.get("title", ""), "deleted": bool(a.get("deleted")), "body": a.get("body", "")} for a in arts],
           "appendices": [x.get("id") for x in d.get("appendix", [])]}
    if _reg_url(r["slug"]):
        out["url"] = _reg_url(r["slug"])
    if want and not arts:
        out["note"] = f"요청한 조({', '.join(sorted(want))})가 없습니다."
    pick = {re.sub(r"\s+", "", str(x)).replace("별표", "별표 ") for x in _list(appendices)}
    if include_appendix or pick:
        out["appendix_text"] = [{"id": x.get("id"), "head": x.get("head", ""), "body": x.get("body", "")} for x in d.get("appendix", [])
                                if not pick or x.get("id") in pick]
    return out


def t_check_regulation(regulation="", text="", title=""):
    if text:
        d = _post("/api/regagent/lint", {"text": text, "title": title or "검토안"})
    else:
        if not regulation:
            return {"error": "regulation(내규명)이나 text(조문 글) 중 하나를 주세요."}
        r, cand = _find(regulation)
        if not r:
            return _not_found(regulation, cand)
        d = _post("/api/regagent/lint", {"slug": r["slug"]})
    if not d.get("success"):
        return d
    iss = d.get("issues", [])
    lv = {"error": "오류", "warn": "주의", "info": "표기 제안"}
    return {"regulation": d.get("reg") or title or "검토안", "errors": sum(i["level"] == "error" for i in iss), "warnings": sum(i["level"] == "warn" for i in iss),
            "suggestions": sum(i["level"] == "info" for i in iss),
            "issues": [{"level": lv.get(i["level"], i["level"]), "article": _lbl(i['no']) if i.get("no") else "", "message": i["msg"], "fix": i.get("fix", "")} for i in iss[:60]]}


def t_health_check(top=10):
    d = _post("/api/regagent/health", {})
    if not d.get("success"):
        return d
    rows = sorted([r for r in d.get("rows", []) if r.get("score") is not None], key=lambda r: r["score"])[: max(1, min(int(top or 10), 30))]
    return {"regulations": d.get("count"), "average_score": d.get("avg"), "grades": d.get("grades"), "with_issues": d.get("with_issues"),
            "with_errors": d.get("with_errors"), "issue_total": d.get("issue_total"), "not_revised_3y": d.get("old_regs"),
            "lowest": [{"regulation": r["title"], "score": r["score"], "grade": r["grade"], "revision": r.get("revision"),
                        "reasons": [x if isinstance(x, str) else x.get("t") or x.get("msg") or json.dumps(x, ensure_ascii=False) for x in r.get("reasons", [])][:6]} for r in rows]}


def t_citation_impact(regulation, articles):
    r, cand = _find(regulation)
    if not r:
        return _not_found(regulation, cand)
    nos = [_art_no(a) for a in _list(articles) if _art_no(a)]
    d = _post("/api/regagent/impact", {"slug": r["slug"], "nos": nos, "moves": {}})
    if not d.get("success"):
        return d
    return {"regulation": r["title"], "summary": d.get("summary"),
            "same_regulation": [{"article": _lbl(h['no']), "title": h.get("title"), "cites": h.get("text"), "snippet": h.get("snippet"), "suggest": h.get("suggest")} for h in d.get("inner", [])],
            "other_regulations": d.get("outer", []), "appendices": d.get("appendix", []), "mentions": d.get("mentions", [])}


def t_upper_law_impact(law, articles=None, old_text="", new_text=""):
    d = _post("/api/regagent/upper", {"law": law, "arts": _list(articles), "old": old_text, "new": new_text})
    if not d.get("success"):
        return d
    return {"law": d.get("law"), "candidates": [{"regulation": c.get("reg"), "article": _lbl(c['no']), "body": c.get("body"), "score": c.get("score"),
                                                 "cites": c.get("cites")} for c in d.get("candidates", [])[:30]],
            "count": d.get("count"), "removed_terms": d.get("removed_terms")}


def t_bulk_rename(old, new):
    d = _post("/api/regagent/bulk", {"old": old, "new": new, "whole": True})
    if not d.get("success"):
        return d
    return {"old": d["old"], "new": d["new"], "regulations": d["reg_count"], "places": d["total"],
            "amendments": [{"regulation": r.get("reg") or r.get("title"), "amendment_text": r.get("amend_text"),
                            "places": [loc for a in r.get("articles", []) for loc in a.get("locs", [])]
                            + [x.get("id") for x in r.get("appx", []) if x.get("id")]} for r in d.get("regs", [])]}


def t_advise(question, regulation=""):
    body = {"question": question}
    if regulation:
        r, cand = _find(regulation)
        if not r:
            return _not_found(regulation, cand)
        body["slug"] = r["slug"]
    d = _post("/api/regagent/advise", body)
    if not d.get("success"):
        return d
    return {k: d.get(k) for k in ("question", "answer", "conclusion", "basis", "conditions", "caveats", "laws", "followups") if d.get(k)}


# ── 다른 기관 사규(알리오) — 공공기관 경영정보 공개시스템에 공시된 내부규정을 찾아 읽고 견준다 ─────────────
ALIO_SCOPES = ("peer", "type", "all")
ALIO_MAX_ORGS = 48                                      # 한 번에 조회할 기관 수 상한(알리오 서버 부담·응답 시간)
ALIO_ID = re.compile(r"^([A-Za-z0-9]{2,12})\|(\d{1,12})\|(K\d{4})?\|([A-Z_]{1,30})\|([A-Z_]{1,30})\|(.{0,40})$")


def _alio_orgs():
    d = _get("/api/regagent/alio/orgs")
    if not d.get("success"):
        raise _AlioDown(d.get("error") or "알리오 기관 목록을 불러오지 못했습니다.")
    return d


class _AlioDown(Exception):
    pass


_ALIO_DATE = re.compile(r"[(（\[]\s*(?:제정|개정|시행|전부개정|일부개정)?\s*[`'’]?[\d.\s년도월일차~-]{4,}\s*(?:제정|개정|시행)?\s*[)）\]]")


def _alio_base(t):
    """규정명에서 제·개정일 괄호를 뗀다(화면의 alioBase 와 같다): “인사규정(2023.1.1. 개정)” → “인사규정”."""
    return _ALIO_DATE.sub("", str(t or "")).strip()


def _alio_id(h):
    return "|".join([h["orgId"], str(h["idx"]), h.get("category") or "", h.get("table") or "COMM_RULE", h.get("idxName") or "RULE_NO", str(h.get("mod") or "")[:40]])


def _alio_rule(rid):
    m = ALIO_ID.match(str(rid or "").strip())
    if not m:
        return None
    return {"orgId": m.group(1), "idx": m.group(2), "category": m.group(3) or "", "table": m.group(4), "idxName": m.group(5), "mod": m.group(6)}


def _alio_url(rule):
    import alio
    return alio.BASE + alio.detail_url(rule)


def _alio_scope(D, scope, agencies):
    """조회할 기관 ID 목록과 알림. agencies(기관명·ID)가 있으면 그것만, 없으면 범위(peer 유관·type 같은 유형·all 전체).
    기관명은 정확히 맞거나, 일부만 적었으면 그 말이 든 기관이 하나뿐일 때만 고른다(여럿이면 고르지 않고 후보를 알린다)."""
    orgs, me, note = D["orgs"], D.get("self"), ""
    if agencies:
        ids, miss, amb = [], [], []
        for a in _list(agencies):
            k = re.sub(r"\s+", "", str(a))
            o = next((o for o in orgs if k and (o["id"] == k or re.sub(r"\s+", "", o["name"]) == k)), None)
            if not o:
                cand = [o for o in orgs if k and k in re.sub(r"\s+", "", o["name"])]
                if len(cand) == 1:
                    o = cand[0]
                elif cand:
                    amb.append(f"‘{a}’ → {', '.join(c['name'] for c in cand[:6])}{' 등' if len(cand) > 6 else ''}")
                    continue
            if not o:
                miss.append(str(a))
            elif o["id"] not in ids:
                ids.append(o["id"])
        notes = []
        if amb:
            notes.append("이름이 여러 기관에 맞아 고르지 않았습니다(정확한 기관명이나 ID로 다시 주세요): " + "; ".join(amb))
        if miss:
            notes.append(f"알리오에서 찾지 못한 기관: {', '.join(miss[:5])}")
        note = " ".join(notes)
    elif scope == "type":
        t = next((o.get("type") for o in orgs if o["id"] == me), "")
        ids = [o["id"] for o in orgs if o["id"] != me and (not t or o.get("type") == t)]
    elif scope == "all":
        ids = [o["id"] for o in orgs if o["id"] != me]
    else:
        ids = list(D.get("peers") or [])
        if not ids:
            note = "유관 기관이 설정되어 있지 않습니다(org_config.json alio.peer_depts). scope 를 type 이나 all 로 넓히거나 agencies 로 기관을 고르세요."
    if len(ids) > ALIO_MAX_ORGS:
        note = (note + " " if note else "") + f"범위가 넓어 {len(ids)}곳 중 앞의 {ALIO_MAX_ORGS}곳만 조회했습니다. agencies 로 기관을 고르면 그 기관을 조회합니다."
        ids = ids[:ALIO_MAX_ORGS]
    return ids, note


def _alio_cat(category):
    """분류: 코드(K1100)·이름(인사·복무·징계)·그 일부(인사, 복무) → 코드. 모르는 말이면 (None, 안내)."""
    import alio
    c = re.sub(r"\s+", "", str(category or ""))
    if not c:
        return "", ""
    for k, v in alio.CATEGORIES.items():
        if c in (k, v.replace(" ", "")) or c in v.split("·") or c in v:
            return k, ""
    return None, f"분류는 {', '.join(alio.CATEGORIES.values())} 중 하나입니다."


def _alio_hits(keyword, ids, batch, category="", all_=False, deadline=None):
    """기관을 나눠(한 번에 12곳) 알리오 규정 검색 → (hits, 실패 목록, 실제로 조회한 기관 수). 시간이 모자라면 남은 기관은 조회하지 않는다."""
    import time
    hits, failed, queried, B = [], [], 0, batch or 12
    for i in range(0, len(ids), B):
        if i and deadline and time.monotonic() > deadline - 10:          # 첫 묶음은 늘 조회한다
            failed.append({"error": f"시간 제한으로 {len(ids) - i}곳은 조회하지 않음", "skipped": len(ids) - i})
            break
        d = _post("/api/regagent/alio/search", {"q": keyword, "orgs": ids[i:i + B], "category": category, "all": all_})
        if not d.get("success"):
            if not queried:
                raise _AlioDown(d.get("error") or "알리오 조회 실패")
            failed.append({"error": d.get("error") or "알리오 조회 실패", "skipped": len(ids) - i})
            break
        queried += len(ids[i:i + B])
        hits += d.get("hits", [])
        failed += [{"agency": f.get("org"), "error": f.get("error")} for f in (d.get("failed") or []) + (d.get("timedOut") or [])]
    k = re.sub(r"\s+", "", keyword or "")
    hits.sort(key=lambda h: (0 if k and re.sub(r"\s+", "", _alio_base(h["title"])).startswith(k) else 1, -int(re.sub(r"\D", "", h.get("enf") or "") or 0)))
    return hits, failed, queried


def _alio_fail_report(out, hits, failed, queried):
    """조회 실패를 숨기지 않는다: 실패 수를 적고, 결과 없이 절반 이상 실패했으면 오류로 돌린다(“그런 규정이 없다”로 읽히지 않게)."""
    bad = sum(1 for f in failed if f.get("agency"))
    skipped = sum(int(f.get("skipped") or 0) for f in failed)
    if failed:
        out["failed_count"] = bad + skipped
        out["failed"] = failed[:10]
    if not hits and (bad + skipped) and (bad + skipped) >= max(1, (queried + skipped) / 2):
        first = next((f.get("error") for f in failed if f.get("error")), "알리오 응답 없음")
        return {"error": f"알리오에서 {queried + skipped}곳 중 {bad + skipped}곳을 조회하지 못했습니다({first}). 잠시 뒤 다시 시도하거나 agencies 로 기관을 좁히세요.",
                "failed": failed[:10]}
    return out


def t_alio_search(keyword, scope="peer", agencies=None, category="", include_old=False, limit=30):
    kw = re.sub(r"\s+", " ", str(keyword or "")).strip()[:40]
    cat, cat_err = _alio_cat(category)
    if cat is None:
        return {"error": cat_err}
    if len(kw.replace(" ", "")) < 2 and not cat:
        return {"error": "규정명 검색어를 두 글자 이상 주세요(예: 여비, 드론, 재택근무)."}
    try:
        D = _alio_orgs()
        ids, note = _alio_scope(D, scope if scope in ALIO_SCOPES else "peer", agencies)
        if not ids:
            return {"error": note or "조회할 기관이 없습니다."}
        hits, failed, queried = _alio_hits(kw, ids, D.get("batch"), cat, all_=not kw)
    except _AlioDown as e:
        return {"error": str(e)}
    if not include_old:
        hits = [h for h in hits if not h.get("superseded")]
    lim = max(1, min(int(limit or 30), 100))
    out = {"keyword": kw, "scope": "agencies" if agencies else (scope if scope in ALIO_SCOPES else "peer"), "agencies_searched": queried,
           "agencies_found": len({h["orgId"] for h in hits}), "count": len(hits),
           "results": [{"id": _alio_id(h), "agency": h["org"], "regulation": _alio_base(h["title"]), "title": h["title"],
                        "category": h.get("categoryName") or "", "enforced": h.get("enf") or "", "superseded": bool(h.get("superseded")),
                        "url": _alio_url({"orgId": h["orgId"], "idx": h["idx"], "category": h.get("category"), "table": h.get("table"), "idxName": h.get("idxName")})}
                       for h in hits[:lim]],
           "next": "조문은 alio_get_regulation 에 id 를 넣어 읽는다(질문·주제를 query 로 주면 관련 조문이 먼저 온다)."}
    if note:
        out["note"] = note
    if len(hits) > lim:
        out["truncated"] = f"{len(hits)}건 중 {lim}건만 보였습니다(limit)."
    return _alio_fail_report(out, hits, failed, queried)


def t_alio_get_regulation(id, query="", articles=None, limit=12):
    rule = _alio_rule(id)
    if not rule:
        return {"error": "id 는 alio_search_regulations 결과의 id 를 그대로 넣으세요(예: C0105|21892|K1100|COMM_RULE|RULE_NO|…)."}
    try:
        D = _alio_orgs()                                # 알리오에 닿지 않으면 규정 파일을 기다리지 않고 바로 알린다(기관명도 여기서)
    except _AlioDown as e:
        return {"error": str(e), "url": _alio_url(rule)}
    nos = [_art_no(a) for a in _list(articles) if _art_no(a)]
    d = _post("/api/regagent/alio/rule", {**rule, "q": str(query or "")[:300], "kw": str(query or "")[:40], "nos": nos,
                                          "limit": max(1, min(int(limit or 12), 80))})
    if not d.get("success"):
        return {"error": d.get("error") or "알리오 규정을 읽지 못했습니다.", "url": _alio_url(rule)}
    name = (d.get("file") or {}).get("fileName") or ""
    agency = next((o["name"] for o in D.get("orgs", []) if o["id"] == rule["orgId"]), "")
    out = {"id": id, "agency": agency, "regulation": _alio_base(os.path.splitext(name)[0]) if name else "", "file": name,
           "article_count": d.get("count"), "toc": d.get("toc", []),
           "articles": [{"article": _lbl(a['no']), "title": a.get("title", ""), "body": a.get("body", ""), "relevant": bool(a.get("rel"))}
                        for a in d.get("articles", [])],
           "url": d.get("url") or _alio_url(rule),
           "source": "알리오(공공기관 경영정보 공개시스템) 공시 현행본 — 인용할 때 기관명·규정명·조를 밝히세요."}
    for k in ("warning", "excerpt"):
        if d.get(k):
            out[k] = d[k]
    if d.get("missing"):
        out["missing"] = [_lbl(n) for n in d["missing"]]
    return out


_UNITS = ("원", "일", "개월", "년", "시간", "%", "회", "명", "배", "분")
COMPARE_BUDGET = 45                                     # 수치 비교 한 번의 전체 제한(초) — 클라이언트 요청 제한(흔히 60초) 안에 답한다


def t_alio_compare_values(item, unit, keyword, scope="peer", agencies=None, max_agencies=15):
    """유관 기관 사규에서 같은 항목(일비·경조휴가 일수 등)의 수치를 뽑아 견준다(화면의 ‘다른 기관은 얼마로 정했나’와 같은 방식).
    전체를 COMPARE_BUDGET 안에 끝낸다: 남은 시간이 모자란 기관은 ‘시간 제한으로 건너뜀’으로 알리고 끝난 것만 돌려준다."""
    import concurrent.futures as cf
    import statistics
    import time
    import alio
    import reg_agent
    t_end = time.monotonic() + COMPARE_BUDGET
    item = re.sub(r"\s+", " ", str(item or "")).strip()[:20]
    kw = re.sub(r"\s+", " ", str(keyword or "")).strip()[:40]
    if len(item.replace(" ", "")) < 2 or unit not in _UNITS:
        return {"error": f"비교할 항목(두 글자 이상)과 단위({'·'.join(_UNITS)})를 주세요."}
    if len(kw.replace(" ", "")) < 2:
        return {"error": "찾을 규정명(예: 여비, 복무, 보수)을 keyword 로 주세요."}
    try:
        D = _alio_orgs()
        ids, note = _alio_scope(D, scope if scope in ALIO_SCOPES else "peer", agencies)
        if not ids:
            return {"error": note or "조회할 기관이 없습니다."}
        hits, failed, queried = _alio_hits(kw, ids, D.get("batch"), deadline=t_end)
    except _AlioDown as e:
        return {"error": str(e)}
    best = {}
    for h in hits:                                       # 기관마다 규정명이 검색어로 시작하는(가장 최근) 하나
        if not h.get("superseded") and h["orgId"] not in best:
            best[h["orgId"]] = h
    pick = list(best.values())[: max(1, min(int(max_agencies or 15), 30))]

    def one(h):
        left = t_end - time.monotonic()
        if left < 3:
            return {"error": "시간 제한으로 건너뜀"}
        try:
            r = alio.rule_text({k: h.get(k) or "" for k in ("orgId", "idx", "category", "table", "idxName", "mod")}, budget=min(alio.RULE_BUDGET, left - 1))
        except alio.AlioError as e:
            return {"error": str(e)}
        except Exception as e:                           # noqa: BLE001 — 한 기관의 실패가 전체를 멈추지 않게
            return {"error": f"읽지 못함({type(e).__name__})"}
        return {"matches": reg_agent.bench_extract(r["text"], item, unit)}

    ex = cf.ThreadPoolExecutor(max_workers=3)            # 화면과 같이 세 곳씩
    futs = {ex.submit(one, h): h for h in pick}
    done, _pending = cf.wait(futs, timeout=max(1.0, t_end - time.monotonic()))
    ex.shutdown(wait=False, cancel_futures=True)         # 끝나지 않은 것은 기다리지 않는다
    rows, none = [], []
    for f, h in futs.items():
        base = {"agency": h["org"], "regulation": _alio_base(h["title"]), "url": _alio_url(h), "id": _alio_id(h)}
        d = f.result() if f in done else {"error": "시간 제한으로 건너뜀"}
        if d.get("matches"):
            m = d["matches"][0]
            rows.append({**base, "value": m["first"], "values": m.get("vals", []), "article": _lbl(m.get("no")),
                         "sentence": m.get("text", ""), "other_matches": [x.get("text", "") for x in d["matches"][1:3]]})
        else:
            none.append({**base, "reason": d.get("error") or "이 항목의 수치를 찾지 못함(표로만 적혀 있을 수 있음)"})
    vals = [r["value"] for r in rows]
    out = {"item": item, "unit": unit, "keyword": kw, "agencies_searched": queried, "regulations_checked": len(pick),
           "values": sorted(rows, key=lambda r: -r["value"]), "not_found": none,
           "summary": ({"count": len(vals), "min": min(vals), "max": max(vals), "median": statistics.median(vals)} if vals else {"count": 0}),
           "ours": _our_values(kw, item, unit) or {"note": f"우리 기관 내규 문장에서 “{item}” 수치를 찾지 못했습니다(별표 표에만 있을 수 있음). get_regulation 의 appendices 로 별표를 읽어 확인하세요."},
           "caution": "기관마다 표기가 달라 잘못 뽑힐 수 있습니다. sentence(원문 문장)를 보고 같은 기준인지 확인한 뒤 인용하세요. 별표 표로만 적힌 수치는 못 찾을 수 있습니다."}
    if any(n["reason"] == "시간 제한으로 건너뜀" for n in none):
        out["partial"] = f"{COMPARE_BUDGET}초 안에 끝내려고 일부 기관은 읽지 못했습니다. max_agencies 를 줄이거나 agencies 로 기관을 고르면 그 기관을 끝까지 봅니다."
    if note:
        out["note"] = note
    return _alio_fail_report(out, hits, failed, queried)


def _our_values(kw, item, unit):
    """우리 기관 내규 중 규정명에 keyword 가 든 것에서 같은 항목의 수치."""
    import reg_agent
    k = re.sub(r"\s+", "", kw)
    out = []
    for r in _catalog():
        if k and k in r["title"].replace(" ", ""):
            for m in reg_agent.bench_extract(reg_agent._reg_raw_text(r["slug"]), item, unit)[:2]:
                out.append({"regulation": r["title"], "value": m["first"], "article": _lbl(m.get("no")),
                            "sentence": m.get("text", "")})
        if len(out) >= 4:
            break
    return out


def _refs_in(refs):
    """AI 가 넘긴 다른 기관 참고 조문 → 엔진 형식(검토 보고서 ‘자료조사 결과’·심의 사전검토 ‘다른 공공기관 운영 사례’에 쓰인다)."""
    out = []
    for r in _list(refs)[:12]:
        if not isinstance(r, dict):
            continue
        org = str(r.get("agency") or r.get("org") or "").strip()[:40]
        reg = str(r.get("regulation") or r.get("reg") or "").strip().strip("「」")[:60]
        if not org or not reg:
            continue
        out.append({"org": org, "reg": reg, "no": _art_no(r.get("article") or r.get("no") or ""), "title": str(r.get("title") or "")[:40],
                    "body": str(r.get("body") or "")[:1500]})
    return out


# ── ChatGPT 커넥터·심층 리서치 규격(search·fetch) ─────────────────────────────────
def t_search(query):
    d = _get("/api/regagent/regs/search", q=query)
    rows = [{"slug": r["slug"], "no": a["no"], "title": a["title"]} for r in d.get("regs", [])[:10] for a in r.get("arts", [])[:3]]
    if not rows:
        rows = _kw_search(query)
    titles = {r["slug"]: r["title"] for r in _catalog()}
    res = []
    for e in rows[:20]:
        title = titles.get(e["slug"], e["slug"])
        lb = _lbl(e["no"])
        res.append({"id": f"{e['slug']}#{lb}", "title": f"「{title}」 {lb}({e['title']})" if e.get("title") else f"「{title}」 {lb}",
                    "url": _reg_url(e["slug"]) or f"reg:{e['slug']}"})
    return {"results": res}


def t_fetch(id):
    rid = str(id or "").strip()
    name, _, part = rid.partition("#")
    r, cand = _find(name)
    if not r:
        return _not_found(name, cand)
    d = _get("/api/regagent/articles", slug=r["slug"])
    if not d.get("success"):
        return d
    url = _reg_url(r["slug"]) or f"reg:{r['slug']}"
    meta = {"regulation": d["title"], "revision": d.get("revision"), "category": d.get("category")}
    part = re.sub(r"\s+", "", part)
    if part.startswith("별표"):
        x = next((x for x in d.get("appendix", []) if re.sub(r"\s+", "", x.get("id", "")) == part), None)
        if not x:
            return {"error": f"「{d['title']}」에 {part}가 없습니다.", "appendices": [y.get("id") for y in d.get("appendix", [])]}
        return {"id": rid, "title": f"「{d['title']}」 {x['id']}", "text": f"{x.get('head', '')}\n{x.get('body', '')}".strip(), "url": url, "metadata": meta}
    if part:
        no = _art_no(part)
        a = next((a for a in d["articles"] if a["no"] == no), None)
        if not a:
            return {"error": f"「{d['title']}」에 {_lbl(no)}가 없습니다."}
        t = f"{_lbl(a['no'])}({a.get('title', '')})" if a.get("title") else _lbl(a["no"])
        return {"id": rid, "title": f"「{d['title']}」 {t}", "text": f"{t} {a.get('body', '')}".strip(), "url": url, "metadata": meta}
    body = "\n\n".join((f"{_lbl(a['no'])}({a.get('title', '')}) " if a.get("title") else f"{_lbl(a['no'])} ") + a.get("body", "") for a in d["articles"])
    return {"id": rid, "title": f"「{d['title']}」", "text": body[:100000], "url": url, "metadata": meta}


# ── 화면 엔진 도구(에이전트·개정문) ───────────────────────────────────────────────
def _fmt(f):
    return "docx" if str(f or "").lower() == "docx" else "hwpx"


def _doc_bytes(doc, fmt):
    r = _client().post(f"/api/regagent/{fmt}", json={"filename": doc["filename"], "blocks": doc["blocks"]})
    if r.status_code != 200:
        return None, f"문서 저장 실패({r.status_code})"
    return r.get_data(), ""


def _save(doc, out_dir, fmt):
    data, err = _doc_bytes(doc, fmt)
    if err:
        return {"error": err}
    d = os.path.abspath(os.path.expanduser(str(out_dir)))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, re.sub(r'[\\/:*?"<>|]', "_", doc["filename"]) + "." + fmt)
    with open(path, "wb") as f:
        f.write(data)
    return {"file": path, "documents": doc.get("documents", [])}


def _secret():
    return (os.environ.get("MCP_TOKEN") or "").strip()


# 엔진에 넘기는 입력: 작업별로 허용한 키만, 글 길이 상한을 둔다. 엔진(JS 정규식)은 서버에서 돌고 QuickJS 는 정규식 계산을 중간에 끊지 못하므로
# 입력 크기로 계산량을 묶는다(내려받기 링크도 같은 정리를 거친다).
_KEYS = {"agent": ("request",), "amend": ("slug", "changes", "appendix_changes", "addenda", "reason", "effective", "references"),
         "enact": ("title", "text", "purpose", "addenda", "effective", "references")}
_CAP = {"request": 500, "slug": 200, "title": 120, "text": 30000, "purpose": 3000, "reason": 3000, "addenda": 3000, "effective": 40}
MAX_CHANGE_CHARS = 60000                                # 고친 조문 본문의 합


def _norm_changes(changes):
    """고칠 조문: 조 번호를 엔진 꼴로(“제13조의2”·“제13의2조” → 13의2), 같은 조가 두 번이면 마지막 것만(알림), 본문 길이 상한."""
    if isinstance(changes, dict):
        changes = [changes]
    if not isinstance(changes, list):
        return [], []
    by, order, warn, total = {}, [], [], 0
    for c in changes[:80]:
        if not isinstance(c, dict):
            continue
        no = _art_no(c.get("article") or c.get("no") or "")
        if not no:
            continue
        t = str(c.get("type") or ("delete" if c.get("delete") else "modify")).lower()
        body = str(c.get("body") or "")[:20000]
        if total + len(body) > MAX_CHANGE_CHARS:
            warn.append(f"고친 조문이 너무 길어 {_lbl(no)}부터는 빼었습니다(합계 {MAX_CHANGE_CHARS:,}자까지).")
            break
        total += len(body)
        e = {"article": no, "type": t if t in ("modify", "insert", "delete") else "modify", "body": body}
        if c.get("title") is not None and str(c.get("title")).strip():        # 비우면 현행 제목
            e["title"] = str(c["title"])[:100]
        if no in by:
            warn.append(f"{_lbl(no)}가 두 번 들어와 마지막 것을 썼습니다.")
        else:
            order.append(no)
        by[no] = e
    return [by[n] for n in order], warn


def _norm_appx(xs):
    out = []
    for x in (xs if isinstance(xs, list) else [xs] if isinstance(xs, dict) else [])[:20]:
        if not isinstance(x, dict) or not str(x.get("id") or "").strip():
            continue
        k = str(x["id"]).strip()[:40]
        if re.fullmatch(r"\d+(?:의\d+)?", re.sub(r"\s+", "", k)):            # “2” → “별표 2”
            k = "별표 " + re.sub(r"\s+", "", k)
        e = {"id": k, "body": str(x.get("body") or "")[:30000]}
        if x.get("head") is not None and str(x.get("head")).strip():
            e["head"] = str(x["head"])[:300]
        out.append(e)
    return out


def clean_input(op, inp):
    """작업 입력 정리 → (inp, 알림). 도구 호출과 내려받기 링크가 같은 규칙을 쓴다."""
    if op not in _KEYS or not isinstance(inp, dict):
        raise ValueError("알 수 없는 작업입니다.")
    out, warn = {}, []
    for k in _KEYS[op]:
        if k in _CAP and inp.get(k) is not None:
            out[k] = str(inp[k])[:_CAP[k]]
    if op == "amend":
        out["changes"], warn = _norm_changes(inp.get("changes"))
        out["appendix_changes"] = _norm_appx(inp.get("appendix_changes"))
    if "references" in _KEYS[op]:
        refs = _refs_in(inp.get("references"))
        if refs:
            out["references"] = refs
    return out, warn


def make_token(op, inp):
    """내려받기 링크에 담을 요청 — 서버에 저장하지 않고 링크 자체에 담는다(서버리스에서도 된다). MCP_TOKEN 이 있으면 서명한다."""
    raw = base64.urlsafe_b64encode(zlib.compress(json.dumps([op, inp], ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)).decode().rstrip("=")
    if _secret():
        raw += "." + base64.urlsafe_b64encode(hmac.new(_secret().encode(), raw.encode(), hashlib.sha256).digest()[:18]).decode()
    return raw


MAX_TOKEN_DATA = 160_000                                # 링크 안 요청(압축을 푼 크기) 상한 — 도구 입력 상한의 합보다 조금 크게


def read_token(tok):
    """링크 토큰 → (op, inp). 잘못됐으면 ValueError, 서명이 맞지 않으면 PermissionError. 입력은 도구 호출과 같은 규칙으로 다시 정리한다."""
    tok = str(tok or "")
    if len(tok) > MAX_LINK * 2:
        raise ValueError("링크가 너무 깁니다.")
    raw, _, sig = tok.partition(".")
    if _secret():
        want = base64.urlsafe_b64encode(hmac.new(_secret().encode(), raw.encode(), hashlib.sha256).digest()[:18])
        if not sig or not sig.isascii() or not hmac.compare_digest(sig.encode(), want):
            raise PermissionError("서명이 맞지 않는 링크입니다.")
    try:
        z = zlib.decompressobj()
        data = z.decompress(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), MAX_TOKEN_DATA)
        if z.unconsumed_tail:
            raise ValueError
        op, inp = json.loads(data.decode("utf-8"))
        inp, _ = clean_input(op, inp)
    except Exception:
        raise ValueError("링크를 읽지 못했습니다.")
    return op, inp


def doc_file(op, inp, fmt):
    """링크로 받은 요청을 다시 실행해 문서 세트 파일을 만든다 → (bytes, 파일 이름, 오류)."""
    res = engine.run(op, {**inp, "docs": True}, timeout=engine.HTTP_TIMEOUT)
    doc = res.get("doc") if isinstance(res, dict) else None
    if not doc:
        return None, "", (res or {}).get("error") or "이 요청으로는 만들 문서가 없습니다(바뀐 조문 없음)."
    data, err = _doc_bytes(doc, fmt)
    return data, re.sub(r'[\\/:*?"<>|]', "_", doc["filename"]) + "." + fmt, err


def _with_docs(op, inp, out_dir, fmt, documents):
    """엔진 실행 + 문서: stdio 는 output_dir 에 파일로, http 는 내려받기 링크로."""
    fmt = _fmt(fmt)
    inp, warn = clean_input(op, inp)
    if op == "amend" and not inp["changes"] and not inp["appendix_changes"]:
        return {"error": "changes 에 고칠 조문을 하나 이상 주세요(예: [{\"article\": \"제15조\", \"body\": \"…\"}]).", "warnings": warn}
    if _mode() == "http":
        res = engine.run(op, inp, timeout=engine.HTTP_TIMEOUT)
        if warn:
            res["warnings"] = warn + list(res.get("warnings") or [])
        if documents is not False and not res.get("error") and res.get("doc_ready"):
            tok = make_token(op, inp)
            if len(tok) <= MAX_LINK and _base_url():
                res["download"] = {"hwpx": f"{_base_url()}/api/mcp/doc/hwpx/{tok}", "docx": f"{_base_url()}/api/mcp/doc/docx/{tok}",
                                   "note": "심의안건서·개정문·신구조문대비표·이유서 등 문서 세트. 링크를 열면 그때 만들어 내려받는다."}
            else:
                res["download"] = {"note": "요청이 길어 내려받기 링크를 만들지 못했습니다. 웹 화면에서 같은 작업을 하고 ‘문서 받기’를 쓰세요."}
        return res
    res = engine.run(op, {**inp, "docs": bool(out_dir)})
    if warn:
        res["warnings"] = warn + list(res.get("warnings") or [])
    doc = res.pop("doc", None) if isinstance(res, dict) else None
    if out_dir and doc:
        res["saved"] = _save(doc, out_dir, fmt)
    return res


def t_run_agent(request, output_dir="", format="hwpx", documents=True):
    return _with_docs("agent", {"request": request}, output_dir, format, documents)


def t_amend_regulation(regulation, changes, appendix_changes=None, addenda="", reason="", effective="", references=None,
                       output_dir="", format="hwpx", documents=True):
    r, cand = _find(regulation)
    if not r:
        return _not_found(regulation, cand)
    inp = {"slug": r["slug"], "changes": changes, "appendix_changes": appendix_changes, "addenda": addenda, "reason": reason, "effective": effective,
           "references": references}
    return _with_docs("amend", inp, output_dir, format, documents)


def t_enact_regulation(title, text, purpose="", addenda="", effective="", references=None, output_dir="", format="hwpx", documents=True):
    if not str(text or "").strip():
        return {"error": "text 에 내규안 조문 전체(제1조(목적) …)를 주세요."}
    if len(str(text)) > _CAP["text"]:
        return {"error": f"내규안이 너무 깁니다({len(str(text)):,}자). {_CAP['text']:,}자 이하로 나눠 점검하세요."}
    inp = {"title": title, "text": text, "purpose": purpose, "addenda": addenda, "effective": effective, "references": references}
    return _with_docs("enact", inp, output_dir, format, documents)


# ── 도구 목록 ─────────────────────────────────────────────────────────────────
_STR = {"type": "string"}
_ARTS = {"type": "array", "items": _STR}
_SAVE = {"output_dir": {"type": "string", "description": "문서 세트(심의안건서·개정문·신구조문대비표·이유서 등)를 저장할 폴더. 비우면 저장하지 않는다."},
         "format": {"type": "string", "enum": ["hwpx", "docx"], "description": "저장 형식: 한글(hwpx, 기본) 또는 Word(docx)"}}
_LINK = {"documents": {"type": "boolean", "description": "문서 세트(한글·Word) 내려받기 링크를 함께 줄지(기본 true)"}}
_REFS = {"references": {"type": "array", "description": "참고한 다른 기관 조문(alio_get_regulation 결과에서). 검토 보고서 ‘자료조사 결과’와 심의 사전검토 ‘다른 공공기관 운영 사례’에 들어간다",
                        "items": {"type": "object", "properties": {"agency": {"type": "string", "description": "기관명"}, "regulation": {"type": "string", "description": "규정명"},
                                                                   "article": {"type": "string", "description": "조(예: 제5조)"}, "title": {"type": "string", "description": "조 제목"},
                                                                   "body": {"type": "string", "description": "조문(선택)"}}, "required": ["agency", "regulation"]}}}

TOOLS = [
    ("run_agent", "에이전트 실행(한 문장 요청)", t_run_agent,
     "한 문장 요청을 웹 화면의 에이전트와 똑같이 끝까지 처리한다(AI 없이 규칙 기반). 예: “여비규정 제15조의 일비를 3만원으로 올려줘”(개정), "
     "“여비규정 제20조를 삭제해줘”, “모든 내규에서 기획운영본부를 경영기획본부로 바꿔줘”(일괄 정비), “업무용 드론 운영지침을 새로 만들어줘”(제정 — 다른 기관(알리오) 같은 종류 규정을 찾아 조 구성을 참고), "
     "“다른 기관은 재택근무를 어떻게 규정했어?”(다른 기관 사례 — 알리오), 내규 질의(자문). "
     "단계별 작업 내역과 결론, 개정이면 개정문·신구조문대비표·개정문 검증, 제정이면 조문 초안, 다른 기관 사례면 찾은 규정과 관련 조문을 돌려준다. 자유로운 문장 수정은 amend_regulation 을 쓴다.",
     {"type": "object", "properties": {"request": {"type": "string", "description": "하고 싶은 일을 한 문장으로"}, **_SAVE, **_LINK}, "required": ["request"]}),
    ("amend_regulation", "개정안 → 개정문·대비표·검증", t_amend_regulation,
     "고친 조문(전문)을 받아 개정문(“○○ 일부를 다음과 같이 개정한다.”), 신구조문대비표, 개정문 검증(개정문을 현행에 다시 적용해 수정안과 같은지), "
     "조문 점검(인용 오류·항 번호·표기), 인용 영향(이 조를 인용하는 다른 조·내규)을 돌려준다. 먼저 get_regulation 으로 현행 조문을 읽고, 바꿀 조의 본문 전체를 적는다.",
     {"type": "object", "properties": {
         "regulation": {"type": "string", "description": "내규명(예: 여비규정)"},
         "changes": {"type": "array", "description": "고칠 조문들", "items": {"type": "object", "properties": {
             "article": {"type": "string", "description": "조 번호(예: 제15조, 15, 3의2)"},
             "type": {"type": "string", "enum": ["modify", "insert", "delete"], "description": "개정(기본)·신설·삭제"},
             "title": {"type": "string", "description": "조 제목(비우면 현행 제목)"},
             "body": {"type": "string", "description": "고친 뒤의 조 본문 전체(항은 ①② 등으로 줄을 나눈다). 삭제면 비운다."}},
             "required": ["article"]}},
         "appendix_changes": {"type": "array", "description": "고칠 별표(선택)", "items": {"type": "object", "properties": {
             "id": {"type": "string", "description": "예: 별표 2"}, "head": _STR, "body": {"type": "string", "description": "고친 뒤의 별표 본문 전체"}}, "required": ["id", "body"]}},
         "addenda": {"type": "string", "description": "부칙 문장(선택, 비우면 “이 규정은 발령한 날부터 시행한다.”)"},
         "reason": {"type": "string", "description": "개정 이유(선택, 이유서·검토 보고서에 씀)"},
         "effective": {"type": "string", "description": "시행일(선택, 예: 2027. 1. 1.)"},
         **_REFS, **_SAVE, **_LINK}, "required": ["regulation", "changes"]}),
    ("enact_regulation", "제정안 → 점검·사전검토·문서", t_enact_regulation,
     "새 내규안(AI 가 다른 기관 사례 등을 참고해 쓴 조문 전체)을 받아 조문 점검(인용 오류·항 번호·표기), 심의 사전검토(기관 심의기준), 제정 문서 세트(검토 보고서·내규안·제정 이유서·사전예고문 등)를 만든다. "
     "다른 기관 조문을 참고했으면 references 로 넘겨 근거로 남긴다. 처음부터 규칙으로 초안을 만들려면 run_agent(“○○ 지침을 새로 만들어줘”)를 쓴다.",
     {"type": "object", "properties": {
         "title": {"type": "string", "description": "만들 내규명(예: 업무용 드론 운영지침)"},
         "text": {"type": "string", "description": "내규안 조문 전체(제1조(목적) … 형식, 항은 ①②로 줄을 나눈다)"},
         "purpose": {"type": "string", "description": "제정 이유(선택, ~하려는 것임 체)"},
         "addenda": {"type": "string", "description": "부칙(선택, 비우면 시행일 조만)"},
         "effective": {"type": "string", "description": "시행일(선택)"},
         **_REFS, **_SAVE, **_LINK}, "required": ["title", "text"]}),
    ("search_regulations", "내규 검색", t_search_regulations,
     "낱말로 내규 조문을 찾는다. 낱말이 많이 나온 내규 순으로 조 번호·제목·발췌를 돌려준다.",
     {"type": "object", "properties": {"query": {"type": "string", "description": "찾을 낱말(예: 일비, 연차휴가)"}, "limit": {"type": "integer", "description": "최대 내규 수(기본 10)"}}, "required": ["query"]}),
    ("list_regulations", "내규 목록", t_list_regulations, "등록된 내규 전체 목록(이름·종류·개정 표기·조 수).",
     {"type": "object", "properties": {"category": {"type": "string", "description": "종류만 고르기(정관·규정·규칙·지침 등, 선택)"}}}),
    ("get_regulation", "내규 조문 읽기", t_get_regulation,
     "내규의 조문 원문(전체 또는 고른 조)과 별표 목록. 금액·일수는 별표에 있을 수 있으니 include_appendix 나 appendices 로 별표 본문도 읽는다.",
     {"type": "object", "properties": {"regulation": {"type": "string", "description": "내규명(일부만 적어도 됨)"},
                                       "articles": {"type": "array", "items": _STR, "description": "읽을 조(예: [\"제15조\", \"16\"]), 비우면 전체"},
                                       "include_appendix": {"type": "boolean", "description": "별표 본문 전체도 함께"},
                                       "appendices": {"type": "array", "items": _STR, "description": "본문을 읽을 별표만(예: [\"별표 2\"])"}}, "required": ["regulation"]}),
    ("check_regulation", "조문 점검", t_check_regulation,
     "내규 하나(또는 붙여 넣은 조문 글)의 형식 오류를 점검한다: 없는·삭제된 조문 인용, 항·호 번호, 현행 목록에 없는 내규명, 옛 명칭, 표기.",
     {"type": "object", "properties": {"regulation": {"type": "string", "description": "점검할 내규명"}, "text": {"type": "string", "description": "또는 점검할 조문 글(제1조(목적) …)"},
                                       "title": {"type": "string", "description": "text 의 내규명(선택)"}}}),
    ("health_check", "내규 건강검진", t_health_check, "기관 내규 전체를 진단해 평균 점수·등급 분포·문제가 있는 내규 수와 점수가 낮은 내규(이유 포함)를 돌려준다.",
     {"type": "object", "properties": {"top": {"type": "integer", "description": "점수가 낮은 내규 몇 개를 보일지(기본 10)"}}}),
    ("citation_impact", "인용 영향", t_citation_impact, "어떤 조를 고치거나 지울 때 그 조를 인용하는 같은 내규의 조·다른 내규·별표를 찾는다.",
     {"type": "object", "properties": {"regulation": _STR, "articles": {"type": "array", "items": _STR, "description": "고칠 조(예: [\"제20조\"])"}}, "required": ["regulation", "articles"]}),
    ("upper_law_impact", "상위법 개정 영향", t_upper_law_impact, "상위법(법령) 개정 시 그 법을 인용하는 내규 조문 후보를 찾는다. 개정 전·후 조문을 주면 사라진 용어도 짚는다.",
     {"type": "object", "properties": {"law": {"type": "string", "description": "법령명(예: 공공기관의 운영에 관한 법률)"}, "articles": _ARTS,
                                       "old_text": {"type": "string", "description": "개정 전 조문(선택)"}, "new_text": {"type": "string", "description": "개정 후 조문(선택)"}}, "required": ["law"]}),
    ("bulk_rename", "일괄 정비(명칭 변경)", t_bulk_rename, "모든 내규에서 용어·조직 명칭을 찾아 바꾸는 정비안: 내규별 개정문과 바뀌는 위치(조사 자동 교정, 별표·서식 포함).",
     {"type": "object", "properties": {"old": {"type": "string", "description": "바꿀 말"}, "new": {"type": "string", "description": "새 말"}}, "required": ["old", "new"]}),
    ("advise", "내규 자문", t_advise, "내규 질의에 근거 조문을 찾아 회신 초안을 만든다(AI 없이 근거 조문 중심).",
     {"type": "object", "properties": {"question": _STR, "regulation": {"type": "string", "description": "특정 내규로 좁히기(선택)"}}, "required": ["question"]}),
    ("alio_search_regulations", "다른 기관 규정 찾기(알리오)", t_alio_search,
     "다른 공공기관이 알리오(공공기관 경영정보 공개시스템)에 공시한 내부규정을 규정명으로 찾는다. 기본은 유관 기관(같은 주무부처 등). "
     "결과의 id 를 alio_get_regulation 에 넣으면 그 규정의 현행본 조문을 읽는다. 제정·개정 때 다른 기관은 어떻게 정했는지 볼 때 쓴다.",
     {"type": "object", "properties": {"keyword": {"type": "string", "description": "규정명 검색어(예: 여비, 드론, 재택근무, 직장 내 괴롭힘)"},
                                       "scope": {"type": "string", "enum": list(ALIO_SCOPES), "description": "peer: 유관 기관(기본), type: 우리와 같은 기관 유형, all: 전체 공공기관(앞의 48곳까지)"},
                                       "agencies": {"type": "array", "items": _STR, "description": "기관명이나 알리오 기관 ID 로 직접 고르기(예: [\"한국농어촌공사\"]). 주면 scope 는 무시"},
                                       "category": {"type": "string", "description": "분류(선택): 인사·복무·징계, 보수, 직제, 기타, 정관"},
                                       "include_old": {"type": "boolean", "description": "옛 판(같은 이름의 이전 공시)도 보일지(기본 false)"},
                                       "limit": {"type": "integer", "description": "최대 결과 수(기본 30)"}}, "required": ["keyword"]}),
    ("alio_get_regulation", "다른 기관 규정 읽기(알리오)", t_alio_get_regulation,
     "alio_search_regulations 결과의 id 로 그 기관 규정의 현행본(가장 최근 공시 파일)을 받아 조문을 준다. query(주제·질문)를 주면 관련 조문이 먼저 오고, articles 로 조를 고르면 그 조의 전문을 준다. "
     "목차(toc)와 알리오 원문 링크(url)도 준다. 인용할 때는 기관명·규정명·조를 밝힌다.",
     {"type": "object", "properties": {"id": {"type": "string", "description": "alio_search_regulations 결과의 id"},
                                       "query": {"type": "string", "description": "관련 조문을 먼저 볼 주제·질문(예: 비행 승인, 숙박비 상한)"},
                                       "articles": {"type": "array", "items": _STR, "description": "전문을 읽을 조(예: [\"제5조\", \"7\"])"},
                                       "limit": {"type": "integer", "description": "관련 순으로 보일 조문 수(기본 12, 최대 80)"}}, "required": ["id"]}),
    ("alio_compare_values", "다른 기관 수치 비교(알리오)", t_alio_compare_values,
     "유관 기관 사규에서 같은 항목의 금액·일수 등을 뽑아 우리 기관 값과 견준다(예: 여비 규정의 일비 원, 복무 규정의 경조휴가 일). "
     "기관별 값·원문 문장·조와 최솟값·최댓값·중앙값을 준다. 개정안의 수치를 정할 근거로 쓰되, 원문 문장을 보고 같은 기준인지 확인한다.",
     {"type": "object", "properties": {"item": {"type": "string", "description": "비교할 항목(예: 일비, 숙박비, 경조휴가, 당직비)"},
                                       "unit": {"type": "string", "enum": list(_UNITS), "description": "단위"},
                                       "keyword": {"type": "string", "description": "찾을 규정명(예: 여비, 복무, 보수)"},
                                       "scope": {"type": "string", "enum": list(ALIO_SCOPES), "description": "peer(기본)·type·all"},
                                       "agencies": {"type": "array", "items": _STR, "description": "기관을 직접 고르기(선택)"},
                                       "max_agencies": {"type": "integer", "description": "규정을 열어 볼 기관 수(기본 15, 최대 30)"}}, "required": ["item", "unit", "keyword"]}),
    ("search", "검색(커넥터 규격)", t_search,
     "내규 조문 검색 — ChatGPT 커넥터·심층 리서치 규격. 결과의 id 를 fetch 에 넣으면 원문을 준다. 일반 대화에서는 search_regulations 가 더 자세하다.",
     {"type": "object", "properties": {"query": {"type": "string", "description": "찾을 말(예: 출장 일비)"}}, "required": ["query"]}),
    ("fetch", "원문 가져오기(커넥터 규격)", t_fetch,
     "search 결과의 id(예: 여비규정#제15조, 여비규정#별표 2, 여비규정)로 조문·별표·내규 전문을 가져온다 — ChatGPT 커넥터·심층 리서치 규격.",
     {"type": "object", "properties": {"id": {"type": "string", "description": "search 결과의 id"}}, "required": ["id"]}),
]
_BY = {t[0]: t for t in TOOLS}
_ENGINE_TOOLS = ("run_agent", "amend_regulation", "enact_regulation")
_ALIO_TOOLS = ("alio_search_regulations", "alio_get_regulation", "alio_compare_values")


def _schema(name, schema):
    """연결 방식에 맞는 입력 형식: 원격(http)은 파일 저장(output_dir·format) 대신 내려받기 링크(documents)."""
    if name not in _ENGINE_TOOLS:
        return schema
    props = dict(schema["properties"])
    for k in (("output_dir", "format") if _mode() == "http" else ("documents",)):
        props.pop(k, None)
    return {**schema, "properties": props}


def tool_list():
    out = []
    for n, ti, _, desc, schema in TOOLS:
        writes = _mode() == "stdio" and n in _ENGINE_TOOLS              # stdio 에서 output_dir 를 주면 파일을 쓴다
        out.append({"name": n, "title": ti, "description": desc, "inputSchema": _schema(n, schema),
                    "annotations": {"title": ti, "readOnlyHint": not writes, "destructiveHint": False, "idempotentHint": True,
                                    "openWorldHint": n == "run_agent" or n in _ALIO_TOOLS}})
    return out


def _call(name, args):
    t = _BY.get(name)
    if not t:
        return {"content": [{"type": "text", "text": f"모르는 도구: {name}"}], "isError": True}
    props = _schema(name, t[4]).get("properties", {})
    args = {k: v for k, v in (args or {}).items() if k in props}      # 형식에 없는 값은 버린다(연결 방식에 없는 output_dir 등)
    try:
        res = t[2](**args)
    except TypeError as e:
        miss = [k for k in t[4].get("required", []) if k not in args]
        msg = f"필수 입력이 빠졌습니다: {', '.join(miss)}" if miss else f"입력값이 맞지 않습니다: {e}"
        return {"content": [{"type": "text", "text": msg}], "isError": True}
    except Exception as e:  # 도구 오류는 프로토콜 오류가 아니라 결과로 알린다(AI 가 읽고 다시 시도)
        return {"content": [{"type": "text", "text": f"처리 중 오류: {type(e).__name__}: {e}"}], "isError": True}
    err = isinstance(res, dict) and bool(res.get("error")) and len(res) <= 3
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n…(길어서 잘랐습니다)"
    out = {"content": [{"type": "text", "text": text}], "isError": err}
    if isinstance(res, dict):
        out["structuredContent"] = res
    return out


def _instructions():
    s = ("이 서버는 기관 내규(규정·규칙·지침)의 제·개정을 돕는 ‘규정 제·개정 에이전트’입니다. "
         "답에는 근거를 「내규명」 제N조 형태로 밝히고, 금액·기한은 조문·별표 원문에서 확인한 값만 쓰세요. "
         "개정은 ① get_regulation 으로 현행 조문을 읽고 ② 고친 조문 전문을 amend_regulation 에 넣어 개정문·신구조문대비표·개정문 검증·조문 점검·인용 영향을 받으세요. "
         "한 문장 요청(예: “여비규정 제15조의 일비를 3만원으로 올려줘”)은 run_agent 가 규칙으로 끝까지 처리합니다. "
         "다른 공공기관 사례가 필요하면 alio_search_regulations → alio_get_regulation 으로 알리오 공시 규정을 읽고, 수치는 alio_compare_values 로 견주세요. "
         "참고한 다른 기관 조문은 amend_regulation·enact_regulation 의 references 로 넘기면 검토 보고서·심의 사전검토의 근거로 남습니다(기관명·규정명·조를 밝혀 인용). "
         "검증 결과(verification.ok=false)나 점검 오류가 있으면 사용자에게 그대로 알리세요.")
    if _mode() == "http":
        s += " 결과에 download 링크가 있으면 사용자에게 한글(hwpx)·Word(docx) 문서 세트 내려받기 링크로 보여 주세요. 원문 링크(url)도 함께 주세요."
    return s


def handle(msg, mode="stdio", base=""):
    """JSON-RPC 메시지 하나 → 응답(알림·클라이언트 응답이면 None). mode: stdio|http, base: 원격일 때 이 서버의 공개 주소."""
    tok = _CTX.set({"mode": mode, "base": base})
    try:
        return _handle(msg)
    finally:
        _CTX.reset(tok)


def _handle(msg):
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params")
    if method is None:                               # 클라이언트가 보낸 응답(result·error) — 답하지 않는다
        if "id" in msg and ("result" in msg or "error" in msg):
            return None
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32600, "message": "Invalid Request"}}
    if "id" not in msg:                              # 알림(notifications/initialized 등)에는 답하지 않는다
        return None
    if not isinstance(method, str) or not (mid is None or isinstance(mid, (str, int))) or isinstance(mid, bool):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Invalid params"}}
    if method == "initialize":
        want = params.get("protocolVersion")
        res = {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0], "capabilities": {"tools": {"listChanged": False}},
               "serverInfo": {"name": "reg-agent", "title": "규정 제·개정 에이전트", "version": VERSION}, "instructions": _instructions()}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": tool_list()}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments")
        if not isinstance(name, str) or not (args is None or isinstance(args, dict)):
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Invalid params: name(문자열)과 arguments(객체)가 필요합니다."}}
        res = _call(name, args)
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}
