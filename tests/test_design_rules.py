"""디자인 규칙: 왼쪽 색띠(굵은 왼쪽 테두리·왼쪽 inset 그림자·왼쪽 테두리만 색칠)를 쓰지 않는다.
단계 사이를 잇는 무채색 선(.ra-steps li)만 예외."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOW = {".ra-steps li"}
BAD = re.compile(r"border-left(?:-width)?\s*:\s*(?:[a-z]+\s+)?(?:(\d+(?:\.\d+)?)px|[\d.]+r?em|var\(--rule-bar\))|border-left-color\s*:|"
                 r"border-inline-start\s*:\s*\d|box-shadow\s*:[^;}]*inset\s+[1-9]\d*px\s+0(?:px)?\s+0(?:px)?\s")


def _offenders(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        sel = " ".join(sel.split())
        for m in BAD.finditer(body):
            if m.group(1) is not None and float(m.group(1)) < 2:
                continue
            if sel in ALLOW or any(sel.endswith(a) or sel.startswith(a + ":") for a in ALLOW):
                continue
            out.append(f"{sel} {{ {m.group(0)} }}")
    return out


def test_no_left_stripes(client):
    # 이 저장소에 남은 화면은 MCP 연결 안내(/)뿐이다. 에이전트 화면 CSS 는 내규똑똑(agro-law)이 같은 규칙으로 막는다
    html = client.get("/", headers={"Accept": "text/html"}).get_data(as_text=True)
    css = "".join(re.findall(r"<style>(.*?)</style>", html, re.S))
    assert css
    bad = _offenders(css)
    assert not bad, "왼쪽 색띠 금지:\n" + "\n".join(bad[:20])
    js = open(os.path.join(ROOT, "assets", "reg_agent.js"), encoding="utf-8").read()
    assert not re.search(r"border-?[lL]eft(?:-width)?\s*[:=]\s*['\"]?(?:[a-z]+\s+)?(?:[2-9]|[1-9]\d)px", js), "화면 코드의 인라인 스타일에도 왼쪽 색띠 금지"


def test_no_left_stripes_in_regulation_pages():
    # 내규 원문 페이지(regulations/*/index.html)와 그것을 만드는 틀(reg_import.py)도 같은 규칙을 따른다
    src = open(os.path.join(ROOT, "reg_import.py"), encoding="utf-8").read().replace("{{", "{").replace("}}", "}")
    bad = [f"reg_import.py: {b}" for b in _offenders("".join(re.findall(r"<style>(.*?)</style>", src, re.S)))]
    for base in ("regulations", os.path.join("samples")):
        for dp, _, fs in os.walk(os.path.join(ROOT, base)):
            for f in fs:
                if f.endswith(".html"):
                    html = open(os.path.join(dp, f), encoding="utf-8").read()
                    bad += [f"{os.path.relpath(os.path.join(dp, f), ROOT)}: {b}"
                            for b in _offenders("".join(re.findall(r"<style>(.*?)</style>", html, re.S)))]
    assert not bad, "왼쪽 색띠 금지:\n" + "\n".join(bad[:20])
