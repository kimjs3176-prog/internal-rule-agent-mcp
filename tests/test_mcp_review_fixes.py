"""MCP 원격·알리오 도구 독립 검토에서 재현된 결함의 회귀 시험."""
import base64
import json
import time
import zlib

import pytest
from conftest import needs_engine

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
PUB = {"Host": "agro-law-demo.vercel.app", "X-Forwarded-Proto": "https"}


def call(client, name, args, headers=None):
    r = client.post("/mcp", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}, ensure_ascii=False),
                    headers={**H, **PUB, **(headers or {})})
    assert r.status_code == 200, r.data
    return r.get_json()["result"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("MCP_TOKEN", "MCP_HTTP", "MCP_ALLOWED_ORIGINS", "MCP_PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)


# ── 알리오 ──────────────────────────────────────────────────────────────────
@pytest.fixture()
def alio_fake(monkeypatch, ra):
    """tests/test_mcp_alio.py 와 같은 가짜(저장한 실제 알리오 응답)."""
    import test_mcp_alio as T
    import alio
    alio._cache.update({"orgs": None, "orgs_at": 0.0, "search": {}, "files": {}, "text": {}})
    orgs, pages = json.loads(T._fx("orgs.json")), json.loads(T._fx("search_C0105_all.json"))
    hwpx = ra.build_hwpx([{"t": "p", "text": T.RULE}])
    state = {"search_fail": False}

    def fake(method, path, *, json_body=None, binary=False, retries=2, deadline=None):
        if path.startswith("/item/itemOrganListSusi.json"):
            return T._Resp(), json.dumps(orgs)
        if path.startswith("/item/itemReportListSusi.json"):
            if state["search_fail"]:
                raise alio.AlioError("NETWORK", "알리오 연결 실패: ConnectTimeout")
            if json_body["apbaId"] != "C0105":
                return T._Resp(), json.dumps({"data": {"result": [], "page": {"totalPage": 1, "totalCount": 0}}})
            return T._Resp(), json.dumps(pages[str(json_body["pageNo"])])
        if path.startswith("/item/itemBoard21110.do"):
            return T._Resp("text/html"), T._fx("detail_C0105_21892.html")
        if path.startswith("/download/rulefiledown.json"):
            return T._Resp("application/octet-stream"), hwpx
        raise AssertionError(path)

    monkeypatch.setattr(alio, "_request", fake)
    monkeypatch.setattr(alio, "reachable", lambda force=False: True)
    yield state
    alio._cache.update({"orgs": None, "orgs_at": 0.0, "search": {}, "files": {}, "text": {}})


def test_ambiguous_agency_name_is_not_guessed(client, alio_fake):
    r = call(client, "alio_search_regulations", {"keyword": "여비", "agencies": ["한국전력"]})
    t = r["content"][0]["text"]
    assert r["isError"] and "여러 기관" in t and "한국전력공사" in t and "한국전력거래소" in t        # 첫 기관을 몰래 고르지 않는다
    d = call(client, "alio_search_regulations", {"keyword": "규정", "agencies": ["인천국제공항"]})["structuredContent"]
    assert d["agencies_searched"] == 1 and d["results"][0]["agency"] == "인천국제공항공사"          # 하나뿐이면 고른다


def test_category_shorthand_and_unknown(client, alio_fake):
    d = call(client, "alio_search_regulations", {"keyword": "규정", "agencies": ["C0105"], "category": "인사"})
    assert not d["isError"]
    r = call(client, "alio_search_regulations", {"keyword": "규정", "agencies": ["C0105"], "category": "없는분류"})
    assert r["isError"] and "인사·복무·징계" in r["content"][0]["text"]


def test_all_failed_search_is_an_error_not_zero_results(client, alio_fake):
    alio_fake["search_fail"] = True
    r = call(client, "alio_search_regulations", {"keyword": "여비", "agencies": ["C0105", "C0422"]})
    assert r["isError"] and "조회하지 못했습니다" in r["content"][0]["text"]


def test_explicit_articles_are_not_cut_by_limit_and_date_suffix(client, alio_fake):
    r = call(client, "alio_get_regulation", {"id": "C0105|21892|K1100|COMM_RULE|RULE_NO|", "articles": ["1", "2", "3"], "limit": 1})["structuredContent"]
    assert [a["article"] for a in r["articles"]] == ["제1조", "제2조", "제3조"]
    from mcp_server import core
    assert core._alio_base("인사규정(2025년도 6월 개정)") == "인사규정" and core._alio_base("보수규정(2023.1.1. 개정)") == "보수규정"


def test_compare_values_answers_within_budget(client, alio_fake, monkeypatch):
    import alio
    from mcp_server import core
    monkeypatch.setattr(core, "COMPARE_BUDGET", 6)
    monkeypatch.setattr(alio, "rule_text", lambda rule, budget=None: time.sleep(9) or {"text": ""})   # 알리오가 아주 느릴 때
    t = time.monotonic()
    d = call(client, "alio_compare_values", {"item": "일비", "unit": "원", "keyword": "규정", "agencies": ["C0105"]})["structuredContent"]
    assert time.monotonic() - t < 8.5                                                                 # 끝나지 않은 기관을 기다리지 않는다
    assert d["not_found"][0]["reason"] == "시간 제한으로 건너뜀" and "partial" in d


# ── 조 번호·개정 입력 ──────────────────────────────────────────────────────────
def test_branch_article_labels(client):
    d = call(client, "fetch", {"id": "한국농업기술진흥원 정관#제13조의2"})["structuredContent"]
    assert d["title"].endswith("제13조의2(노동이사의 권한과 의무 및 책임)") and d["text"].startswith("제13조의2(")
    d = call(client, "get_regulation", {"regulation": "한국농업기술진흥원 정관", "articles": ["제13조의2"]})["structuredContent"]
    assert [a["article"] for a in d["articles"]] == ["제13조의2"]
    d = call(client, "search", {"query": "노동이사"})["structuredContent"]
    assert any(x["id"].endswith("#제13조의2") for x in d["results"])


@needs_engine
def test_amend_input_normalisation(client):
    d = call(client, "amend_regulation", {"regulation": "한국농업기술진흥원 정관", "changes": [{"article": "제13조의2", "type": "delete"}]})["structuredContent"]
    assert "제13조의2를 삭제한다." in d["amendment_text"] and d["verification"]["ok"]
    body = "여비는 운임·일비·숙박비·식비·이전비 및 가족여비로 구분한다."
    d = call(client, "amend_regulation", {"regulation": "여비규정", "changes": [{"article": "제2조", "body": "x"}, {"article": "2", "title": "", "body": body}]})["structuredContent"]
    assert any("두 번" in w for w in d["warnings"]) and d["comparison_table"][0]["amended"].startswith("제2조(여비의 종류)")   # 마지막 것, 제목은 현행
    cur = call(client, "get_regulation", {"regulation": "여비규정", "articles": ["제2조"]})["structuredContent"]["articles"][0]["body"]
    d = call(client, "amend_regulation", {"regulation": "여비규정", "changes": [{"article": "제2조", "body": cur}]})["structuredContent"]
    assert d["doc_ready"] is False and "download" not in d and any("바뀐 조문" in w for w in d["warnings"])          # 현행과 같으면 문서 없음
    r = call(client, "amend_regulation", {"regulation": "여비규정", "changes": [{"body": "x"}]})
    assert r["isError"]


# ── 내려받기 링크·전송 ─────────────────────────────────────────────────────────
def _tok(op, inp):
    return base64.urlsafe_b64encode(zlib.compress(json.dumps([op, inp], ensure_ascii=False).encode(), 9)).decode().rstrip("=")


@needs_engine
def test_doc_token_is_cleaned_and_bounded(client, monkeypatch):
    t = _tok("enact", {"op": "agent", "base": "http://evil", "title": "시험지침", "text": "제1조(목적) 이 지침은 시험을 정한다."})
    r = client.get(f"/api/mcp/doc/hwpx/{t}")
    assert r.status_code == 200 and r.data[:2] == b"PK"                                        # 엉뚱한 키(op·base)는 버린다
    big = _tok("enact", {"title": "x", "text": "제1조(목적) " + "가" * 200000})
    assert client.get(f"/api/mcp/doc/hwpx/{big}").status_code == 400                          # 압축을 풀면 큰 요청은 받지 않는다
    from mcp_server import core
    inp, _ = core.clean_input("enact", {"title": "x", "addenda": "는 " * 50000, "text": "제1조(목적) 가."})
    assert len(inp["addenda"]) == core._CAP["addenda"]                                           # 엔진에 가는 글 길이를 묶는다
    monkeypatch.setenv("MCP_TOKEN", "s3cret")
    assert client.get(f"/api/mcp/doc/hwpx/{t}.가나다").status_code == 403                       # 비ASCII 서명은 500 이 아니라 403


def test_lone_surrogate_and_rebinding(client):
    r = client.post("/mcp", data='{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}', headers=H)
    assert r.status_code == 200 and r.get_json()["result"] == {}
    r = client.post("/mcp", data='{"jsonrpc":"2.0","id":1,"method":"ping"}', headers={**H, "Host": "evil.example:5100", "Origin": "http://evil.example:5100"})
    assert r.status_code == 403                                                                  # Origin 과 Host 가 같아도 허용 목록이 아니면 막는다


def test_no_engine_message_names_the_fix(monkeypatch):
    from mcp_server import engine
    monkeypatch.setattr(engine, "backend", lambda: "node")
    monkeypatch.setattr(engine.shutil, "which", lambda n: None)
    e = engine.run("agent", {"request": "여비규정 제15조의 일비를 3만원으로 올려줘"})["error"]
    assert "Python 3.12" in e and "다른 도구는 됩니다" in e


def test_check_regulation_accepts_source_text(client):
    """amend_regulation 의 source_text 를 check_regulation 에 그대로 넘겨도 점검한다(전에는 ‘text 를 주세요’ 오류)."""
    src = "제1조(목적) 이 규정은 출장 여비를 정한다.\n제2조(일비) 일비는 제9조에 따른다."
    a = call(client, "check_regulation", {"source_text": src, "title": "가상 여비규정", "org": "가상행정진흥원"})
    b = call(client, "check_regulation", {"text": src, "title": "가상 여비규정", "org": "가상행정진흥원"})
    assert not a["isError"] and a["structuredContent"] == b["structuredContent"]
    assert any("제9조" in i["message"] for i in a["structuredContent"]["issues"])
