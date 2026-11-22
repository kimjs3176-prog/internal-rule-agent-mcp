"""기관 내규 원문 → 에이전트 데이터(regulations/<slug>/ + regulations_manifest.json) 변환.

HWPX·HWP·DOCX·HTML·TXT·MD(·PDF는 원본 열람, 글자 층이 있으면 검색용 본문)를 조문 단위로 다룰 수 있는 열람 HTML과
본문 텍스트(text.txt)로 바꾼다. 다른 기관이 자기 내규를 들여올 때는
`python scripts/import_regulations.py <폴더>` 를 쓰면 된다(이 모듈을 사용).
"""
from __future__ import annotations

import io as _io
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

import hwp5
from datetime import datetime, timedelta, timezone

try:
    import defusedxml.ElementTree as _DET

    def _xml_fromstring(s):
        return _DET.fromstring(s)
except Exception:  # pragma: no cover
    def _xml_fromstring(s):
        return ET.fromstring(s)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REG_DIR = os.environ.get("REG_DIR") or os.path.join(BASE_DIR, "regulations")
REG_MANIFEST_PATH = os.environ.get("REG_MANIFEST") or os.path.join(BASE_DIR, "regulations_manifest.json")
ALLOWED_EXT = {".hwpx", ".hwp", ".docx", ".pdf", ".html", ".htm", ".txt", ".md"}
_KST = timezone(timedelta(hours=9))


