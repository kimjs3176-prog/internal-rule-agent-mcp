"""엔진(reg_agent.py)·MCP 입력 정리(core.py) 다듬기 — 짧은 용어 치환, 본문 속 시행일 조·별표 인용, 캐시 열쇠, 날짜, 표 열 상한."""
import io
import os
import re
import zipfile


# 1. 짧은 용어 뒤 조사처럼 보이는 글자 + 한글이면 다른 낱말
def test_replace_term_short_word_not_split_by_particle(ra):
    assert ra.replace_term("부서이동을 한다", "부서", "팀")[0] == "부서이동을 한다"
    assert ra.replace_term("이사가족", "이사", "원장")[0] == "이사가족"
    assert ra.replace_term("이사회의", "이사", "원장")[0] == "이사회의"


def test_replace_term_short_word_particles_still_fixed(ra):
    assert ra.replace_term("부서를 부서는 부서가", "부서", "팀")[0] == "팀을 팀은 팀이"
    assert ra.replace_term("이사가 출석한다", "이사", "원장")[0] == "원장이 출석한다"
    assert ra.replace_term("부서와의 협의", "부서", "팀")[0] == "팀과의 협의"
    assert ra.replace_term("감사는 이사이며", "이사", "원장")[0] == "감사는 원장이며"


# 2. 본문 가운데의 ‘시행일’ 조
def test_parse_main_body_article_titled_effective_date(ra):
    p = ra.parse_text("제1조(목적) 목적.\n제2조(시행일) 직원 시행일 규정.\n제3조(정의) 정의.")
    assert [a["no"] for a in p["articles"]] == ["1", "2", "3"]
    assert p["addenda"] == ""


def test_parse_addenda_articles_still_detected(ra):
    p = ra.parse_text("제1조(목적) 목적.\n제10조(정의) 정의.\n제1조(시행일) 부칙.")
    assert [a["no"] for a in p["articles"]] == ["1", "10"]
    assert "시행일" in p["addenda"]
    p = ra.parse_text("제1조(목적) 목적.\n제2조(정의) 정의.\n제3조(시행일) 이 규정은 공포한 날부터 시행한다.")
    assert [a["no"] for a in p["articles"]] == ["1", "2"]          # 뒤에 본문 조가 없으면 부칙
    p = ra.parse_text("제1조(목적) 목적.\n제2조(정의) 정의.\n부칙\n제1조(시행일) 시행.\n제2조(경과조치) 경과.")
    assert [a["no"] for a in p["articles"]] == ["1", "2"]


# 3. 본문 줄 머리의 별표 인용
def test_parse_appendix_citation_line_is_not_header(ra):
    p = ra.parse_text("제1조(목적) 목적.\n[별표 1]을 참조한다\n제2조(정의) 정의.")
    assert [a["no"] for a in p["articles"]] == ["1", "2"]
    assert p["appendix"] == ""
    p = ra.parse_text("제1조(목적) 목적.\n부칙\n이 규정은 2020.1.1부터 시행한다.\n[별표 1] 수당표\n금액")
    assert p["appendix"].startswith("[별표 1] 수당표")
    p = ra.parse_text("제1조(목적) 목적.\n[별표 1]\n금액")
    assert p["appendix"].startswith("[별표 1]")


# 4. 캐시 열쇠: id(regs) 대신 세대 — 임시 목록·외부 요청([])은 공유 캐시를 쓰지 않는다
def test_cache_key_not_shared_with_temporary_lists(ra, monkeypatch):
    def mk(title, body):
        return {"slug": title, "title": title, "category": "", "revision": "", "chapters": [], "addenda": "", "appendix": "",
                "articles": [{"no": "1", "title": "정의", "body": body, "chapter": "", "deleted": False}]}
    a = [mk("가규정", "“갑용어”란 하나를 말한다.")]
    monkeypatch.setattr(ra, "all_regs", lambda: a)
    assert ra._regs_key(a) is None
    assert "갑용어" in ra.glossary()["terms"]
    b = [mk("나규정", "“을용어”란 둘을 말한다.")]
    monkeypatch.setattr(ra, "all_regs", lambda: b)
    g = ra.glossary()["terms"]
    assert "을용어" in g and "갑용어" not in g
    monkeypatch.setattr(ra, "all_regs", lambda: [])
    assert ra.glossary()["terms"] == {}
    assert ra.citation_graph()["stats"]["regs"] == 0


