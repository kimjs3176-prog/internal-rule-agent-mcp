"""내규 들여오기(reg_import·import_regulations·notation·build_embeddings) 검토 지적 회귀 시험."""
import importlib.util
import io
import json
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import notation  # noqa: E402
import reg_chunks  # noqa: E402
import reg_import as ri  # noqa: E402

HP = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
     'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"')


def _zip(name, xml):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, xml)
    return b.getvalue()


def hwpx(body):
    return _zip("Contents/section0.xml", f"<hs:sec {HP}>{body}</hs:sec>")


def docx(body):
    return _zip("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")


def P(t):
    return f"<hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>"


def TC(inner, cs=1, rs=1):
    return f'<hp:tc><hp:cellSpan colSpan="{cs}" rowSpan="{rs}"/><hp:subList>{inner}</hp:subList></hp:tc>'


def TBL(*rows):
    return "<hp:p><hp:run><hp:tbl>" + "".join(f"<hp:tr>{''.join(r)}</hp:tr>" for r in rows) + "</hp:tbl></hp:run></hp:p>"


def _imp():
    spec = importlib.util.spec_from_file_location("imp_rf", os.path.join(ROOT, "scripts", "import_regulations.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """가짜 저장소 기본 위치(BASE_DIR) — 실제 저장소 데이터는 건드리지 않는다."""
    base = tmp_path / "repo"
    base.mkdir()
    monkeypatch.setattr(ri, "BASE_DIR", str(base))
    monkeypatch.setattr(ri, "REG_DIR", str(base / "regulations"))
    monkeypatch.setattr(ri, "REG_MANIFEST_PATH", str(base / "regulations_manifest.json"))
    return base


def _src(tmp_path, files):
    d = tmp_path / "src"
    d.mkdir(exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
    return str(d)


# 1. REG_DIR 만 바꾸고 REG_MANIFEST 는 기본값이면 --force 없이 기본 매니페스트를 덮어쓰지 않는다
def test_reset_refuses_default_manifest_when_only_reg_dir_set(tmp_path, repo, monkeypatch, capsys):
    man = repo / "regulations_manifest.json"
    man.write_text(json.dumps([{"title": "여비규정", "slug": "여비규정"}], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ri, "REG_DIR", str(tmp_path / "other" / "regulations"))
    src = _src(tmp_path, {"복무규정.txt": "제1조(목적) 가."})
    assert _imp().main([src, "--reset"]) == 3
    assert "멈춤" in capsys.readouterr().out
    assert json.loads(man.read_text(encoding="utf-8")) == [{"title": "여비규정", "slug": "여비규정"}]
    assert not any(p.startswith("regulations_manifest.json.backup-") for p in os.listdir(repo))
    # 둘 다 바꾸면 그대로 진행
    monkeypatch.setattr(ri, "REG_MANIFEST_PATH", str(tmp_path / "other" / "manifest.json"))
    assert _imp().main([src, "--reset"]) == 0
    assert json.loads(man.read_text(encoding="utf-8")) == [{"title": "여비규정", "slug": "여비규정"}]


# 2. 깨진 매니페스트를 빈 목록으로 읽어 다음 저장에 덮어쓰지 않는다
def test_load_manifest_missing_vs_corrupt(repo, monkeypatch, caplog):
    assert ri.load_manifest() == []
    (repo / "regulations_manifest.json").write_text("[{\"title\": ", encoding="utf-8")
    with pytest.raises(ValueError, match="매니페스트"):
        ri.load_manifest()
    # 읽기 전용(검색) 쪽은 서버가 멈추지 않게 기록만 남기고 빈 목록
    monkeypatch.setattr(reg_chunks, "MANIFEST", str(repo / "regulations_manifest.json"))
    assert reg_chunks.load_manifest() == []
    assert "매니페스트" in caplog.text
    monkeypatch.setattr(reg_chunks, "MANIFEST", str(repo / "none.json"))
    assert reg_chunks.load_manifest() == []


def test_import_stops_on_corrupt_manifest(tmp_path, repo, capsys):
    (repo / "regulations_manifest.json").write_text("{broken", encoding="utf-8")
    src = _src(tmp_path, {"복무규정.txt": "제1조(목적) 가."})
    assert _imp().main([src]) == 3
    assert "매니페스트를 읽을 수 없습니다" in capsys.readouterr().out
    assert not (repo / "regulations").exists()
    assert (repo / "regulations_manifest.json").read_text(encoding="utf-8") == "{broken"


# 3. 이름에서 글자가 다 빠지면 REG_DIR 바로 아래에 쓰지 않는다
@pytest.mark.parametrize("title", ["___", "..", "?*", ".", "  "])
def test_empty_slug_rejected(repo, title):
    with pytest.raises(ValueError):
        ri.reg_slug(title)
    with pytest.raises(ValueError):
        ri.write_reg("", "<p>x</p>", "x", "a.txt", b"x")


def test_import_skips_empty_slug_file(tmp_path, repo):
    src = _src(tmp_path, {"___(개정).txt": "제1조(목적) 가.", "복무규정.txt": "제1조(목적) 나."})
    assert _imp().main([src]) == 2
    assert not (repo / "regulations" / "index.html").exists()
    assert [m["title"] for m in json.loads((repo / "regulations_manifest.json").read_text(encoding="utf-8"))] == ["복무규정"]


# 4. 한 번에 들여오는 파일 중 같은 규정명(공백 차이 포함)은 알리고 넘기지 않는다
def test_duplicate_titles_reported(tmp_path, repo, capsys):
    src = _src(tmp_path, {"CCTV운영지침.txt": "제1조(목적) 가.", "CCTV 운영 지침(2025 개정).txt": "제1조(목적) 나.",
                          "복무규정.txt": "제1조(목적) 다."})
    assert _imp().main([src]) == 2
    out = capsys.readouterr().out
    assert "CCTV운영지침.txt" in out and "CCTV 운영 지침(2025 개정).txt" in out and "같은 규정명" in out
    man = json.loads((repo / "regulations_manifest.json").read_text(encoding="utf-8"))
    assert [m["title"] for m in man] == ["복무규정"]


def test_slug_reuses_existing_entry_for_whitespace_variant(tmp_path, repo):
    src = _src(tmp_path, {"CCTV 운영 지침.txt": "제1조(목적) 가."})
    assert _imp().main([src]) == 0
    os.remove(os.path.join(src, "CCTV 운영 지침.txt"))
    (tmp_path / "src" / "CCTV운영지침.txt").write_text("제1조(목적) 나.", encoding="utf-8")
    assert _imp().main([src]) == 0
    man = json.loads((repo / "regulations_manifest.json").read_text(encoding="utf-8"))
    assert len(man) == 1 and man[0]["slug"] == "CCTV_운영_지침"
    assert os.listdir(repo / "regulations") == ["CCTV_운영_지침"]
    assert "나." in (repo / "regulations" / "CCTV_운영_지침" / "text.txt").read_text(encoding="utf-8")


# 5. 다시 들여올 때 옛 파생 값(original·searchable·pdf)이 남지 않는다
def test_upsert_drops_stale_derived_keys():
    man = [{"title": "여비규정", "slug": "여비규정", "pdf": "pdf/여비규정.pdf", "original": "original.pdf",
            "searchable": False, "department": "총무팀"}]
    out = ri.upsert(man, {"title": "여비 규정", "slug": "여비규정", "src": "여비 규정.hwpx"})
    assert out[0] == {"title": "여비 규정", "slug": "여비규정", "src": "여비 규정.hwpx", "department": "총무팀"}


# 6. 머리말·꼬리말·각주·미주는 본문 단락에 끼어들지 않는다
def test_hwpx_header_footnote_not_in_body():
    body = (P("제1조(목적) 이 규정은")
            + "<hp:p><hp:run><hp:ctrl><hp:header><hp:subList>" + P("- 머리말 -") + "</hp:subList></hp:header></hp:ctrl>"
            "<hp:t>본문앞</hp:t><hp:ctrl><hp:footNote><hp:subList>" + P("각주내용") + "</hp:subList></hp:footNote></hp:ctrl>"
            "<hp:ctrl><hp:footer><hp:subList>" + P("꼬리말") + "</hp:subList></hp:footer></hp:ctrl>"
            "<hp:ctrl><hp:endNote><hp:subList>" + P("미주") + "</hp:subList></hp:endNote></hp:ctrl>"
            "<hp:t>본문뒤</hp:t></hp:run></hp:p>")
    texts = [b["text"] for b in ri._hwpx_blocks(hwpx(body)) if b["text"]]
    assert texts == ["제1조(목적) 이 규정은", "본문앞본문뒤"]


# 7. 표 안의 표: 안쪽 행이 바깥 행으로 새지 않고, 병합 정보는 자기 셀 것만
def test_nested_table_rows_and_spans():
    inner = TBL([TC(P("내부A"), cs=3), TC(P("내부B"))])
    outer = TBL([TC(P("구분")), TC(P("내용"))], [TC(P("항목")), TC(inner)])
    tbls = [b for b in ri._hwpx_blocks(hwpx(outer)) if b["type"] == "table"]
    assert len(tbls) == 1
    rows = tbls[0]["rows"]
    assert len(rows) == 2
    assert [(c["t"], c["cs"]) for c in rows[1]] == [("항목", 1), ("내부A 내부B", 1)]
    h = ri._table_html(rows)                         # 열람 화면: 안쪽 표는 그 셀 안에 한 번만
    assert h.count("내부A") == 1 and h.count("<table>") == 2 and 'colspan="3"' in h


def test_wrapper_one_cell_table_keeps_inner_table():
    inner = TBL([TC(P("구분")), TC(P("내용"))], [TC(P("한도")), TC(P("월100만원"))])
    blocks = ri._hwpx_blocks(hwpx(TBL([TC(P("안내") + inner)])))
    assert [b["rows"] for b in blocks if b["type"] == "table"][0][1][1]["t"] == "월100만원"
    assert "안내" in [b.get("text") for b in blocks]


def test_bad_colspan_defaults_to_one():
    t = TBL([TC(P("가나"), cs="abc"), TC(P("다라"))], [TC(P("1")), TC(P("2"))])
    rows = [b for b in ri._hwpx_blocks(hwpx(t)) if b["type"] == "table"][0]["rows"]
    assert [c["cs"] for c in rows[0]] == [1, 1]


# 8. DOCX 글상자(mc:Choice/mc:Fallback) 한 번만, 탭은 띄어쓰기로
def test_docx_textbox_once_and_tab():
    tb = "<w:txbxContent><w:p><w:r><w:t>글상자</w:t></w:r></w:p></w:txbxContent>"
    body = (f"<w:p><w:r><w:t>제1조(목적)</w:t></w:r><w:r><mc:AlternateContent><mc:Choice Requires=\"wps\">"
            f"<w:drawing>{tb}</w:drawing></mc:Choice><mc:Fallback><w:pict>{tb}</w:pict></mc:Fallback>"
            f"</mc:AlternateContent></w:r></w:p>"
            "<w:p><w:pPr><w:tabs><w:tab w:val=\"left\" w:pos=\"800\"/></w:tabs></w:pPr>"
            "<w:r><w:t>1.</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>정관</w:t></w:r></w:p>")
    texts = [b["text"] for b in ri._docx_blocks(docx(body)) if b["text"]]
    assert texts == ["제1조(목적)글상자", "1. 정관"]


def test_docx_tab_in_table_cell():
    cell = lambda inner: f"<w:tc><w:p>{inner}</w:p></w:tc>"
    body = ("<w:tbl><w:tr>" + cell("<w:r><w:t>가</w:t><w:tab/><w:t>나</w:t></w:r>") + cell("<w:r><w:t>다라</w:t></w:r>")
            + "</w:tr><w:tr>" + cell("<w:r><w:t>1</w:t></w:r>") + cell("<w:r><w:t>2</w:t></w:r>") + "</w:tr></w:tbl>")
    rows = [b for b in ri._docx_blocks(docx(body)) if b["type"] == "table"][0]["rows"]
    assert rows[0][0]["t"] == "가 나"


# 9. 한 글자 자료 셀(수/우/미 등)은 합치지 않고, 빈 칸 사이 글자 쪼갠 라벨만 합친다
def _r(*ts):
    return [{"t": t, "cs": 1, "rs": 1} for t in ts]


def test_merge_char_cells_keeps_data_cells():
    rows = [_r("등급", "수", "우", "미"), _r("평가", "상", "중", "하"), _r("유", "무"),
            _r("응시 번호", "성명", "가", "나", "다", "합격"), _r("건", "건", "건")]
    ri._merge_char_cells(rows)
    assert [[c["t"] for c in r] for r in rows] == [
        ["등급", "수", "우", "미"], ["평가", "상", "중", "하"], ["유", "무"],
        ["응시 번호", "성명", "가", "나", "다", "합격"], ["건", "건", "건"]]


def test_merge_char_cells_layout_label_still_merged():
    # 보직관리기준 경력개발 도식: 빈 칸 사이에 '활|용|기' 가 한 글자씩
    rows = [_r("", "", "", "활", "용", "기", "")]
    ri._merge_char_cells(rows)
    assert [c["t"] for c in rows[0]] == ["", "", "", "활용기", ""]
    assert sum(c["cs"] for c in rows[0]) == 7


# 10. HTML 업로드: <meta charset> 와 CP949 를 따른다
def test_html_upload_cp949():
    raw = '<html><head><meta charset="euc-kr"></head><body><p>제1조(목적) 이 규정은</p></body></html>'.encode("cp949")
    r = ri.convert("a.html", raw, "t", {})
    assert "제1조(목적) 이 규정은" in r["text"] and not r["warning"]
    raw = '<html><body><p>제1조(목적) 이 규정은</p></body></html>'.encode("cp949")
    assert "제1조(목적) 이 규정은" in ri.convert("a.htm", raw, "t", {})["text"]
    raw = '<html><body><p>제1조(목적) 가</p></body></html>'.encode("utf-8")
    assert "제1조(목적) 가" in ri.convert("a.html", raw, "t", {})["text"]


# 11. 금액 규칙: ‘계약금’의 금·‘원장’·‘원칙’은 금액 표기가 아니다
def test_money_rule_false_positives():
    for s in ("2026 원장은 이를 승인한다.", "예산 1000 원칙에 따라", "계약금 30,000원(금삼만원)",
              "2025 원년으로 한다", "계약금 30000원을 지급한다"):
        hits = [(x["match"], x["suggest"]) for x in notation.check(s, "law") if x["rule"] == "MONEY"]
        if s.startswith("계약금 30000"):
            assert hits == [("30000원", "금30,000원(금삼만원)")], hits
        else:
            assert hits == [], (s, hits)
    assert [x["rule"] for x in notation.check("금액은 30000원으로 한다", "law")] == ["MONEY"]
    assert [x["rule"] for x in notation.check("금 30,000원(금삼만원)을 지급", "law")] == ["MONEY"]
    assert [x["rule"] for x in notation.check("수수료 5000원", "law")] == ["MONEY"]


# 12. 쓰기 중 실패해도 옛 파일이 반쯤 쓰인 채 남지 않는다 / 쿼터 외 오류에도 진행분 저장
def test_write_reg_atomic(repo, monkeypatch):
    ri.write_reg("r", "<p>v1</p>", "제1조(목적) 옛 본문", "a.hwpx", b"old")
    real = os.replace

    def boom(src, dst):
        if dst.endswith("index.html"):
            raise OSError("disk full")
        return real(src, dst)
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        ri.write_reg("r", "<p>v2</p>", "제1조(목적) 새 본문", "a.hwpx", b"new")
    d = repo / "regulations" / "r"
    assert (d / "index.html").read_text(encoding="utf-8") == "<p>v1</p>"
    assert not [p for p in os.listdir(d) if ".tmp" in p]


def _be():
    spec = importlib.util.spec_from_file_location("be_rf", os.path.join(ROOT, "scripts", "build_embeddings.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_build_embeddings_saves_on_non_quota_error(tmp_path, monkeypatch):
    be = _be()
    monkeypatch.setattr(be, "BIN_PATH", str(tmp_path / "v.bin"))
    monkeypatch.setattr(be, "META_PATH", str(tmp_path / "v.json"))
    monkeypatch.setattr(be, "BATCH", 1)
    monkeypatch.setattr(be, "SLEEP", 0)
    monkeypatch.setattr(be, "FLUSH_EVERY", 0)
    chunks = [{"slug": "s", "title": "T", "no": str(i), "art_title": "", "boiler": False, "text": f"T 제{i}조 본문{i}"}
              for i in range(1, 4)]
    monkeypatch.setattr(be.rc, "iter_chunks", lambda: iter(chunks))
    calls = []

    def fake(texts, *a, **k):
        calls.append(texts)
        if len(calls) == 2:
            raise RuntimeError("임베딩 실패: 400 bad")
        return [[1.0, 0.0, 0.0] for _ in texts]
    monkeypatch.setattr(be, "embed_batch", fake)
    monkeypatch.setattr(sys, "argv", ["be", "--api-key", "x", "--dim", "3"])
    with pytest.raises(RuntimeError):
        be.main()
    meta = json.loads((tmp_path / "v.json").read_text(encoding="utf-8"))
    assert meta["count"] == 1 and os.path.getsize(tmp_path / "v.bin") == 3
    assert not [p for p in os.listdir(tmp_path) if ".tmp" in p]


# 13. 탭·줄바꿈 같은 제어 문자 참조로 숨긴 javascript: 도 막는다
@pytest.mark.parametrize("h", ['<a href="java&#9;script:alert(1)">x</a>', '<a href="java&#x0A;script:alert(1)">x</a>',
                               '<a href="&#32;javascript:alert(1)">x</a>', '<a href="jav&#x61;script:alert(1)">x</a>',
                               "<a href='java&#13;script:alert(1)'>x</a>", '<a href="java&Tab;script&colon;alert(1)">x</a>'])
def test_sanitize_entity_whitespace_scheme(h):
    out = ri._sanitize_html(h)
    assert "alert" not in out and "script:" not in out.replace("&#", ""), out


def test_sanitize_keeps_normal_links():
    assert ri._sanitize_html('<a href="https://ex.kr/a?b=1&amp;c=2">x</a>') == '<a href="https://ex.kr/a?b=1&amp;c=2">x</a>'
