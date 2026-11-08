"""11/8 1차 수정(기능점검.md 높음 등급) 회귀 시험 — 서버 쪽 요청 해석."""


def test_arrow_with_reg_or_number_is_amend_not_bulk(ra):
    # AG-3: 내규명·조를 적은 화살표 요청은 그 내규의 개정이다(모든 내규 일괄 정비가 아님)
    p = ra.heuristic_plan("여비규정 제8조 정산 기한 14일 → 30일")
    assert p["mode"] == "amend"
    # AGENT-V1: 쉼표 금액은 숫자 가운데를 잘라 “000원”→“30” 정비를 만들지 않는다
    p = ra.heuristic_plan("여비규정의 일비 25,000원→30,000원")
    assert p["mode"] == "amend"
    p = ra.heuristic_plan("숙박비 상한 100,000 → 120,000")
    assert p["mode"] != "bulk"
    # 내규명 없이 명칭만 바꾸는 화살표는 여전히 일괄 정비
    p = ra.heuristic_plan("기획운영본부 → 경영기획본부")
    assert p["mode"] == "bulk" and p["old"] == "기획운영본부" and p["new"] == "경영기획본부"
    # 내규명이 있는 낱말 화살표는 그 내규의 낱말 바꾸기 의도로 고쳐 쓴다
    p = ra.heuristic_plan("여비규정에서 여비 → 출장비")
    assert p["mode"] == "amend" and "“여비”을 “출장비”로 바꿔" in p["intent"]


def test_possessive_ui_is_not_branch_article(ra):
    # AG-5: “제8조의 14일”·“제17조의 2만원”·“제8조의 2항”은 제8조·제17조다
    import re
    f = lambda t: [re.sub(r"\s+", "", x) for x in re.findall(ra._REQ_ART, t)]
    assert f("제8조의 14일을 30일로") == ["제8조"]
    assert f("제17조의 2만원을 3만원으로") == ["제17조"]
    assert f("제8조의 2항을 고쳐") == ["제8조"]
    assert f("제8조의2를 삭제") == ["제8조의2"]
    assert f("제15조의2제1항") == ["제15조의2"]
    plan = {"mode": "amend", "intent": "", "reasoning": []}
    ra._resolve_targets(plan, "여비규정 제17조의 근무지내 출장 여비 2만원을 3만원으로 올려줘")
    assert plan["reg"]["title"] == "여비규정"
    assert [a["no"] for a in plan["articles"]] == ["17"] and not plan.get("missing")


def test_retarget_skips_law_article_lists(ra):
    # AMD-1: 서버 쪽도 같은 판정 — 다른 법률 조의 나열은 바꾸지 않는다
    t = "「감염병의 예방 및 관리에 관한 법률」 제24조 및 제25조에 따른 예방접종, 같은 법 제 24조 또는 제25조에 따라"
    out, n = ra.retarget_refs(t, {"25": "26"})
    assert n == 0 and out == t
    out, n = ra.retarget_refs("제25조에 따라 신고한다.", {"25": "26"})
    assert n == 1 and out == "제26조에 따라 신고한다."


def test_advise_example_chips_and_colloquial_endings(client):
    # LKP-2: 화면 예시 칩 4개는 모두 ‘해당 규정’으로 답해야 한다(심사위원이 처음 누르는 질의)
    import re
    src = open("assets/reg_agent.js", encoding="utf-8").read()
    chips = re.findall(r"'([^']+)'", re.search(r"const RA_ADV_EX=\[(.*?)\];", src).group(1))
    assert len(chips) == 4
    for q in chips + ["명예퇴직수당 어떻게 계산해?", "임신한 직원 야간근무 가능한가요?", "CCTV 영상 보관 기간은?"]:
        d = client.post("/api/regagent/advise", json={"question": q}).get_json()
        assert d["conclusion"] == "해당 규정" and not d["gap"], (q, d["answer"][:120])
    d = client.post("/api/regagent/advise", json={"question": "CCTV 영상 보관 기간은?"}).get_json()
    assert "「CCTV 운영 지침」 제14조" in d["answer"]


def test_advise_query_strips_verb_endings(ra):
    toks = ra._adv_query("육아휴직 기간도 승진소요 최저 근무연수에 포함되나요?")[1]
    assert "포함" in toks and "포함되" not in toks
    toks = ra._adv_query("70만원 넘는 물품은 그럼 누가 결재하나요?")[1]
    assert "결재" in toks and not any(t.startswith("70") for t in toks) and "그럼" not in toks


