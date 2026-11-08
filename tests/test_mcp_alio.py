"""MCP 로 다른 기관 사규(알리오) 쓰기 — 찾기·읽기·수치 비교, 그리고 참고 조문을 개정·제정 문서의 근거로 남기기.
저장한 실제 알리오 응답(tests/fixtures/alio)으로 네트워크 없이 확인한다(test_alio.py 와 같은 방식)."""
import json
import os

import pytest

FX = os.path.join(os.path.dirname(__file__), "fixtures", "alio")
H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
PUB = {"Host": "agro-law-demo.vercel.app", "X-Forwarded-Proto": "https"}
RULE = ("인사규정\n제1조(목적) 이 규정은 인사에 관한 사항을 정한다.\n"
        "제2조(여비) ① 출장 여비는 실비로 지급한다.\n② 일비는 1일 20,000원으로 한다.\n"
        "제3조(채용) 직원은 공개경쟁으로 채용한다.")


def _fx(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


class _Resp:
    def __init__(self, ct="application/json"):
        self.headers = {"content-type": ct}


@pytest.fixture()
def alio_fake(monkeypatch, ra):
    import alio
    alio._cache.update({"orgs": None, "orgs_at": 0.0, "search": {}, "files": {}, "text": {}})
    orgs, pages = json.loads(_fx("orgs.json")), json.loads(_fx("search_C0105_all.json"))
    hwpx = ra.build_hwpx([{"t": "p", "text": RULE}])

    def fake(method, path, *, json_body=None, binary=False, retries=2, deadline=None):
        if path.startswith("/item/itemOrganListSusi.json"):
            return _Resp(), json.dumps(orgs)
        if path.startswith("/item/itemReportListSusi.json"):
            if json_body["apbaId"] != "C0105":
                return _Resp(), json.dumps({"data": {"result": [], "page": {"totalPage": 1, "totalCount": 0}}})
            return _Resp(), json.dumps(pages[str(json_body["pageNo"])])
        if path.startswith("/item/itemBoard21110.do"):
            return _Resp("text/html"), _fx("detail_C0105_21892.html")
        if path.startswith("/download/rulefiledown.json"):
            return _Resp("application/octet-stream"), hwpx
        raise AssertionError(path)

    monkeypatch.setattr(alio, "_request", fake)
    monkeypatch.setattr(alio, "reachable", lambda force=False: True)
    yield alio
    alio._cache.update({"orgs": None, "orgs_at": 0.0, "search": {}, "files": {}, "text": {}})


def call(client, name, args):
    r = client.post("/mcp", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}, ensure_ascii=False),
                    headers={**H, **PUB})
    assert r.status_code == 200, r.data
    return r.get_json()["result"]


def test_tools_listed_with_open_world_hint(client):
    r = client.post("/mcp", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), headers=H).get_json()["result"]["tools"]
    by = {t["name"]: t for t in r}
    for n in ("alio_search_regulations", "alio_get_regulation", "alio_compare_values", "enact_regulation"):
        assert n in by
    assert by["alio_get_regulation"]["annotations"]["openWorldHint"] and by["alio_get_regulation"]["annotations"]["readOnlyHint"]
    assert "references" in by["amend_regulation"]["inputSchema"]["properties"] and "references" in by["enact_regulation"]["inputSchema"]["properties"]


def test_search_and_read_other_agency(client, alio_fake):
    d = call(client, "alio_search_regulations", {"keyword": "규정", "agencies": ["인천국제공항공사"]})["structuredContent"]
    assert d["agencies_searched"] == 1 and d["count"] > 10 and d["scope"] == "agencies"
    h = d["results"][0]
    assert h["agency"] == "인천국제공항공사" and h["id"].startswith("C0105|") and h["url"].startswith("https://www.alio.go.kr/item/itemBoard21110.do?")
    assert all(not x["superseded"] for x in d["results"])                                  # 옛 판은 기본으로 뺀다
    # 기본 범위(유관 기관 — 농촌진흥청·농림축산식품부 산하)에는 이 시험 자료가 없다
    assert call(client, "alio_search_regulations", {"keyword": "여비"})["structuredContent"]["count"] == 0
    rid = "C0105|21892|K1100|COMM_RULE|RULE_NO|"
    r = call(client, "alio_get_regulation", {"id": rid, "query": "여비 일비"})["structuredContent"]
    assert r["agency"] == "인천국제공항공사" and r["article_count"] == 3 and r["articles"][0]["article"] == "제2조"
    assert r["toc"][0] == "제1조(목적)" and r["url"].startswith("https://www.alio.go.kr/") and "기관명" in r["source"]
    r = call(client, "alio_get_regulation", {"id": rid, "articles": ["제3조", "9"]})["structuredContent"]
    assert [a["article"] for a in r["articles"]] == ["제3조"] and r["missing"] == ["제9조"] and "공개경쟁" in r["articles"][0]["body"]
    assert call(client, "alio_get_regulation", {"id": "C0105|1;rm|x"})["isError"]


