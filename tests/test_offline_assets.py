"""업무망(외부망 차단)에서도 같은 화면: 글꼴 등 화면 자원을 외부 CDN 에서 불러오지 않는다."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
_EXT = re.compile(r"""<(?:link|script)[^>]+(?:href|src)=["']https?://""", re.I)


def test_pages_load_no_external_assets():
    for name in ["index.html", "upload.html"]:
        html = (ROOT / name).read_text(encoding="utf-8")
        assert not _EXT.search(html), f"{name} 이 외부 자원을 불러온다"
        assert '/assets/fonts/pretendard/pretendard.css' in html
    for css in (ROOT / "assets").glob("*.css"):
        assert not re.search(r"@import\s+url\(\s*['\"]?https?://|url\(\s*['\"]?https?://", css.read_text(encoding="utf-8")), css.name


def test_bundled_font_and_license():
    d = ROOT / "assets" / "fonts" / "pretendard"
    css = (d / "pretendard.css").read_text(encoding="utf-8")
    files = re.findall(r"url\(\./(woff2-dynamic-subset/[^)]+\.woff2)\)", css)
    assert len(files) >= 50 and all((d / f).exists() for f in files)      # 글꼴 조각이 모두 들어 있다
    lic = (d / "LICENSE.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in lic and "Pretendard" in lic


def test_third_party_license_list_covers_requirements():
    """정보화사업 이관 때 필요한 라이선스 목록: requirements.txt 의 패키지와 포함한 글꼴이 모두 적혀 있다."""
    lic = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8").lower()
    reqs = [re.split(r"[<>=!~\[ ]", ln.strip(), maxsplit=1)[0].lower() for ln in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    assert reqs and all(f"| {r} |" in lic for r in reqs), [r for r in reqs if f"| {r} |" not in lic]
    assert "pretendard" in lic and "ofl" in lic