def _decode(raw: bytes) -> str:
    """텍스트 파일 디코딩. 알 수 없는 인코딩·이진 파일은 깨진 글자로 받지 않고 거부한다(fail closed)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    elif b"\x00" not in raw[:4096]:
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                t = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            bad = sum(1 for ch in t[:20000] if ord(ch) < 32 and ch not in "\t\n\r\f")
            if bad <= max(2, len(t[:20000]) // 500):
                return t
            break
    raise ValueError("텍스트 파일을 읽을 수 없습니다. 한글 문서라면 UTF-8 또는 CP949(ANSI)로 저장해 올리거나 HWPX·DOCX로 올려 주세요.")


# 규정명 끝말 → 내규 체계상의 구분.
# 기관 내규는 정관 > 규정 > 규칙 > 세칙 > 예규 순이고,
# 지침·요령·기준·수칙·계획 등 하위 문서는 모두 예규로 묶는다.
_REG_CAT_SUFFIX = (
    ("정관", "정관"),
    ("규정", "규정"),
    ("규칙", "규칙"),
    ("세칙", "세칙"),
    ("예규", "예규"),
    ("지침", "예규"), ("요령", "예규"), ("기준", "예규"), ("수칙", "예규"),
    ("준칙", "예규"), ("규준", "예규"), ("요강", "예규"), ("계획", "예규"),
    ("매뉴얼", "매뉴얼"), ("편람", "매뉴얼"), ("가이드", "매뉴얼"),
    ("안내서", "매뉴얼"), ("핸드북", "매뉴얼"),
)


def guess_category(title: str) -> str:
    """규정명으로 구분을 추정. 판단이 서지 않으면 '기타'.

    정관은 기관당 1건뿐이므로 이름이 '정관'으로 끝날 때만 인정한다.
    (예전에는 업로드 폼의 첫 선택지가 정관이라 '보직관리기준'처럼
     끝말이 목록에 없는 규정이 그대로 정관으로 등록되는 사고가 있었다.)
    """
    t = re.sub(r"\s+", "", (title or ""))
    t = re.sub(r"[(（\[【].*$", "", t)          # 뒤에 붙은 (제정 …)·[별표] 등 제거
    for suf, cat in _REG_CAT_SUFFIX:
        if t.endswith(suf):
            return cat
    return "기타"


def now_kst() -> str:
    return datetime.now(_KST).strftime("%Y-%m-%d %H:%M")


def reg_slug(title: str) -> str:
    """규정명 → 디렉터리 슬러그. 기존 manifest 규칙(공백→_)을 따른다."""
    s = unicodedata.normalize("NFC", (title or "").strip())
    s = re.sub(r"[\\/:*?\"<>|#%\x00-\x1f\x7f]+", "", s)   # 경로·윈도우 금지문자·URL 예약문자·제어문자 제거
    s = re.sub(r"\s+", "_", s).strip("._")
    # 파일시스템 이름 한도(255바이트) 안에서 자른다 — 한글은 글자당 3바이트
    b = s.encode("utf-8")[:200]
    s = b.decode("utf-8", "ignore").strip("._")
    if not s:                                         # 빈 슬러그면 REG_DIR 바로 아래에 쓰게 된다
        raise ValueError(f"규정명으로 폴더 이름을 만들 수 없습니다: {title!r} — 글자가 있는 규정명으로 바꿔 주세요.")
    return s


def slug_for(man: list, title: str) -> str:
    """같은 규정(norm_key)이 매니페스트에 있으면 그 슬러그를, 없으면 새 슬러그.
    'CCTV운영지침'·'CCTV 운영 지침'처럼 띄어쓰기만 다른 이름이 다른 폴더로 갈라지지 않게 한다."""
    key = norm_key(title)
    for m in man:
        if m.get("slug") and norm_key(m.get("title", "")) == key:
            return m["slug"]
    return reg_slug(title)



# ── 문서 → 블록(단락·표) 추출 ────────────────────────────────────────────────
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# 본문 흐름이 아닌 하위 트리: HWPX 머리말·꼬리말·각주·미주, DOCX 호환용 대체 그림(mc:Fallback — mc:Choice 와 같은 글이 한 번 더)
_SKIP_TAGS = {"header", "footer", "footNote", "endNote", "Fallback"}


def _xml_blocks(root: ET.Element, para_tag: str, table_tag: str,
                row_tag: str, cell_tag: str, text_tags: set,
                break_tags: set) -> list:
    """
    OWPML(HWPX)·OOXML(DOCX) 공통 블록 추출.
    표는 단락 안에 중첩되어 나타나므로(HWPX: p > run > tbl) 표를 만나면
    앞까지의 텍스트를 단락으로 끊고 표 블록을 따로 만든다 — 표가 줄글로 풀리지 않게.
    """
    blocks = []
    buf = []

    def flush():
        txt = re.sub(r"[ \t]+", " ", "".join(buf)).strip()
        buf.clear()
        if not txt:
            blocks.append({"type": "p", "text": ""})
            return
        for line in txt.split("\n"):
            blocks.append({"type": "p", "text": line.strip()})

    def tag_text(el: ET.Element) -> str:
        """글자 태그 안의 글. HWPX 의 <hp:t>는 <hp:tab/>·<hp:lineBreak/> 등을 품고 그 뒤 글을 tail 에 둔다."""
        out = [el.text or ""]
        for sub in el:
            n = _local(sub.tag)
            out.append("\n" if n in break_tags or n == "lineBreak" else " " if n in ("tab", "nbSpace", "fwSpace") else "")
            out.append(sub.tail or "")
        return "".join(out)

    def is_tab(el: ET.Element, parent: ET.Element) -> bool:
        """DOCX 본문 탭(<w:r><w:tab/>). 단락 속성의 탭 위치 정의(<w:tabs><w:tab/>)는 제외."""
        return _local(el.tag) == "tab" and _local(parent.tag) != "tabs"

    def cell_text(tc: ET.Element) -> str:
        parts = []

        def go(node):                                # 안쪽 표의 글도 이 셀 안에 한 번만 담긴다
            for el in node:
                t = _local(el.tag)
                if t in _SKIP_TAGS:
                    continue
                if t in text_tags:
                    parts.append(tag_text(el))
                    continue
                if is_tab(el, node):
                    parts.append(" ")
                    continue
                if t == para_tag and parts:
                    parts.append(" ")
                go(el)
        go(tc)
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def own(node: ET.Element, tag: str):
        """node 아래의 tag 요소 — 안쪽 표(table_tag) 속은 들어가지 않는다."""
        for el in node:
            n = _local(el.tag)
            if n == tag:
                yield el
            elif n != table_tag:
                yield from own(el, tag)

    def _int(v) -> int:
        try:
            return int(v or 1)
        except (TypeError, ValueError):
            return 1

    def cell_span(tc: ET.Element):
        """셀 병합 정보(colspan, rowspan). HWPX는 hp:cellSpan, DOCX는 gridSpan/vMerge. 안쪽 표의 병합은 보지 않는다."""
        cs = rs = 1
        for sub in own(tc, "cellSpan"):              # HWPX
            cs, rs = _int(sub.get("colSpan")), _int(sub.get("rowSpan"))
        for sub in own(tc, "gridSpan"):              # DOCX
            vals = list(sub.attrib.values())
            if vals:
                cs = _int(vals[0])
        return max(cs, 1), max(rs, 1)

    def table_block(tbl: ET.Element):
        rows, el_of = [], {}
        for tr in own(tbl, row_tag):
            cells = []
            for tc in tr:
                if _local(tc.tag) != cell_tag:
                    continue
                cs, rs = cell_span(tc)
                cells.append({"t": cell_text(tc), "cs": cs, "rs": rs})
                if next(own(tc, table_tag), None) is not None:   # 표 안의 표: 열람 화면에서 그 셀 안에 표로 한 번만
                    cells[-1]["blocks"] = _xml_blocks(tc, para_tag, table_tag, row_tag, cell_tag,
                                                      text_tags, break_tags)
                el_of[id(cells[-1])] = tc
            if cells:
                rows.append(cells)
        _merge_char_cells(rows)      # 세로쓰기로 글자마다 쪼개진 셀 복원
        while rows and not any(c["t"] for c in rows[0]):   # 앞뒤 빈 행 제거
            rows.pop(0)
        while rows and not any(c["t"] for c in rows[-1]):
            rows.pop()
        if not rows:
            return None
        # 1열 표는 제목·안내 박스로 쓰인 레이아웃 표 → 표 대신 단락으로
        if max(sum(c["cs"] for c in r) for r in rows) <= 1:
            for r in rows:
                tc = el_of.get(id(r[0])) if r else None
                if tc is not None and next(own(tc, table_tag), None) is not None:
                    walk(tc, False)           # 표를 감싼 틀: 안쪽 표를 표 그대로 꺼낸다
                    if buf:
                        flush()
                    continue
                blocks.append({"type": "p", "text": (r[0]["t"] if r else "").strip()})
            return None
        return {"type": "table", "rows": rows}

    def walk(node, in_para: bool):
        for child in list(node):
            tag = _local(child.tag)
            if tag in _SKIP_TAGS:
                continue
            if is_tab(child, node):
                buf.append(" ")
                continue
            if tag == table_tag:
                flush()                       # 표 앞 텍스트를 단락으로 마무리
                tb = table_block(child)
                if tb:
                    blocks.append(tb)
                continue
            if tag == para_tag and not in_para:
                buf.clear()
                walk(child, True)
                flush()
                continue
            if tag in text_tags:
                buf.append(tag_text(child))
                continue
            if tag in break_tags:
                buf.append("\n")
                continue
            walk(child, in_para)

    walk(root, False)
    if buf:
        flush()
    return blocks


# 업로드 zip(HWPX/DOCX) 압축 해제 폭탄(zip bomb) 방어용 상한
_ZIP_ENTRY_MAX = 80 * 1024 * 1024     # 단일 항목 최대 80MB(압축 해제 기준)
_ZIP_TOTAL_MAX = 200 * 1024 * 1024    # 누적 읽기 최대 200MB


class _ZipBudget:
    """zip 항목의 압축 해제 크기를 검사하며 안전하게 읽는 헬퍼."""
    def __init__(self, z):
        self.z = z
        self.total = 0

    def read(self, name: str) -> bytes:
        data = safe_zip_read(self.z, name, min(_ZIP_ENTRY_MAX, _ZIP_TOTAL_MAX - self.total))
        self.total += len(data)
        return data


def safe_zip_read(z, name, limit: int) -> bytes:
    """zip 항목을 조금씩 풀며 실제로 나온 바이트 수로 상한을 지킨다.
    zip 이 스스로 적은 크기(file_size)는 속일 수 있으므로 믿지 않는다(zip bomb 방어)."""
    info = name if isinstance(name, zipfile.ZipInfo) else z.getinfo(name)
    if info.file_size > limit:
        raise ValueError("압축 해제 크기 제한 초과")
    if info.compress_size and info.file_size / max(1, info.compress_size) > 400:
        raise ValueError("압축률이 비정상적으로 높은 파일입니다.")
    out, n = [], 0
    with z.open(info) as f:
        while True:
            chunk = f.read(1 << 16)
            if not chunk:
                break
            n += len(chunk)
            if n > limit:
                raise ValueError("압축 해제 크기 제한 초과")
            out.append(chunk)
    return b"".join(out)


def _hwpx_blocks(raw: bytes) -> list:
    """HWPX(한/글 OWPML, zip) 본문 추출."""
    blocks = []
    with zipfile.ZipFile(_io.BytesIO(raw)) as z:
        budget = _ZipBudget(z)
        names = [n for n in z.namelist()
                 if re.match(r"Contents/section\d+\.xml$", n, re.I)]
        names.sort(key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        if not names:
            raise ValueError("HWPX 본문(Contents/section*.xml)을 찾을 수 없습니다.")
        for n in names:
            root = _xml_fromstring(budget.read(n))
            blocks += _xml_blocks(root, "p", "tbl", "tr", "tc",
                                  {"t"}, {"lineBreak"})
    return blocks


def _docx_blocks(raw: bytes) -> list:
    """DOCX(OOXML) 본문 추출."""
    with zipfile.ZipFile(_io.BytesIO(raw)) as z:
        budget = _ZipBudget(z)
        root = _xml_fromstring(budget.read("word/document.xml"))
    return _xml_blocks(root, "p", "tbl", "tr", "tc", {"t"}, {"br", "cr"})


def _text_blocks(text: str) -> list:
    return [{"type": "p", "text": l.rstrip()} for l in text.replace("\r\n", "\n").split("\n")]


_SCRIPT_RE = re.compile(
    r"<\s*(script|iframe|object|embed|applet|style)\b.*?<\s*/\s*\1\s*>",
    re.I | re.S)
_SCRIPT_OPEN_RE = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|applet|link|meta|base)\b[^>]*>", re.I)
_ON_ATTR_RE = re.compile(r"[\s/\"']on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)   # <svg/onload=…> 도
# srcdoc/formaction 은 스크립트 실행 경로가 되므로 속성째 제거
_DANGER_ATTR_RE = re.compile(
    r"\s(srcdoc|formaction)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_JS_URL_RE = re.compile(
    r"(href|src|action|xlink:href)\s*=\s*(\"|')\s*(?:javascript|data|vbscript):[^\"']*(\2)", re.I)
_JS_URL_BARE_RE = re.compile(r"(href|src|action|xlink:href)\s*=\s*(?:javascript|data|vbscript):[^\s>]*", re.I)
_ENTITY_RE = re.compile(r"&#(x[0-9a-f]+|\d+);?", re.I)


def _unentity_urls(html: str) -> str:
    """href/src 값 속 숫자 문자 참조(jav&#x61;script:)를 풀어 아래 검사에 걸리게 한다.
    브라우저는 URL 의 탭·줄바꿈을 버리고 앞뒤 공백·제어 문자를 걷으므로(java&#9;script:, &#32;javascript:)
    그렇게 걷어 낸 값이 위험한 스킴이면 걷어 낸 값으로 바꿔 둔다."""
    def dec(m):
        v = m.group(1)
        try:
            ch = chr(int(v[1:], 16) if v[0] in "xX" else int(v))
        except (ValueError, OverflowError):
            return m.group(0)
        return ch if ch.isascii() and (ch.isalnum() or ch in ":/") else m.group(0)

    def dec_all(m):
        v = m.group(1)
        try:
            return chr(int(v[1:], 16) if v[0] in "xX" else int(v))
        except (ValueError, OverflowError):
            return m.group(0)

    def fix(m):
        v = m.group(3)
        probe = _ENTITY_RE.sub(dec_all, v)
        probe = re.sub(r"(?i)&colon;", ":", re.sub(r"(?i)&(?:tab|newline);", "", probe))   # 이름 참조(java&Tab;script&colon;)
        probe = re.sub(r"^[\x00-\x20\x7f]+", "", re.sub(r"[\t\n\r]", "", probe))
        if re.match(r"(?:javascript|data|vbscript):", probe, re.I):
            return m.group(1) + m.group(2) + probe + m.group(2)
        return m.group(1) + m.group(2) + _ENTITY_RE.sub(dec, v) + m.group(2)
    html = re.sub(r"((?:href|src|action|xlink:href)\s*=\s*)(\"|')(.*?)\2", fix, html, flags=re.I | re.S)
    return re.sub(r"((?:href|src|action|xlink:href)\s*=\s*)()([^\"'\s>]+)",
                  fix, html, flags=re.I)


def _sanitize_html(html: str) -> str:
    """업로드된 HTML에서 스크립트·이벤트 핸들러 제거(같은 출처에서 서빙되므로 필수).

    이는 심층 방어(defense-in-depth)일 뿐, 실제 신뢰 경계는 업로드 토큰이다.
    <table>/<tr>/<td>/<span>/<p>/<div>/style="..." 등 규정 서식에 필요한 요소는
    의도적으로 보존한다.
    """
    out = _SCRIPT_RE.sub("", html)
    out = _SCRIPT_OPEN_RE.sub("", out)
    out = _ON_ATTR_RE.sub("", out)
    out = _DANGER_ATTR_RE.sub("", out)
    out = _unentity_urls(out)
    out = _JS_URL_RE.sub(r"\1=\2#\2", out)
    out = _JS_URL_BARE_RE.sub(r'\1="#"', out)
    return out


_ONE_HANGUL = re.compile(r"^[가-힣]$")


def _merge_char_cells(rows: list) -> list:
    """세로쓰기 라벨이 글자마다 별도 셀로 쪼개진 것을 한 셀로 합친다.

    한글 문서에서 '활 용 기' 같은 라벨은 칸을 나눠 글자를 하나씩 넣는 경우가 많다.
    그대로 두면 폭 좁은 빈 칸이 늘어서 표가 어수선해진다.
    합친 셀의 colspan 을 합계로 유지해 열 정렬은 그대로 둔다.
    (숫자·기호는 실제 자료일 수 있으므로 한글 한 글자만 대상으로 한다)
    수/우/미·상/중/하·유/무·가/나/다 같은 한 글자 자료 셀을 뭉치지 않도록, 그 행의 나머지 칸이
    모두 비어 있는(도식처럼 빈 칸 사이에 글자를 흩어 둔) 경우에만 합치고, 같은 글자 반복(건|건|건)은 두다.
    """
    for r in rows:
        out, i = [], 0
        while i < len(r):
            j = i
            while (j < len(r)
                   and _ONE_HANGUL.match((r[j]["t"] or "").strip())
                   and r[j]["rs"] == r[i]["rs"]):
                j += 1
            rest = r[:i] + r[j:]
            if (j - i >= 2 and rest and not any((c["t"] or "").strip() for c in rest)
                    and len({(c["t"] or "").strip() for c in r[i:j]}) > 1):
                out.append({"t": "".join((c["t"] or "").strip() for c in r[i:j]),
                            "cs": sum(c["cs"] for c in r[i:j]),
                            "rs": r[i]["rs"]})
                i = j
            else:
                out.append(r[i])
                i += 1
        r[:] = out
    return rows


def _blocks_to_text(blocks: list) -> str:
    lines = []
    for b in blocks:
        if b["type"] == "table":
            for row in b["rows"]:
                lines.append(" | ".join(c["t"] for c in row))
        else:
            lines.append(b.get("text", ""))
    # 3줄 이상 연속 공백 줄은 2줄로 압축
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


_ART_HEAD_RE = re.compile(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:\(|$|\s)")
_CHAP_HEAD_RE = re.compile(r"^제\s*\d+\s*(?:편|장|절|관)\b")
_APX_HEAD_RE = re.compile(r"^[\[［〔【<＜]?\s*(?:별표|별지|붙임|서식)")


def _table_html(rows: list) -> str:
    """병합(colspan/rowspan)을 반영해 표를 렌더. 첫 행이 머리글로 보일 때만 thead 사용."""
    def cells(row, tag):
        out = []
        for c in row:
            attr = ""
            if c["cs"] > 1:
                attr += f' colspan="{c["cs"]}"'
            if c["rs"] > 1:
                attr += f' rowspan="{c["rs"]}"'
            if c.get("blocks"):                       # 표 안의 표
                inner = "".join(_table_html(b["rows"]) if b["type"] == "table" else f"<p>{_esc(b['text'])}</p>"
                                for b in c["blocks"] if b["type"] == "table" or (b.get("text") or "").strip())
                out.append(f"<{tag}{attr}>{inner}</{tag}>")
                continue
            out.append(f'<{tag}{attr}>{_esc(c["t"])}</{tag}>')
        return "".join(out)

    if not rows:
        return ""
    # 머리글 판정: 첫 행이 모두 채워져 있고 짧으면 헤더로 본다.
    # (자료 행이 헤더로 올라가 열이 어긋나는 것을 막는다)
    first = rows[0]
    # 날짜·호수·순수 숫자가 있으면 머리글이 아니라 자료 행(예: 연혁 표의 '제정 2010.07.14 …')
    _data_like = re.compile(r"^\s*(?:\d{4}\s*[.\-]|제\s*[\d\-]+\s*호|[\d,]+)\s*\.?\s*$")
    is_head = (len(rows) > 1
               and all(c["t"].strip() for c in first)
               and all(len(c["t"]) <= 20 for c in first)
               and not any(c["rs"] > 1 for c in first)
               and not any(_data_like.match(c["t"]) for c in first))
    head = f"<thead><tr>{cells(first, 'th')}</tr></thead>" if is_head else ""
    body_rows = rows[1:] if is_head else rows
    tb = "".join(f"<tr>{cells(r, 'td')}</tr>" for r in body_rows)
    return f'<div class="tbl-wrap"><table>{head}<tbody>{tb}</tbody></table></div>'


def _blocks_to_view_html(title: str, meta: dict, blocks: list,
                         orig_name: str = "") -> str:
    """열람용 HTML 생성 — 조·장 제목을 구분해 기존 원본 뷰어와 동일하게 읽히도록."""
    body = []
    for b in blocks:
        if b["type"] == "table":
            body.append(_table_html(b["rows"]))
            continue
        t = (b.get("text") or "").strip()
        if not t:
            body.append('<p class="blank"></p>')
        elif _CHAP_HEAD_RE.match(t):
            body.append(f'<h2 class="chap">{_esc(t)}</h2>')
        elif _ART_HEAD_RE.match(t):
            body.append(f'<h3 class="art">{_esc(t)}</h3>')
        elif _APX_HEAD_RE.match(t):
            body.append(f'<h3 class="apx">{_esc(t)}</h3>')
        else:
            body.append(f"<p>{_esc(t)}</p>")

    metarows = "".join(
        f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>"
        for k, v in [("규정 구분", meta.get("category")),
                     ("개정 구분", meta.get("revision")),
                     ("시행일자", meta.get("effective_date")),
                     ("담당 부서", meta.get("department")),
                     ("원본 파일", orig_name),
                     ("업로드", meta.get("uploaded_at"))] if v)
    note = meta.get("note") or ""
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
 :root{{--tx:#1a1d21;--mu:#5b6472;--bd:#e5e8ec;--g:#1D9E75;--gl:#eafaf3;}}
 body{{font-family:'Malgun Gothic','맑은 고딕',system-ui,sans-serif;color:var(--tx);
   line-height:1.85;max-width:900px;margin:0 auto;padding:28px 26px 60px;font-size:15px;}}
 h1{{font-size:22px;text-align:center;margin:0 0 6px;letter-spacing:2px;}}
 .sub{{text-align:center;color:var(--mu);font-size:13px;margin-bottom:18px;}}
 .meta{{border-collapse:collapse;margin:0 auto 26px;font-size:13px;min-width:60%;}}
 .meta th,.meta td{{border:1px solid var(--bd);padding:5px 12px;text-align:left;}}
 .meta th{{background:var(--gl);color:var(--g);white-space:nowrap;font-weight:700;}}
 .note{{background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:8px 12px;
   font-size:13px;margin-bottom:22px;white-space:pre-wrap;}}
 h2.chap{{font-size:17px;margin:32px 0 12px;padding-bottom:5px;
   border-bottom:1px solid var(--bd);}}
 h3.art{{font-size:15px;margin:22px 0 6px;color:#0f172a;}}
 h3.apx{{font-size:15px;margin:26px 0 8px;color:var(--g);}}
 p{{margin:0 0 4px;white-space:pre-wrap;word-break:keep-all;}}
 p.blank{{height:8px;margin:0;}}
 .tbl-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:10px 0 18px;}}
 table{{border-collapse:collapse;font-size:12.5px;width:100%;table-layout:auto;}}
 th,td{{border:1px solid var(--bd);padding:5px 8px;vertical-align:top;
   word-break:keep-all;overflow-wrap:anywhere;line-height:1.55;}}
 thead th{{background:#f7f8fa;font-weight:700;text-align:center;}}
 /* 좁은 화면: 표를 원래 폭으로 두고 가로 스크롤(줄바꿈으로 뭉개지는 것 방지) */
 @media(max-width:820px){{ table{{width:auto;min-width:100%;}}
   th,td{{white-space:nowrap;}} }}
 @media print{{body{{padding:0;}}}}
</style></head><body>
<h1>{_esc(title)}</h1>
<div class="sub">{_esc(meta.get('revision') or '')}</div>
{f'<table class="meta">{metarows}</table>' if metarows else ''}
{f'<div class="note">{_esc(note)}</div>' if note else ''}
{chr(10).join(body)}
</body></html>"""


def _decode_html(raw: bytes) -> str:
    """HTML 업로드 디코딩: <meta charset>(euc-kr 등)을 먼저 따르고, 없으면 UTF-8 → CP949 순으로."""
    m = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9_\-]+)", raw[:4096], re.I)
    if m:
        enc = m.group(1).decode("ascii").lower()
        enc = "cp949" if enc in ("euc-kr", "euckr", "ks_c_5601-1987", "ksc5601") else enc   # 확장 완성형까지
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return _decode(raw)
    except ValueError:
        return raw.decode("utf-8", errors="replace")


