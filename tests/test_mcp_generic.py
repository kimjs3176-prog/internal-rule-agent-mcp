"""범용 MCP: 이 서버에 등록되지 않은 다른 기관 사규(붙여 넣은 원문·알리오 공시본)를 개정·점검하는지,
그 기관 이름이 문서에 쓰이고 우리 기관(등록 내규·구 명칭·심의기준)과 섞이지 않는지."""
import json

import pytest
from conftest import needs_engine

TXT = """출장규정
제1조(목적) 이 규정은 한국가상공단 임직원의 국내 출장에 관한 사항을 정함을 목적으로 한다.
제2조(일비) ① 일비는 1일 2만원으로 한다.
② 제3조에 따른 출장자에게 지급한다.
제3조(출장자) 출장자는 이사장이 명한 임직원으로 한다.
제4조(준용) 이 규정에 없는 사항은 「여비규정」 제30조를 준용한다.
부칙
이 규정은 2020년 1월 1일부터 시행한다."""
ORG = {"org_name": "한국가상공단", "head": "이사장", "reg_word": "사규", "rules_name": "사규관리규정"}
CHG = [{"article": "제2조", "body": "① 일비는 1일 3만원으로 한다.\n② 제3조에 따른 출장자에게 지급한다."}]
H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
PUB = {"Host": "law-agent.example", "X-Forwarded-Proto": "https"}


@pytest.fixture
def core(ra, monkeypatch):
    import alio
    from mcp_server import core
    monkeypatch.setattr(alio, "reachable", lambda force=False: False)
    return core


def test_ctx_header_scoped_to_request(ra, client):
    h = {"X-RA-Ctx": ra.make_ctx(True, {"org_name": "한국가상공단", "head": "이사장", "x": "무시"})}
    a = client.get("/api/regagent/config").get_json()
    b = client.get("/api/regagent/config", headers=h).get_json()
    c = client.get("/api/regagent/config").get_json()
    assert b["org"]["org_name"] == "한국가상공단" and b["org"]["head"] == "이사장" and b["reg_count"] == 0
    assert not b["org"].get("stale_terms") and not b["org"].get("review_criteria") and "x" not in b["org"]
    assert a["org"]["org_name"] == c["org"]["org_name"] != "한국가상공단" and c["reg_count"] == a["reg_count"] > 0   # 다음 요청에 번지지 않음
    for bad in ("", "!!!", "a" * 5000, "e30"):                     # 깨진 값·너무 긴 값·빈 객체는 무시(우리 기관 그대로)
        d = client.get("/api/regagent/config", headers={"X-RA-Ctx": bad}).get_json()
        assert d["reg_count"] == a["reg_count"]


def test_check_other_org_text_not_compared_with_our_regs(core):
    ours = [i["message"] for i in core.t_check_regulation(text=TXT, title="출장규정")["issues"]]
    theirs = [i["message"] for i in core.t_check_regulation(text=TXT, title="출장규정", org=ORG)["issues"]]
    assert any("「여비규정」 제30조" in m for m in ours)               # 우리 여비규정(29개 조)과 대조한 경고
    assert not any("「여비규정」" in m or "구 명칭" in m for m in theirs)
    assert not any("이미 지났습니다" in m for m in theirs)              # 현행 규정의 지난 부칙 시행일은 짚지 않는다
    bad = [i["message"] for i in core.t_check_regulation(text=TXT.replace("제3조에 따른", "제9조에 따른"), title="출장규정", org=ORG)["issues"]]
    assert any("제9조" in m for m in bad)                               # 규정 자체의 점검(없는 조 인용)은 그대로


@needs_engine
def test_amend_pasted_text_other_org(core, tmp_path):
    r = core.t_amend_regulation(regulation="출장규정", source_text=TXT, org=ORG, reason="일비 현실화", changes=CHG,
                                output_dir=str(tmp_path), format="docx")
    assert not r.get("error"), r
    assert "출장규정 일부를 다음과 같이 개정한다." in r["amendment_text"]
    assert "제2조제1항 중 “2만원”을 “3만원”으로 한다." in r["amendment_text"]
    assert r["verification"]["ok"] and r["comparison_table"][0]["amended"].startswith("제2조(일비) ① 일비는 1일 3만원")
    assert r["citation_impact"]["other_regulations"] == []
    import zipfile
    f = r["saved"]["file"]
    xml = "".join(zipfile.ZipFile(f).read(n).decode("utf-8", "ignore") for n in zipfile.ZipFile(f).namelist() if n.endswith(".xml"))
    assert "한국가상공단" in xml and "한국농업기술진흥원" not in xml and "농진원" not in xml