def test_cache_key_changes_on_registry_reload(ra):
    regs = ra.all_regs()
    k1 = ra._regs_key(regs)
    assert k1 is not None and k1[1] == len(regs)
    ra._REG_CACHE["key"] = object()                 # 매니페스트가 바뀐 것처럼 다시 읽게 한다
    regs2 = ra.all_regs()
    k2 = ra._regs_key(regs2)
    assert k2 is not None and k2 != k1
    assert ra._regs_key(regs) is None               # 지난 세대 목록은 열쇠가 없다
    hit, _ = ra._cache_get({"key": k1, "v": 1}, k2)
    assert not hit


# 5. 부칙 시행일의 ISO 날짜
def test_addenda_iso_date_checked(ra):
    iss = ra._addenda_date_issues("이 규정은 2027-02-30부터 시행한다.")
    assert iss and iss[0]["level"] == "error"
    assert ra._addenda_date_issues("이 규정은 2027.02.30부터 시행한다.")[0]["level"] == "error"
    assert ra._addenda_date_issues("이 규정은 2099-03-01부터 시행한다.") == []


# 6. 개정 표기의 달력에 없는 날짜
def test_rev_date_invalid_month(ra):
    assert ra.rev_date("2023년 13월 일부개정") == ""
    assert ra.rev_date("2023년도 7월 일부개정") == "20230701"


# 7. 표 열 상한(40) 밖의 칸
def test_norm_blocks_clamps_cells_past_col_cap(ra):
    rows = [[{"t": "a", "cs": 20}, {"t": "b", "cs": 20}, {"t": "c", "cs": 5}, {"t": "d"}], [{"t": "x"}]]
    t = ra._norm_blocks([{"t": "table", "rows": rows}])[0]
    assert t["ncol"] == 40
    for r in t["rows"]:
        assert r and r[-1]["col"] + r[-1]["cs"] == 40
        assert all(c["col"] + c["cs"] <= 40 for c in r)
    data = ra.build_hwpx([{"t": "table", "rows": rows}])
    sec = zipfile.ZipFile(io.BytesIO(data)).read("Contents/section0.xml").decode("utf-8")
    assert 'colCnt="40"' in sec
    assert not re.search(r'<hp:cellSz width="0"', sec)


# 8. 제1조의0
def test_branch_zero_article_flagged(ra):
    p = ra.parse_text("제1조의0(목적) 목적.")
    iss = ra.lint_articles(p["articles"])
    assert any(i["code"] == "branch0" and i["level"] == "error" for i in iss)


# 9. 짝 없는 서로게이트
def test_check_regulation_lone_surrogate():
    from mcp_server import core
    r = core.t_check_regulation(text="제1조(목적) 목적\ud800.", title="시험 규정", org={"org_name": "가"})
    assert "issues" in r
    assert core._scrub("가\ud800") == "가�"


# 10. 파일 이름의 제어 문자
def test_save_filename_strips_control_chars(tmp_path):
    from mcp_server import core
    r = core.t_enact_regulation(title="a\nb\tc", text="제1조(목적) 목적.\n제2조(정의) 정의.", org={"org_name": "가"},
                                output_dir=str(tmp_path), format="docx")
    f = (r.get("saved") or {}).get("file") or ""
    assert f, r
    name = os.path.basename(f)
    assert not re.search(r"[\x00-\x1f]", name) and name.startswith("a b c")