def test_compare_values_across_agencies(client, alio_fake):
    d = call(client, "alio_compare_values", {"item": "일비", "unit": "원", "keyword": "규정", "agencies": ["인천국제공항공사"]})["structuredContent"]
    assert d["regulations_checked"] == 1 and d["values"][0]["value"] == 20000 and d["values"][0]["article"] == "제2조"
    assert "20,000원" in d["values"][0]["sentence"] and d["summary"] == {"count": 1, "min": 20000, "max": 20000, "median": 20000}
    assert "sentence" in d["caution"]
    assert call(client, "alio_compare_values", {"item": "일비", "unit": "달러", "keyword": "여비"})["isError"]


def test_alio_down_is_reported(client, monkeypatch, ra):
    import alio
    alio._cache.update({"orgs": None, "orgs_at": 0.0})
    monkeypatch.setattr(alio, "reachable", lambda force=False: False)
    r = call(client, "alio_search_regulations", {"keyword": "여비"})
    assert r["isError"] and "알리오에 연결하지 못했습니다" in r["content"][0]["text"]


def test_references_go_into_amend_and_enact_documents(client, alio_fake):
    ref = [{"agency": "인천국제공항공사", "regulation": "인사규정", "article": "제2조", "title": "여비", "body": "② 일비는 1일 20,000원으로 한다."}]
    d = call(client, "amend_regulation", {"regulation": "여비규정", "changes": [{"article": "제2조", "body": "여비는 운임·일비·숙박비·식비·이전비 및 가족여비로 구분한다."}],
                                          "reason": "준비금 폐지", "references": ref})["structuredContent"]
    assert d["references"] == [{"agency": "인천국제공항공사", "regulation": "인사규정", "article": "제2조", "title": "여비"}]
    need = next(c for c in d["review"]["criteria"] if c["criterion"] == "내규의 필요성")
    assert any("다른 공공기관 운영 사례 1곳" in n and "인천국제공항공사 「인사규정」 제2조(여비)" in n for n in need["notes"])
    f = client.get(d["download"]["hwpx"].split("vercel.app", 1)[1])
    assert f.status_code == 200 and f.data[:2] == b"PK"
    text = "제1조(목적) 이 지침은 업무용 드론의 운영에 필요한 사항을 정함을 목적으로 한다.\n제2조(비행 승인) 드론을 비행하려는 부서는 미리 승인을 받아야 한다.\n제3조(사고 보고) 사고가 나면 즉시 보고한다."
    e = call(client, "enact_regulation", {"title": "업무용 드론 운영지침", "text": text, "purpose": "업무용 드론을 안전하게 운영하려는 것임",
                                          "references": [{"agency": "한국농어촌공사", "regulation": "드론 운영규정", "article": "5", "title": "비행 승인"}]})["structuredContent"]
    assert e["article_count"] == 3 and e["category"] == "지침" and e["check"]["errors"] == 0 and e["review"]["criteria"]
    assert e["references"][0]["article"] == "제5조"
    f = client.get(e["download"]["docx"].split("vercel.app", 1)[1])
    assert f.status_code == 200 and f.data[:2] == b"PK"
    assert call(client, "enact_regulation", {"title": "x지침", "text": "조문 없음"})["isError"]


def test_run_agent_compare_mode(client, alio_fake, ra, monkeypatch):
    monkeypatch.setitem(ra.ORG, "alio", {**(ra.ORG.get("alio") or {}), "peers": ["C0105"]})        # 시험 자료 기관을 유관 기관으로
    d = call(client, "run_agent", {"request": "다른 기관은 여비를 어떻게 규정했어?"})["structuredContent"]
    assert d["mode"] == "compare", d
    c = d["compare"]
    assert c["keyword"] == "여비" and c["found"] and c["found"][0]["agency"] == "인천국제공항공사"
    assert c["opened"] and c["opened"][0]["articles"][0]["article"] == "제2조" and "실비" in c["opened"][0]["articles"][0]["body"]
    assert c["found"][0]["id"].count("|") == 5                                                  # alio_get_regulation 에 그대로 넣을 수 있는 id
