"""디자인 규칙: 왼쪽 색띠(굵은 왼쪽 테두리·왼쪽 inset 그림자·왼쪽 테두리만 색칠)를 쓰지 않는다.
단계 사이를 잇는 무채색 선(.ra-steps li)만 예외."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOW = {".ra-steps li"}
BAD = re.compile(r"border-left\s*:\s*(?:(\d+(?:\.\d+)?)px|var\(--rule-bar\))\s+solid|border-left-color\s*:|"
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


def test_no_left_stripes():
    files = [os.path.join(ROOT, "assets", "reg_agent.css"), os.path.join(ROOT, "assets", "tokens.css")]
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    css = "".join(open(f, encoding="utf-8").read() for f in files) + "".join(re.findall(r"<style>(.*?)</style>", html, re.S))
    bad = _offenders(css)
    assert not bad, "왼쪽 색띠 금지:\n" + "\n".join(bad[:20])
    js = open(os.path.join(ROOT, "assets", "reg_agent.js"), encoding="utf-8").read()
    assert not re.search(r"border-left\s*:\s*[2-9]px", js), "화면 코드의 인라인 스타일에도 왼쪽 색띠 금지"
