"""행정규칙(훈령·예규·고시) 본문: 법제처에 없는 admRulService.do 대신 lawService.do?target=admrul 로 받고,
조마다 <조문내용> 글 덩어리로 오는 본문을 조문·장 머리로 읽는다."""
import xml.etree.ElementTree as ET

NM = "지식재산성과 관리 및 사용에 관한 업무처리 규정"


def _fake(calls, A):
    def f(ep, params, *a, **k):
        calls.append((ep, dict(params)))
        if ep == "lawSearch.do" and params.get("target") == "admrul":
            return ET.fromstring(f"<AdmRulSearch><admrul><행정규칙명>{NM}</행정규칙명><행정규칙일련번호>2100000281576</행정규칙일련번호>"
                                 "<행정규칙ID>23047</행정규칙ID><행정규칙종류명>훈령</행정규칙종류명></admrul></AdmRulSearch>")
        if ep == "lawSearch.do":
            return ET.fromstring("<LawSearch><totalCnt>0</totalCnt></LawSearch>")
        if ep == "lawService.do" and params.get("target") == "admrul" and params.get("ID") == "2100000281576":
            return ET.fromstring(f"<AdmRulService><행정규칙기본정보><행정규칙명>{NM}</행정규칙명><발령일자>20260625</발령일자></행정규칙기본정보>"
                                 "<조문내용>제1장 총 칙</조문내용><조문내용>제1조(목적) 이 규정은 …</조문내용>"
                                 "<조문내용>제5조의2(위원) ① 위원은 …\n② 간사는 …</조문내용></AdmRulService>")
        raise A.req_lib.exceptions.ConnectionError("없는 주소")
    return f


def test_admrul_articles(client, monkeypatch):
    import api_server as A
    calls = []
    monkeypatch.setattr(A, "_law_get_xml", _fake(calls, A))
    if hasattr(A, "_LOOKUP_CACHE") and hasattr(A._LOOKUP_CACHE, "clear"):
        A._LOOKUP_CACHE.clear()
    d = client.get("/api/law/articles", query_string={"name": NM}).get_json()
    arts = [x for x in d.get("articles") or [] if x.get("type") == "article"]
    assert [x["조문표시번호"] for x in arts] == ["제1조", "제5조의2"], d
    assert arts[0]["조문제목"] == "목적"
    assert any(x.get("type") == "header" and x.get("header_no") == "제1장" for x in d["articles"])
    assert not any(ep == "admRulService.do" for ep, _ in calls)


def test_law_go_redirects_by_kind(client, monkeypatch):
    """법령 바로가기: 행정규칙이면 /행정규칙/, 법령이면 /법령/(조문까지), 확인 못 하면 /법령/."""
    from urllib.parse import unquote
    import api_server as A
    calls = []
    monkeypatch.setattr(A, "_law_get_xml", _fake(calls, A))
    A._LOOKUP_CACHE.clear() if hasattr(A, "_LOOKUP_CACHE") and hasattr(A._LOOKUP_CACHE, "clear") else None
    A._LAW_GO_KIND.clear(); A._LAW_GO_HITS.clear()
    r = client.get("/api/law/go", query_string={"name": NM, "art": "제5조"})
    assert r.status_code == 302 and unquote(r.headers["Location"]) == f"https://www.law.go.kr/행정규칙/{NM}"

    def law_xml(ep, params, *a, **k):
        if ep == "lawSearch.do" and params.get("target") == "law":
            return ET.fromstring("<LawSearch><law><법령명한글>민법</법령명한글><법령일련번호>1</법령일련번호></law></LawSearch>")
        raise AssertionError("법령이면 행정규칙을 찾지 않는다")
    monkeypatch.setattr(A, "_law_get_xml", law_xml)
    r = client.get("/api/law/go", query_string={"name": "민법", "art": "제 3 조의2"})
    assert r.status_code == 302 and unquote(r.headers["Location"]) == "https://www.law.go.kr/법령/민법/제3조의2"

    monkeypatch.setattr(A, "OC", "")
    r = client.get("/api/law/go", query_string={"name": "어떤 법"})
    assert unquote(r.headers["Location"]) == "https://www.law.go.kr/법령/어떤 법"
    assert client.get("/api/law/go").status_code == 400


def test_agent_law_links_go_through_server():
    import pathlib
    js = (pathlib.Path(__file__).resolve().parents[1] / "assets" / "reg_agent.js").read_text(encoding="utf-8")
    assert "'/api/law/go?name='" in js and "law.go.kr/법령/'+" not in js