@needs_engine
def test_doc_set_drops_empty_forms(core, tmp_path):
    """MCP 문서 세트: 채울 입력이 없어 빈 서식뿐인 문서(의견수렴 결과, 항목 없는 사전검토 의견서)는 빼고 붙임 목록도 맞춘다."""
    import zipfile
    r = core.t_amend_regulation(regulation="출장규정", source_text=TXT, org=ORG, reason="일비 현실화", changes=CHG,
                                output_dir=str(tmp_path), format="docx")
    sv = r["saved"]
    assert sv["documents"] == ["심의안건서", "개정문", "신구조문대비표", "개정 이유서"]
    assert sv["omitted"] == ["의견수렴 결과", "사전검토 의견서"] and "빈 서식" in sv["note"]
    xml = "".join(zipfile.ZipFile(sv["file"]).read(n).decode("utf-8", "ignore") for n in zipfile.ZipFile(sv["file"]).namelist() if n.endswith(".xml"))
    assert "의견수렴 결과" not in xml and "사전검토 의견서" not in xml and "제출된 의견 없음" not in xml
    assert "개정 이유서 1부." in xml
    # 등록 내규(우리 기관)는 심의기준 검토 항목이 있어 사전검토 의견서를 넣는다 — 의견수렴 결과만 뺀다
    r2 = core.t_run_agent(request="여비규정 제15조의 일비를 3만원으로 올려줘", output_dir=str(tmp_path), format="docx")
    assert r2["saved"]["documents"][-1] == "사전검토 의견서" and r2["saved"]["omitted"] == ["의견수렴 결과"]


@needs_engine
def test_amend_needs_some_source(core):
    assert "regulation" in core.t_amend_regulation(changes=CHG)["error"]
    r = core.t_amend_regulation(regulation="없는출장규정", changes=CHG)
    assert r["error"] and "source_text" in r["hint"]
    r = core.t_amend_regulation(regulation="출장규정", source_text="조문이 없는 글", changes=CHG)
    assert "조문을 찾지 못했습니다" in r["error"]


@needs_engine
def test_amend_from_alio_and_short_link(core, monkeypatch, client):
    """alio_id: 알리오 공시본 전문을 현행으로 개정하고, 내려받기 링크에는 원문 대신 id 만 담는다."""
    import alio
    rid = "C9999|123|K1100|COMM_RULE|RULE_NO|20250101"
    monkeypatch.setattr(core, "_alio_orgs", lambda: {"orgs": [{"id": "C9999", "name": "한국가상공단"}]})
    monkeypatch.setattr(alio, "rule_text", lambda rule, budget=None: {"text": TXT * 1, "file": {"fileName": "출장규정(2024).hwpx"}, "files": [1]})
    from mcp_server import remote  # noqa: F401 — /mcp 등록
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "amend_regulation", "arguments": {"alio_id": rid, "changes": CHG}}}
    r = client.post("/mcp", data=json.dumps(body, ensure_ascii=False), headers={**H, **PUB}).get_json()["result"]
    d = r["structuredContent"]
    assert not r["isError"], d
    assert "제2조제1항 중 “2만원”을 “3만원”으로 한다." in d["amendment_text"] and d["verification"]["ok"]
    link = d["download"]["docx"]
    tok = link.rsplit("/", 1)[1]
    op, inp = core.read_token(tok)
    assert inp.get("alio_id") == rid and "source_text" not in inp and len(tok) < 1500
    f = client.get(link.split("example", 1)[1])
    assert f.status_code == 200 and f.data[:2] == b"PK"


def test_tool_schemas_advertise_generic_inputs(core):
    tools = {t["name"]: t for t in core.tool_list()}
    p = tools["amend_regulation"]["inputSchema"]
    assert {"source_text", "alio_id", "org"} <= set(p["properties"]) and p["required"] == ["changes"]
    assert {"alio_id", "org"} <= set(tools["check_regulation"]["inputSchema"]["properties"])
    assert "org" in tools["enact_regulation"]["inputSchema"]["properties"]
