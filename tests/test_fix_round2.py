"""11/8 남은 높음 4건(기능점검.md) 회귀 시험 — 상위법 문장 판정, 별칭·나열 인용, 일괄 정비 별표, 좁은 화면 메뉴."""
import os
import re


def test_law_article_change_is_upper(ra):
    # HLT-1: “○○법 제N조가 개정됐어” — 내규명을 적지 않았으면 상위법 영향(엉뚱한 내규의 같은 번호 조가 아님)
    for q, law in (("청탁금지법 제10조가 개정됐어", "청탁금지법"), ("근로기준법 제60조가 바뀌었어", "근로기준법"),
                   ("근로기준법 제60조 개정에 따라 고칠 내규 찾아줘", "근로기준법"), ("개인정보 보호법 제15조가 바뀌었어", "개인정보 보호법"),
                   ("공운법 제31조가 개정됐어", "공운법"), ("상위법 근로기준법 제60조 개정", "근로기준법"),
                   ("산업안전보건법 시행령 제5조가 개정됐어", "산업안전보건법 시행령")):
        p = ra.heuristic_plan(q)
        assert p["mode"] == "upper" and p["law"] == law, (q, p)
    assert ra.heuristic_plan("청탁금지법 제10조가 개정됐어")["arts"] == ["제10조"]
    # 내규 조를 고치라는 요청·내규 개정은 그대로
    for q in ("근로기준법 개정에 맞춰 복무규정 제14조를 고쳐줘", "여비규정 제15조의 일비를 3만원으로 올려줘", "인사규정 제60조를 개정해줘"):
        assert ra.heuristic_plan(q)["mode"] == "amend", q


def test_alias_and_list_citations(ra, client):
    # GAP-2: 나열 인용 “「직제규정」 제3조, 제4조, 제6조”
    assert [x[0] for x in ra.external_reg_refs("「직제규정」 제3조, 제4조, 제6조에 의한", "직제규정")] == ["3", "4", "6"]
    assert [x[0] for x in ra.external_reg_refs("「직제규정」 제3조부터 제5조까지", "직제규정")] == ["3", "4", "5"]
    # 「인사규정 시행세칙」 안의 ‘인사규정’은 「인사규정」 인용이 아니다
    assert ra.external_reg_refs("「인사규정 시행세칙」 제3조", "인사규정") == []
    # HLT-3: 시행세칙의 별칭 인용 “규정 제32조” = 「인사규정」 제32조
    assert ra._reg_aliases("인사규정 시행세칙", []) == {"규정": "인사규정"}
    assert ra._reg_aliases("감사규정 시행세칙", ["① 「감사규정」(이하 “규정”이라 한다)"]) == {"규정": "감사규정"}
    refs = ra.alias_refs("규정 제32조에 따라 하고 이 규정 제5조와 같은 규정 제7조는 제외", {"규정": "인사규정"})
    assert [(p, n) for p, n, _, _ in refs] == [("인사규정", "32")]
    d = client.post("/api/regagent/impact", json={"slug": "인사규정", "nos": ["32", "34"]}).get_json()
    sub = [o for o in d["outer"] if o["reg"] == "인사규정 시행세칙"]
    assert sub and "21" in [h["no"] for h in sub[0]["hits"]]
    assert len({(h["no"], h["cites"]) for h in sub[0]["hits"]}) == len(sub[0]["hits"])        # 같은 조의 같은 인용은 한 번만
    d = client.post("/api/regagent/impact", json={"slug": "감사규정", "nos": ["23"]}).get_json()
    assert any(o["reg"] == "감사규정 시행세칙" and any(h["no"] == "49" for h in o["hits"]) for o in d["outer"])
    # 점검: 하위 내규가 상위 내규에 없는 조를 별칭으로 인용하면 짚는다(원문 그대로는 오류 없음)
    r = ra.find_reg("", "인사규정 시행세칙")
    arts = [dict(a) for a in r["articles"]]
    assert not [i for i in ra.lint_articles(arts, r["addenda"], r["appendix"], r["title"]) if i["code"] == "xref"]
    arts[0]["body"] += " 규정 제300조에 따른다."
    iss = [i for i in ra.lint_articles(arts, r["addenda"], r["appendix"], r["title"]) if i["code"] == "xref"]
    assert iss and "인사규정" in iss[0]["msg"] and "제300조" in iss[0]["msg"]
    # HLT-2: 인용 관계 그래프 — 시행세칙 → 모법, 「감사규정」은 ‘영향 없음’이 아니다
    g = ra.citation_graph()
    t = {n["title"]: i for i, n in enumerate(g["nodes"])}
    es = {(e["s"], e["t"]) for e in g["edges"]}
    for child, parent in (("인사규정 시행세칙", "인사규정"), ("감사규정 시행세칙", "감사규정"), ("재무회계규정 시행세칙", "재무회계규정")):
        assert (t[child], t[parent]) in es, (child, parent)


