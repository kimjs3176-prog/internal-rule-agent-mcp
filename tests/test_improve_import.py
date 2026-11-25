"""reg_import 열람 HTML 제목 판정·DOCX 세로 병합·조 앵커 id 중복 회귀 테스트."""
import io
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reg_import as ri  # noqa: E402


def _view(lines):
    return ri._blocks_to_view_html("t", {}, [{"type": "p", "text": l} for l in lines])


def _tag_of(html, text):
    m = re.search(r"<(h2|h3|p)([^>]*)>" + re.escape(text) + r"</\1>", html)
    return (m.group(1), m.group(2)) if m else None


# 1. 인용 문장은 본문으로, 진짜 제목 꼴만 제목으로
def test_article_citation_sentence_is_body():
    h = _view(["제3조 및 제4조의 개정규정은 2025년 1월 1일부터 시행한다.",
               "제5조에 따른 위원회는 위원장이 소집한다.",
               "제1조(목적) 이 규정은 목적을 정한다.",
               "제2조의2(정의) 용어의 뜻은 다음과 같다."])
    assert _tag_of(h, "제3조 및 제4조의 개정규정은 2025년 1월 1일부터 시행한다.")[0] == "p"
    assert _tag_of(h, "제5조에 따른 위원회는 위원장이 소집한다.")[0] == "p"
    assert _tag_of(h, "제1조(목적) 이 규정은 목적을 정한다.")[0] == "h3"
    assert _tag_of(h, "제2조의2(정의) 용어의 뜻은 다음과 같다.")[0] == "h3"


def test_appendix_citation_sentence_is_body():
    h = _view(["서식은 원장이 따로 정한다.", "별표에 따른 금액을 지급한다.", "별지 서식에 따라 신청한다.",
               "[별표 1] 수당 지급 기준", "별지 제1호서식", "<별지 제2호 서식>", "서식 1"])
    for t in ["서식은 원장이 따로 정한다.", "별표에 따른 금액을 지급한다.", "별지 서식에 따라 신청한다."]:
        assert _tag_of(h, t)[0] == "p", t
    for t in ["[별표 1] 수당 지급 기준", "별지 제1호서식", "&lt;별지 제2호 서식&gt;", "서식 1"]:
        assert _tag_of(h, t) == ("h3", ' class="apx"'), t


# 2. 한글 경계: '제1장총칙'도 장 제목, '제1장의 규정은'은 본문
def test_chapter_heading_hangul_boundary():
    h = _view(["제1장총칙", "제2장 위원회", "제1장의 규정은 준용한다.", "제3장 및 제4장은 삭제한다."])
    assert _tag_of(h, "제1장총칙")[0] == "h2"
    assert _tag_of(h, "제2장 위원회")[0] == "h2"
    assert _tag_of(h, "제1장의 규정은 준용한다.")[0] == "p"
    assert _tag_of(h, "제3장 및 제4장은 삭제한다.")[0] == "p"


# 3. DOCX 세로 병합(vMerge)
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _tc(t, vm=None, gs=None):
    pr = ""
    if gs:
        pr += f'<w:gridSpan w:val="{gs}"/>'
    if vm == "restart":
        pr += '<w:vMerge w:val="restart"/>'
    elif vm == "cont":
        pr += "<w:vMerge/>"
    return f"<w:tc><w:tcPr>{pr}</w:tcPr><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>"


def _docx(rows):
    tbl = "<w:tbl>" + "".join("<w:tr>" + "".join(r) + "</w:tr>" for r in rows) + "</w:tbl>"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{tbl}</w:body></w:document>")
    return b.getvalue()


def _vmerge_doc():
    return _docx([
        [_tc("구분"), _tc("항목"), _tc("금액")],
        [_tc("여비", "restart"), _tc("숙박비"), _tc("70,000")],
        [_tc("", "cont"), _tc("식비"), _tc("25,000")],
        [_tc("", "cont"), _tc("교통비"), _tc("실비")],
        [_tc("수당"), _tc("시간외", gs=1), _tc("10,000")],
    ])


def test_docx_vmerge_rowspan_blocks():
    tbl = [b for b in ri._docx_blocks(_vmerge_doc()) if b["type"] == "table"][0]
    rows = tbl["rows"]
    assert [c["t"] for c in rows[1]] == ["여비", "숙박비", "70,000"]
    assert rows[1][0]["rs"] == 3
    assert [c["t"] for c in rows[2]] == ["식비", "25,000"]
    assert [c["t"] for c in rows[3]] == ["교통비", "실비"]
    assert rows[4][0]["rs"] == 1


def test_docx_vmerge_html_and_text():
    r = ri.convert("a.docx", _vmerge_doc(), "t", {})
    assert '<td rowspan="3">여비</td>' in r["view_html"]
    assert r["view_html"].count("<td></td>") == 0
    lines = r["text"].splitlines()
    assert "여비 | 숙박비 | 70,000" in lines and "식비 | 25,000" in lines
    assert not any(l.startswith(" | ") for l in lines)


def test_docx_vmerge_with_gridspan_column_position():
    doc = _docx([
        [_tc("가", gs=2), _tc("나", "restart")],
        [_tc("다"), _tc("라"), _tc("", "cont")],
    ])
    rows = [b for b in ri._docx_blocks(doc) if b["type"] == "table"][0]["rows"]
    assert rows[0][1]["t"] == "나" and rows[0][1]["rs"] == 2
    assert [c["t"] for c in rows[1]] == ["다", "라"]


# 4. 부칙·별지 뒤의 제1조는 본문 조와 앵커 id가 겹치지 않는다
def test_article_anchor_ids_unique_after_addenda_and_forms():
    h = _view(["제1조(목적) 이 규정은", "제2조(정의) 뜻은", "부칙 <2024.1.1.>", "제1조(시행일) 이 규정은",
               "[별지 제1호서식] 용역 계약서", "제1조(목적) 이 계약은", "제2조(정의) 이 계약에서",
               "부칙", "제1조(시행일) 다시"])
    ids = re.findall(r'<h3 class="art" id="([^"]+)"', h)
    assert len(ids) == 6 and len(set(ids)) == 6
    assert ids[:2] == ["a-1", "a-2"]
    assert all(not re.fullmatch(r"a-\d+(?:-\d+)?", i) for i in ids[2:])
    assert re.search(r'<h3 class="art" id="a-1">제1조\(목적\) 이 규정은</h3>', h)


def test_docx_vmerge_row_fully_continued_keeps_rowspan_consistent():
    doc = _docx([
        [_tc("가", "restart"), _tc("나", "restart"), _tc("다")],
        [_tc("", "cont"), _tc("", "cont"), _tc("라")],
        [_tc("", "cont"), _tc("", "cont")],
        [_tc("마"), _tc("바"), _tc("사")],
    ])
    rows = [b for b in ri._docx_blocks(doc) if b["type"] == "table"][0]["rows"]
    assert len(rows) == 3
    assert rows[0][0]["rs"] == 2 and rows[0][1]["rs"] == 2
    assert [c["t"] for c in rows[2]] == ["마", "바", "사"]


def test_article_anchor_duplicate_tail_does_not_collide_with_branch_article():
    """같은 구역에 제1조가 또 나와도 꼬리표가 제1조의2(a-1-2)와 겹치지 않는다."""
    h = _view(["제1조(목적) 가", "제1조(목적) 다시", "제1조의2(특례) 나"])
    ids = re.findall(r'<h3 class="art" id="([^"]+)"', h)
    assert ids == ["a-1", "a-1~2", "a-1-2"] and len(set(ids)) == 3, ids
