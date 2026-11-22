"""별표 표 모양: 원문 글(칸마다 한 줄)을 원본 HTML 표 모양으로 되돌려 개정문 별지·대비표·문서에서 표로 쓴다."""
import io
import re
import zipfile

from conftest import needs_engine


def _expand(lay):
    return sum(s["lines"] if "lines" in s else sum(c["n"] for r in s["table"] for c in r) for s in lay)


def test_layout_matches_body_lines(ra):
    for title, bid in (("여비규정", "별표 2"), ("복무규정", "별표 2")):
        r = ra.find_reg("", title)
        lay = ra.appendix_layouts(r["slug"])[bid]
        body = [x for b in ra.split_appendix(r["appendix"]) if b["id"] == bid for x in b["body"].split("\n") if x.strip()]
        assert _expand(lay) == len(body)                         # 펼친 줄 수 = 원문 줄 수(글은 원문 줄을 그대로 씀)
        assert all(ra.table_grid(s["table"])[0] is not None for s in lay if "table" in s)
    lay = ra.appendix_layouts(ra.find_reg("", "여비규정")["slug"])["별표 2"]
    t = next(s["table"] for s in lay if "table" in s)
    assert len(t) == 3 and len(t[0]) == 8                         # 머리·표 이름·단위 줄은 표 밖 글, 표는 3행 8열
    lay = ra.appendix_layouts(ra.find_reg("", "복무규정")["slug"])["별표 2"]
    assert any(c["rs"] > 1 for s in lay if "table" in s for r in s["table"] for c in r)   # 행 병합(결혼·사망)


def test_articles_api_carries_layout(client, ra):
    d = client.get("/api/regagent/articles?title=여비규정").get_json()
    x = next(b for b in d["appendix"] if b["id"] == "별표 2")
    assert x["layout"] and _expand(x["layout"]) == len([l for l in x["body"].split("\n") if l.strip()])


def test_grid_and_docs_support_rowspan(ra):
    rows = [[{"t": "가", "rs": 2}, {"t": "나"}, {"t": "다"}], [{"t": "라"}, {"t": "마"}], [{"t": "바", "cs": 3}]]
    cols, n = ra.table_grid(rows)
    assert cols == [[0, 1, 2], [1, 2], [0]] and n == 3
    assert ra.table_grid([[{"t": "a"}, {"t": "b"}], [{"t": "c"}]])[0] is None          # 열 수가 다른 행
    blk = [{"t": "table", "rows": rows}]
    dx = zipfile.ZipFile(io.BytesIO(ra.build_docx(blk))).read("word/document.xml").decode()
    assert '<w:vMerge w:val="restart"/>' in dx and dx.count("<w:vMerge/>") == 1 and dx.count("<w:gridCol") == 3
    hx = zipfile.ZipFile(io.BytesIO(ra.build_hwpx(blk))).read("Contents/section0.xml").decode()
    assert 'rowSpan="2"' in hx and '<hp:cellAddr colAddr="1" rowAddr="1"/>' in hx and 'colSpan="3"' in hx


@needs_engine
def test_amend_appendix_documents_draw_table(ra, tmp_path, monkeypatch):
    import alio
    from mcp_server import core
    monkeypatch.setattr(alio, "reachable", lambda force=False: False)
    r = ra.find_reg("", "복무규정")
    body = next(b["body"] for b in ra.split_appendix(r["appendix"]) if b["id"] == "별표 2").split("\n")
    body[next(i for i, l in enumerate(body) if l.strip() == "5일")] = "6일"
    res = core.t_amend_regulation(regulation="복무규정", appendix_changes=[{"id": "별표 2", "body": "\n".join(body)}],
                                  reason="경조휴가 조정", output_dir=str(tmp_path), format="docx")
    assert res["verification"]["ok"]
    cmp = res["comparison_table"][0]
    assert "결 혼 │ 본인 │ 5일" in cmp["current"] and "결 혼 │ 본인 │ 6일" in cmp["amended"]   # 대비표: 표의 한 행이 한 줄
    assert "구 분 │ 대 상 │ 휴가일수" in cmp["amended"]                                  # 열 제목 행은 남긴다
    dx = zipfile.ZipFile(res["saved"]["file"]).read("word/document.xml").decode()
    assert '<w:vMerge w:val="restart"/>' in dx                                          # 별지 별표는 행 병합까지 표로
    # 줄을 넣어 모양과 줄 수가 달라지면 표 대신 지금처럼 글로(깨진 표를 만들지 않음)
    body2 = body + ["※ 새 비고"]
    res2 = core.t_amend_regulation(regulation="복무규정", appendix_changes=[{"id": "별표 2", "body": "\n".join(body2)}],
                                   reason="비고 추가", output_dir=str(tmp_path / "b"), format="docx")
    dx2 = zipfile.ZipFile(res2["saved"]["file"]).read("word/document.xml").decode()
    assert "vMerge" not in dx2 and "※ 새 비고" in re.sub(r"<[^>]+>", "", dx2)
