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