def test_import_reset_refuses_default_data_without_force(tmp_path, monkeypatch, capsys):
    # UX-2: REG_DIR 없이 --reset 하면 저장소 기본 내규를 지우지 않고 멈춘다. --force 면 지우지 않고 백업 폴더로 옮긴다
    import importlib.util, json, os
    import reg_import as ri
    base = tmp_path / "repo"
    (base / "regulations" / "여비규정").mkdir(parents=True)
    (base / "regulations" / "여비규정" / "text.txt").write_text("제1조(목적) 가.", encoding="utf-8")
    (base / "regulations_manifest.json").write_text(json.dumps([{"title": "여비규정", "slug": "여비규정"}]), encoding="utf-8")
    monkeypatch.setattr(ri, "BASE_DIR", str(base))
    monkeypatch.setattr(ri, "REG_DIR", str(base / "regulations"))
    monkeypatch.setattr(ri, "REG_MANIFEST_PATH", str(base / "regulations_manifest.json"))
    spec = importlib.util.spec_from_file_location("imp", os.path.join(os.path.dirname(__file__), "..", "scripts", "import_regulations.py"))
    imp = importlib.util.module_from_spec(spec); spec.loader.exec_module(imp)
    src = os.path.join(os.path.dirname(__file__), "..", "samples", "public_org", "regs")
    assert imp.main([src, "--reset"]) == 3
    assert "멈춤" in capsys.readouterr().out
    assert (base / "regulations" / "여비규정" / "text.txt").exists()          # 그대로
    assert imp.main([src, "--reset", "--force"]) == 0
    baks = [p for p in os.listdir(base) if p.startswith("regulations.backup-")]
    assert len(baks) == 1 and (base / baks[0] / "여비규정" / "text.txt").exists()   # 지우지 않고 옮겨 둠
    assert any(p.startswith("regulations_manifest.json.backup-") for p in os.listdir(base))
    assert len(json.loads((base / "regulations_manifest.json").read_text(encoding="utf-8"))) == 7


def test_review_regressions_server(ra):
    import re
    f = lambda t: [re.sub(r"\s+", "", x) for x in re.findall(ra._REQ_ART, t)]
    assert f("사택관리규칙 제6조의3 일반사택 확보 조항 삭제") == ["제6조의3"]
    assert f("복무규정 시행세칙 제4조의2 시간외근무 수당") == ["제4조의2"]
    # 범위어·조직명 속 ‘정관·기준’은 내규명이 아니다 — 일괄 정비
    for q in ("전 규정에서 기획운영본부 → 경영기획본부", "각 규정의 기획운영본부 → 경영기획본부", "재정관리팀 → 경영관리팀"):
        p = ra.heuristic_plan(q)
        assert p["mode"] == "bulk", (q, p)
    p = ra.heuristic_plan("1.기획운영본부 → 경영기획본부")
    assert p["mode"] == "bulk" and p["old"] == "기획운영본부"
    # intent 고쳐 쓰기에 따옴표가 겹치지 않는다
    p = ra.heuristic_plan("여비규정의 ‘여비’→‘출장비’로 바꿔")
    assert p["mode"] == "amend" and "“여비”을 “출장비”로 바꿔" in p["intent"] and "““" not in p["intent"] and "‘“" not in p["intent"]
    # 서버 인용 정정 — “규정 제25조의 이행관리책임자는 제30조제3항”의 제30조는 같은 내규
    t = "② 규정 제25조의 이행관리책임자는 제30조제3항에 따라 분류된 사항을 관리한다."
    out, n = ra.retarget_refs(t, {"30": "31"})
    assert n == 1 and "제31조제3항" in out
    # 자문 어간 떼기는 명사(결재권한·신청기한·출입제한)를 자르지 않는다
    for q, keep in (("결재권한은 누구에게?", "결재권한"), ("출장 신청기한은?", "신청기한"), ("출입제한 구역은?", "출입제한")):
        assert keep in ra._adv_query(q)[1], q
    # 자문용 구어 동의어는 개정 대상 고르기(유사 검색)에 섞이지 않는다
    assert "보관" not in ra._SYN and "보유" in ra._ADV_SYN["보관"]
