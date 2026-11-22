"""코드 점검(2026-11-22)에서 찾은 오류의 재현 시험 — 검색 조문 분리, 등록 내규 + org, stdio 한글(Windows)."""
import json
import os
import pathlib
import subprocess
import sys

import reg_chunks as rc
from mcp_server import core

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_article_after_heading_ending_in_law_word_is_kept():
    # 앞줄이 “…방법”·“…규정”으로 끝나도 줄 첫머리의 제N조(…)는 새 조문이다(인용으로 보고 앞 조에 붙이지 않는다)
    text = "제6조(목적) 목적을 정한다.\n제2장 계약의 원칙 및 방법\n제7조(계약의 원칙) 계약은 공정하게 한다.\n" \
           "제8조(준용) 이 밖의 사항은 「상법」제391조(이사회의 결의 방법)를 따른다."
    nos = [a["no"] for a in rc.split_articles(text)]
    assert nos == ["6", "7", "8"]


def test_registered_articles_all_searchable():
    for slug, want in (("윤리경영규정", {"12", "13", "17"}), ("계약사무규칙", {"7"})):
        html = (ROOT / "regulations" / slug / "index.html").read_text(encoding="utf-8")
        nos = {a["no"] for a in rc.split_articles(rc.html_to_text(html))}
        assert want <= nos, (slug, want - nos)


def test_amend_registered_regulation_ignores_org():
    r = core.t_amend_regulation(regulation="여비규정", changes=[{"article": "제1조", "body": "이 규정은 시험이다."}],
                                org={"org_name": "한국테스트공단"})
    assert not r.get("error"), r.get("error")
    assert (r.get("verification") or {}).get("ok") is True
    assert any("org" in w for w in r.get("warnings") or [])


def test_stdio_reads_utf8_even_when_locale_is_cp949():
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "check_regulation", "arguments": {"text": "제1조(목적) 이 규정은 목적을 정한다.", "org": {"org_name": "가재단"}}}}
    env = {**os.environ, "PYTHONIOENCODING": "cp949"}
    out = subprocess.run([sys.executable, str(ROOT / "mcp_server" / "server.py")],
                         input=(json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8") + b"\xff\xfe\n",
                         capture_output=True, env=env, timeout=120)
    lines = [json.loads(x) for x in out.stdout.decode("utf-8").splitlines() if x.strip()]
    assert lines[0]["id"] == 1 and "result" in lines[0]
    assert lines[1]["error"]["code"] == -32700          # UTF-8 이 아닌 줄은 오류로 답하고 서버는 계속 돈다
