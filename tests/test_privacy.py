"""제출용 저장소에 개인정보가 남지 않게: 내규 목록의 등록자는 비우거나 부서명으로, 등록 화면도 부서명을 받는다."""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
_DEPT = re.compile(r"(팀|부|실|과|센터|처|단|본부|원|위원회|사무국|담당)$")


def _uploaders(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "uploader":
                yield v
            else:
                yield from _uploaders(v)
    elif isinstance(o, list):
        for v in o:
            yield from _uploaders(v)


def test_manifest_has_no_personal_names():
    m = json.loads((ROOT / "regulations_manifest.json").read_text(encoding="utf-8"))
    bad = [u for u in _uploaders(m) if u and re.fullmatch(r"[가-힣]{2,4}", u) and not _DEPT.search(u)]
    assert bad == [], f"사람 이름으로 보이는 등록자: {sorted(set(bad))}"


def test_upload_form_asks_department():
    html = (ROOT / "upload.html").read_text(encoding="utf-8")
    assert "올린 부서" in html and "올린 사람" not in html and 'autocomplete="name"' not in html