def test_law_go_failure_not_cached_and_hits_cached(client, monkeypatch):
    """법제처 조회 실패는 /법령/ 으로 보내되 캐시하지 않고(no-store), 확정된 종류는 기억해 다시 부르지 않는다."""
    from urllib.parse import unquote
    import api_server as A
    A._LAW_GO_KIND.clear(); A._LAW_GO_HITS.clear()
    calls = []

    def down(ep, params, *a, **k):
        calls.append(params.get("target"))
        raise A.req_lib.exceptions.ConnectionError("법제처 장애")
    monkeypatch.setattr(A, "_law_get_xml", down)
    r = client.get("/api/law/go", query_string={"name": NM})
    assert unquote(r.headers["Location"]) == f"https://www.law.go.kr/법령/{NM}"
    assert r.headers["Cache-Control"] == "no-store" and NM not in A._LAW_GO_KIND
    # 복구되면 행정규칙으로 확정 → 기억해서 다음 클릭은 법제처를 부르지 않는다
    calls.clear()
    monkeypatch.setattr(A, "_law_get_xml", _fake(calls, A))
    r = client.get("/api/law/go", query_string={"name": NM})
    assert "/행정규칙/" in unquote(r.headers["Location"]) and r.headers["Cache-Control"].startswith("public")
    n = len(calls)
    r = client.get("/api/law/go", query_string={"name": NM})
    assert "/행정규칙/" in unquote(r.headers["Location"]) and len(calls) == n


def test_law_go_lookup_budget(client, monkeypatch):
    """공개 주소 — 법제처 조회는 분당 한도까지. 넘으면 조회 없이 /법령/(no-store)."""
    import api_server as A
    A._LAW_GO_KIND.clear(); A._LAW_GO_HITS.clear()
    monkeypatch.setattr(A, "_LAW_GO_PER_MIN", 2)
    calls = []
    monkeypatch.setattr(A, "_law_get_xml", _fake(calls, A))
    for i in range(2):
        client.get("/api/law/go", query_string={"name": f"없는 규정 {i}"})
    n = len(calls)
    r = client.get("/api/law/go", query_string={"name": "없는 규정 9"})
    assert len(calls) == n and r.headers["Cache-Control"] == "no-store"


def test_admrul_title_nested_parens_and_long_chapter():
    """행정규칙 본문: 괄호가 겹친 제목(“위원회의 구성(등)”)과 60자 넘는 장 제목도 읽는다."""
    import api_server as A
    long = "가" * 80
    x = (f"<R><행정규칙명>x</행정규칙명><조문내용>제1장 {long}</조문내용>"
         "<조문내용>제3조(위원회의 구성(등)) 위원회는…</조문내용><조문내용>제4조 삭제</조문내용></R>")
    _, _, arts = A._parse_articles(ET.fromstring(x))
    assert arts[0]["type"] == "header" and arts[0]["조문제목"] == long
    assert arts[1]["조문제목"] == "위원회의 구성(등)" and arts[2]["조문표시번호"] == "제4조"


def test_articles_do_not_open_partially_matching_admrul(client, monkeypatch):
    """국가법령에 없는 이름(사내 규정명·오타)으로 조회할 때 이름 일부만 겹치는 다른 행정규칙 본문을 열지 않는다."""
    import api_server as A
    calls = []

    def fake(ep, params, *a, **k):
        calls.append((ep, dict(params)))
        if ep == "lawSearch.do" and params.get("target") == "admrul":
            return ET.fromstring("<AdmRulSearch><admrul><행정규칙명>농림축산검역본부 여비 지급 규정</행정규칙명>"
                                 "<행정규칙일련번호>9</행정규칙일련번호></admrul></AdmRulSearch>")
        if ep == "lawSearch.do":
            return ET.fromstring("<LawSearch><totalCnt>0</totalCnt></LawSearch>")
        raise AssertionError(f"본문을 부르면 안 된다: {params}")
    monkeypatch.setattr(A, "_law_get_xml", fake)
    A._LOOKUP_CACHE.clear() if hasattr(A, "_LOOKUP_CACHE") and hasattr(A._LOOKUP_CACHE, "clear") else None
    d = client.get("/api/law/articles", query_string={"name": "여비 지급 규정"}).get_json()
    assert d.get("count") == 0 and not d.get("articles")
    assert not any(ep == "lawService.do" for ep, _ in calls)
