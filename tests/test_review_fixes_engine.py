"""검토 지적 수정(엔진): 옛 부칙 시행일 경고·괄호 삭제 조·만+천 금액·띄어쓰기 다른 항목·법령 조 전역 공유·LAW_OC 노출."""
import threading
import time

import pytest
import requests


# 1. 기존 규정 점검 — 옛 부칙의 지난 시행일은 경고하지 않는다(새로 쓰는 부칙만)
_OLD = ("제1조(목적) 이 규정은 목적을 정한다.\n제2조(정의) 정의는 다음과 같다.\n"
        "부칙 <2015.1.1>\n이 규정은 2015년 1월 1일부터 시행한다.\n"
        "부칙 <2018.3.1>\n이 규정은 2018년 3월 1일부터 시행한다.")


def test_lint_text_skips_historical_addenda(client):
    r = client.post("/api/regagent/lint", json={"text": _OLD, "title": "시험 규정"}).get_json()
    assert r["success"] and not [i for i in r["issues"] if i["code"] == "addate"]


def test_check_regulation_existing_text_no_past_addenda_warning():
    from mcp_server import core
    r = core.t_check_regulation(text=_OLD, title="시험 규정", org={"org_name": "가공단"})
    assert "이미 지났습니다" not in str(r)


def test_lint_supplied_addenda_still_checked(client):
    r = client.post("/api/regagent/lint", json={"text": _OLD, "addenda": "이 규정은 2020년 1월 1일부터 시행한다.",
                                                "title": "시험 규정"}).get_json()
    assert [i["level"] for i in r["issues"] if i["code"] == "addate"] == ["warn"]


# 2. 괄호로 쓴 삭제 조
@pytest.mark.parametrize("ln", ["제3조(삭제)", "제3조 (삭제)", "제3조(삭제) <2020. 1. 1.>", "제3조 〔삭제〕",
                                "제3조【삭제】", "제3조 【삭제】 <2020.1.1>"])
def test_parse_bracketed_deleted_article(ra, ln):
    p = ra.parse_text(f"제1조(목적) 목적.\n제2조(정의) 정의.\n{ln}\n제4조(기타) 기타.")
    arts = {a["no"]: a for a in p["articles"]}
    assert list(arts) == ["1", "2", "3", "4"] and arts["3"]["deleted"] and arts["2"]["body"] == "정의."
    iss = ra.lint_articles(p["articles"], "", "", "시험 규정")
    assert not [i for i in iss if i["code"] == "empty"]


def test_parse_titled_article_not_deleted(ra):
    p = ra.parse_text("제1조(목적) 목적.\n제2조(삭제 절차) 삭제는 다음과 같이 한다.")
    assert not p["articles"][1]["deleted"]


# 3. 만+천 복합 금액
@pytest.mark.parametrize("s,v", [("일비는 1일 2만5천원으로 한다.", 25000), ("일비는 1일 1만 5천 원으로 한다.", 15000),
                                 ("일비는 1일 2만원으로 한다.", 20000), ("일비는 1일 5천원으로 한다.", 5000)])
def test_bench_compound_man_cheon(ra, s, v):
    m = ra.bench_extract("제5조(일비) " + s, "일비", "원")
    assert m and m[0]["first"] == v, m


# 4. 항목 띄어쓰기가 달라도 그 항목 뒤의 값
def test_bench_item_spacing_differs(ra):
    t = "제5조(여비) 식비는 1일 30,000원, 국내일비는 1일 20,000원으로 한다."
    assert ra.bench_extract(t, "국내 일비", "원")[0]["first"] == 20000


# 5. 법령 조를 전역에 두지 않는다 — 동시에 부른 계획이 서로의 조를 덮어쓰지 않는다
def test_law_art_change_returns_article(ra):
    assert ra._law_art_change("근로기준법 제60조가 개정됐어") == ("근로기준법", "제60조")
    assert ra._law_art_change("여비를 올려줘") == ("", "")


def test_heuristic_plan_threads_do_not_share_article(ra, monkeypatch):
    orig = ra._CORPUS_LAWS

    def slow():
        time.sleep(0.2)
        return orig()
    monkeypatch.setattr(ra, "_CORPUS_LAWS", slow)
    res = {}

    def go(k, q):
        res[k] = ra.heuristic_plan(q)
    a = threading.Thread(target=go, args=("A", "근로기준법 제60조가 개정됐어"))
    b = threading.Thread(target=go, args=("B", "청탁금지법 제10조가 개정됐어"))
    a.start(); time.sleep(0.05); b.start(); a.join(); b.join()
    assert res["A"] == ra.heuristic_plan("근로기준법 제60조가 개정됐어")
    assert res["B"] == ra.heuristic_plan("청탁금지법 제10조가 개정됐어")


# 6. LAW_OC 가 오류 문구·로그에 나오지 않는다
def test_law_error_does_not_leak_oc(client, monkeypatch, capsys):
    import api_server as A
    import reg_agent as R
    monkeypatch.setattr(A, "OC", "secret-oc-id")

    def fake_get(url, params=None, timeout=None, **kw):
        req = requests.Request("GET", url, params=params).prepare()
        resp = requests.Response()
        resp.status_code, resp.url, resp._content = 403, req.url, b""
        return resp
    monkeypatch.setattr(A._LAW_SESSION, "get", fake_get)
    R._LAW_FRESH.clear()
    r = client.post("/api/regagent/health/laws", json={"names": ["가나다라법"]})
    out = capsys.readouterr()
    body = r.get_data(as_text=True)
    assert "secret-oc-id" not in body and "secret-oc-id" not in out.out + out.err
    assert "error" in body                                # 실패는 실패로 알린다


def test_redact_oc_helper():
    import api_server as A
    import reg_agent as R
    s = "403 Client Error for url: https://x/lawSearch.do?target=law&OC=abc123&type=XML"
    assert "abc123" not in A._redact_oc(s) and "OC=***" in A._redact_oc(s)
    assert "abc123" not in R._redact_oc(s)