def test_bulk_includes_appendix(client):
    # LKP-1: 일괄 정비가 별표·서식도 본다(정원표·분장업무·회계책임자 표)
    d = client.post("/api/regagent/bulk", json={"old": "기획조정실", "new": "경영기획실"}).get_json()
    g = next(x for x in d["regs"] if x["reg"] == "직제규정 시행세칙")
    assert g["appx"] and sum(x["count"] for x in g["appx"]) >= 9
    assert "별표 6 중 “기획조정실”을 각각 “경영기획실”로 한다." in g["amend_text"]
    assert any(x["reg"] == "재무회계규정 시행세칙" and not x["articles"] and x["appx"] for x in d["regs"])   # 별표에만 있는 내규도
    d = client.post("/api/regagent/bulk", json={"old": "기획운영본부", "new": "경영기획본부"}).get_json()
    assert d["reg_count"] == 25 and d["total"] == 35


def test_narrow_screen_menu_is_one_row():
    # UX-1: 좁은 화면에서 메뉴 묶음을 풀어 한 줄로(묶음 머리·소제목 숨김, 접힌 묶음도 보임)
    css = open(os.path.join(os.path.dirname(__file__), "..", "assets", "reg_agent.css"), encoding="utf-8").read()
    m = re.search(r"@media \(max-width:1023px\)\{\s*\.ra-nav \.ra-nav-g,\.ra-nav \.ra-nav-gb,\.ra-nav \.ra-nav-g\.fold \.ra-nav-gb\{display:contents;\}", css)
    assert m and ".ra-nav .ra-nav-gh,.ra-nav .ra-nav-sub{display:none;}" in css


def test_review_regressions_round2(ra, client):
    import time
    # 시행규칙 제N조는 법령 — 내규 고치기로 보지 않는다
    for q, law in (("근로기준법 시행규칙 제9조 개정", "근로기준법 시행규칙"), ("산업안전보건법 시행규칙 제5조 개정에 따라 고칠 내규 찾아줘", "산업안전보건법 시행규칙")):
        p = ra.heuristic_plan(q)
        assert p["mode"] == "upper" and p["law"] == law and p["arts"] == [re.search(r"제\d+조", q).group(0)], (q, p)
    # ‘지급방법’·‘평가방법’은 법령명이 아니다
    for q in ("출장비 지급방법 제3조를 개정해줘", "평가방법 제3조가 바뀌었어", "징계 처리방법 제5조 변경"):
        assert ra.heuristic_plan(q)["mode"] == "amend", q
    # 법령 조 개정 + 내규 조문 고치기·수치 변경이 함께 있으면 개정
    for q in ("청탁금지법 제10조 개정에 따라 행동강령 제15조를 고쳐줘", "근로기준법 제60조 개정에 따라 연차휴가 일수를 15일에서 16일로 늘려줘"):
        assert ra.heuristic_plan(q)["mode"] == "amend", q
    # 긴 입력에서도 빠르게
    t = time.time(); ra.heuristic_plan("가" * 40000 + " 개정"); assert time.time() - t < 2
    # 「제목(주석)」·「제목(이하 …)」 꼴 인용
    assert ra.external_reg_refs("「보안업무규칙(내규)」 제2조에 의거", "보안업무규칙")[0][0] == "2"
    assert ra.external_reg_refs("「인사규정(이하 “규정”이라 한다)」제37조", "인사규정")[0][0] == "37"
    # 정부 규범명 꼬리는 우리 내규 별칭·그래프 간선이 아니다
    assert ra._reg_aliases("직원채용지침", ["공기업·준정부기관 계약사무규칙(이하 “규칙”이라 한다)에 따른다."]) == {}
    g = ra.citation_graph(); t_ = {n["title"]: i for i, n in enumerate(g["nodes"])}
    assert (t_["직원채용지침"], t_["계약사무규칙"]) not in {(e["s"], e["t"]) for e in g["edges"]}
    # 일괄 정비 별표: 별표 자리의 부칙 지시문·부칙 조각 블록·삭제된 서식은 고치지 않는다. 바뀐 줄만 보낸다
    d = client.post("/api/regagent/bulk", json={"old": "기획운영본부", "new": "경영기획본부"}).get_json()
    ax = {(g["reg"], x["id"]) for g in d["regs"] for x in g["appx"]}
    assert ("직제규정 시행세칙", "별지 3") not in ax and ("인사규정 시행세칙", "별표 3") not in ax
    assert ("직제규정 시행세칙", "별표 3") in ax and ("직제규정 시행세칙", "별표 4") in ax
    x = next(x for g in d["regs"] for x in g["appx"] if x["id"] == "별표 4" and g["reg"] == "직제규정 시행세칙")
    assert x["lines"] and all("경영기획본부" in b and "기획운영본부" in a for a, b in x["lines"]) and "old_body" not in x
    d = client.post("/api/regagent/bulk", json={"old": "농업기술실용화재단", "new": "한국농업기술진흥원"}).get_json()
    assert not any(g["reg"] == "내규관리규칙" and any(x["id"] == "별지 제10호 서식" for x in g["appx"]) for g in d["regs"])