def _convert_upload(filename: str, raw: bytes, title: str, meta: dict) -> dict:
    """업로드 파일 → {view_html, text, converted, warning}."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".html", ".htm"):
        html = _sanitize_html(_decode_html(raw))
        import html as _html_mod
        t = re.sub(r"(?is)<\s*(head|script|style|title)\b.*?<\s*/\s*\1\s*>", " ", html)
        t = re.sub(r"(?i)<\s*(br|/p|/div|/tr|/li|/h[1-6]|/table)\s*/?>", "\n", t)
        t = _html_mod.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\u00a0", " ")
        t = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in t.split("\n"))
        text = re.sub(r"\n{3,}", "\n\n", t).strip()
        warn = "" if re.search(r"제\s*\d+\s*조", text) else "HTML에서 “제N조” 형식의 조문을 찾지 못했습니다. 조문 검색·개정에 쓰려면 HWPX·DOCX로 올리세요."
        return {"view_html": html, "text": text, "converted": True, "warning": warn}
    if ext == ".hwpx":
        blocks = _hwpx_blocks(raw)
    elif ext == ".docx":
        blocks = _docx_blocks(raw)
    elif ext in (".txt", ".md"):
        blocks = _text_blocks(_decode(raw))
    elif ext == ".pdf":
        # F08: /regulations/* 의 CSP(object-src/frame-src 'none')는 <embed>/<iframe>
        # 인라인 PDF 표시를 차단한다. 전체 내규의 스크립트 차단을 풀지 않고, 원본 PDF를
        # 새 탭 열기·다운로드 링크로 제공한다(최상위 탐색은 CSP 영향을 받지 않음).
        src = "original.pdf"
        html = (f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{_esc(title)}</title><style>'
                f'body{{margin:0;font-family:system-ui,"Malgun Gothic",sans-serif;background:#f6f7f9;color:#1f2937;}}'
                f'.wrap{{max-width:640px;margin:8vh auto;padding:28px;background:#fff;'
                f'border:1px solid #e5e7eb;border-radius:14px;text-align:center;}}'
                f'.ic{{font-size:44px}}h1{{font-size:18px;margin:10px 0 6px}}'
                f'p{{color:#6b7280;font-size:14px;line-height:1.6}}'
                f'.btns{{margin-top:18px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap}}'
                f'a.btn{{display:inline-block;padding:11px 18px;border-radius:10px;'
                f'font-weight:700;text-decoration:none;font-size:14px}}'
                f'a.p{{background:#256ef4;color:#fff}}'
                f'a.s{{background:#eef2f7;color:#1f2937;border:1px solid #e5e7eb}}'
                f'</style></head><body><div class="wrap"><div class="ic">📄</div>'
                f'<h1>{_esc(title)}</h1>'
                f'<p>이 규정은 PDF 원본으로 등록되어 있습니다.<br>'
                f'아래 버튼으로 원문을 열람하거나 내려받을 수 있습니다.</p>'
                f'<div class="btns"><a class="btn p" href="{src}" target="_blank" rel="noopener">원본 PDF 열기</a>'
                f'<a class="btn s" href="{src}" download>다운로드</a></div>'
                f'<p style="margin-top:16px;font-size:12px">본문 검색이 필요하면 한/글에서 '
                f'HWPX 또는 DOCX로 저장해 다시 올려주세요.</p></div></body></html>')
        ptext = hwp5.pdf_text(raw)               # 글자 층이 있으면 본문 검색·개정에 쓴다(화면은 원본 PDF)
        if ptext and re.search(r"제\s*\d+\s*조", ptext):
            html = html.replace("본문 검색이 필요하면 한/글에서 HWPX 또는 DOCX로 저장해 다시 올려주세요.",
                                "본문은 PDF에서 뽑아 조문 검색·개정에 씁니다.")
            return {"view_html": html, "text": ptext, "converted": False,
                    "warning": "PDF에서 글자를 뽑아 본문 검색에 씁니다. 줄바꿈이 어긋날 수 있으니 조문을 확인하세요."}
        return {"view_html": html, "text": "", "converted": False,
                "warning": "PDF는 원본 열기·다운로드로 제공됩니다. 본문 검색이 필요하면 HWPX 또는 DOCX로 올려주세요."}
    elif ext == ".hwp":
        try:                                      # HWP 5.0 본문 추출(암호·배포용·HWP 3.x 는 안내)
            blocks = [{"type": "p", "text": ln} for ln in hwp5.hwp_text(raw).split("\n")]
        except ValueError as e:
            blocks, hwp_err = [], str(e)
        else:
            hwp_err = "" if any(b["text"] for b in blocks) else "본문 글자가 없습니다."
    else:
        raise ValueError(f"지원하지 않는 형식입니다: {ext}")

    if ext == ".hwp" and not hwp_err:
        return {"view_html": _blocks_to_view_html(title, meta, blocks, orig_name=filename),
                "text": _blocks_to_text(blocks), "converted": True,
                "warning": "HWP(구버전)에서 본문을 뽑았습니다. 표·각주 배치가 원본과 다를 수 있습니다."}
    if ext == ".hwp":
        failed = True
        html = _blocks_to_view_html(
            title, meta,
            [{"type": "p", "text": "이 규정은 구버전 HWP(바이너리) 형식으로 업로드되어 "
                                   "본문을 자동 변환하지 못했습니다."},
             {"type": "p", "text": "한/글에서 '다른 이름으로 저장 → HWPX'로 저장해 다시 올리면 "
                                   "본문까지 조회·검색됩니다. 원본 파일은 아래 링크로 내려받을 수 있습니다."}],
            orig_name=filename)
        return {"view_html": html, "text": "", "converted": False, "failed": failed, "error": hwp_err,
                "warning": f"HWP 본문을 변환하지 못했습니다({hwp_err}). HWPX로 저장해 올리면 본문까지 검색됩니다."}

    text = _blocks_to_text(blocks)
    if not text:
        raise ValueError("본문 텍스트를 추출하지 못했습니다. 파일이 손상되었는지 확인해주세요.")
    warn = "" if re.search(r"제\s*\d+\s*조", text) else (
        "본문에서 “제N조” 형식의 조문을 찾지 못했습니다. 자동 번호(1조, 2조…)로 쓴 문서라면 조문 번호를 글자로 바꿔 다시 올려야 조문 검색·개정에 쓸 수 있습니다.")
    return {"view_html": _blocks_to_view_html(title, meta, blocks, orig_name=filename),
            "text": text, "converted": True, "warning": warn}



def norm_key(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).lower()


def load_manifest() -> list:
    """매니페스트 읽기. 파일이 없을 때만 빈 목록 — 깨진 파일을 빈 목록으로 읽으면 다음 저장 때 통째로 덮어쓴다."""
    try:
        with open(REG_MANIFEST_PATH, encoding="utf-8") as f:
            man = json.load(f)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"매니페스트를 읽을 수 없습니다({REG_MANIFEST_PATH}: {e}). "
                         "파일을 고치거나 백업(.backup-…)으로 되돌린 뒤 다시 실행하세요.") from e
    if not isinstance(man, list):
        raise ValueError(f"매니페스트 형식이 잘못되었습니다({REG_MANIFEST_PATH}: 목록이 아님).")
    return man


def save_manifest(man: list) -> None:
    """manifest 저장 — 기존 파일과 같은 포맷(indent=1)으로 써서 diff 를 최소화한다."""
    tmp = REG_MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, REG_MANIFEST_PATH)


def convert(filename: str, raw: bytes, title: str, meta: dict) -> dict:
    """파일 → {view_html, text, converted, warning}"""
    return _convert_upload(filename, raw, title, meta)


def _atomic_write(path: str, data) -> None:
    """임시 파일에 다 쓴 뒤 os.replace — 중간에 실패해도 옛 파일이 반쯤 쓰인 채 남지 않는다."""
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def write_reg(slug: str, view_html: str, text: str, orig_filename: str, raw: bytes) -> str:
    """regulations/<slug>/ 에 열람 HTML·본문·원본을 쓴다. 저장된 원본 파일명 반환."""
    if not slug or slug in (".", "..") or re.search(r"[\\/]", slug):
        raise ValueError(f"규정 폴더 이름이 올바르지 않습니다: {slug!r}")
    d = os.path.join(REG_DIR, slug)
    os.makedirs(d, exist_ok=True)
    _atomic_write(os.path.join(d, "index.html"), view_html)
    if text:
        _atomic_write(os.path.join(d, "text.txt"), text)
    elif os.path.exists(os.path.join(d, "text.txt")):
        os.remove(os.path.join(d, "text.txt"))       # 본문을 못 읽은 개정판(PDF·HWP)이면 옛 본문으로 개정·검색하지 않게 지운다
    ext = os.path.splitext(orig_filename)[1].lower()
    for fn_ in os.listdir(d):                         # 확장자가 다른 옛 원본은 지운다
        if fn_.startswith("original.") and os.path.splitext(fn_)[1].lower() != ext:
            os.remove(os.path.join(d, fn_))
    stored = f"original{ext}"
    _atomic_write(os.path.join(d, stored), raw)
    return stored


# 원본 파일에서 나온 값 — 새 원본으로 바꿀 때 옛 값이 남으면 엉뚱한 PDF·원본을 가리킨다
_DERIVED_KEYS = ("original", "searchable", "pdf")


def upsert(man: list, entry: dict) -> list:
    """같은 규정명이 있으면 교체, 없으면 추가(순서 유지)."""
    key = norm_key(entry["title"])
    for i, m in enumerate(man):
        if norm_key(m.get("title", "")) == key:
            kept = {k: v for k, v in m.items() if k not in _DERIVED_KEYS}
            man[i] = {**kept, **entry}
            return man
    man.append(entry)
    return man
