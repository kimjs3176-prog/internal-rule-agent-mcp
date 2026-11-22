"""업무망(외부망 차단)에서도 같은 결과: MCP 연결 안내 화면이 외부 CDN 자원을 불러오지 않고, 라이선스 목록이 빠짐없다."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
_EXT = re.compile(r"""<(?:link|script)[^>]+(?:href|src)=["']https?://|url\(\s*['"]?https?://""", re.I)


def test_guide_page_loads_no_external_assets(client):
    html = client.get("/", headers={"Accept": "text/html"}).get_data(as_text=True)
    assert "/mcp" in html and not _EXT.search(html)


def test_third_party_license_list_covers_requirements():
    """정보화사업 이관 때 필요한 라이선스 목록: requirements.txt 의 패키지가 모두 적혀 있다."""
    lic = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8").lower()
    reqs = [re.split(r"[<>=!~\[ ]", ln.strip(), maxsplit=1)[0].lower() for ln in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    assert reqs and all(f"| {r} |" in lic for r in reqs), [r for r in reqs if f"| {r} |" not in lic]
