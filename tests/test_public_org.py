"""다른 공공기관 도입 시험(samples/public_org, 가상 기관) — 원문 파일(txt·docx)을 일괄 등록 스크립트로 들여온 뒤
기관 프로필만 바꿔 같은 엔진이 그대로 도는지 본다. 범정부 확산(다른 기관이 자기 내규로 쓰기)의 최소 경로."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "public_org")
CODE = r'''
import sys, json
sys.path.insert(0, %r)
import api_server, reg_agent as ra
from api_server import app
c = app.test_client()
regs = ra.all_regs()
out = {"org": [ra.ORG["org_name"], ra.ORG["org_short"], ra.ORG["head"]],
       "regs": sorted([r["title"], len(r["articles"]), bool(r["appendix"])] for r in regs)}
p = c.post("/api/regagent/plan", json={"request": "여비규정 제7조의 일비를 3만원으로 올려줘"}).get_json()["plan"]
out["plan"] = [p["mode"], p["reg"]["title"], [a["no"] for a in p["articles"]]]
slug = next(r["slug"] for r in regs if r["title"] == "복무규정")
im = c.post("/api/regagent/impact", json={"slug": slug, "nos": ["6"]}).get_json()
out["impact"] = [[x["no"] for x in im["inner"]], [[o["reg"], [h["no"] for h in o["hits"]]] for o in im["outer"]]]
out["enact"] = ra.template_enact({"title": "업무용 드론 운영지침", "purpose": "드론 운영"})["articles"][0]["body"]
out["health"] = len(c.get("/api/regagent/health").get_json()["rows"])
print("@@" + json.dumps(out, ensure_ascii=False))
''' % ROOT


def test_public_org_import_and_run(tmp_path):
    env = dict(os.environ, ORG_CONFIG=os.path.join(SAMPLE, "org_config.json"),
               REG_DIR=str(tmp_path / "regulations"), REG_MANIFEST=str(tmp_path / "manifest.json"),
               REG_VECTORS=str(tmp_path / "vectors"))
    # 1) 들여오기 — 원문 폴더 하나로 끝난다(저장소 데이터는 건드리지 않음)
    r = subprocess.run([sys.executable, "scripts/import_regulations.py", os.path.join(SAMPLE, "regs"), "--reset"],
                       capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT, timeout=120)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    assert "완료: 7건 등록(주의 0건), 실패 0건" in r.stdout
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert {m["title"] for m in man} >= {"여비규정", "복무규정", "인사규정", "차량관리지침"}
    # 2) 같은 엔진 — 기관명·조문 해석·인용 영향·제정 초안·건강검진
    r = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.split("@@", 1)[1])
    assert out["org"] == ["가상행정진흥원", "진흥원", "원장"]
    assert ["여비규정", 12, True] in out["regs"] and ["차량관리지침", 7, False] in out["regs"]   # docx도 조문 단위로
    assert out["plan"] == ["amend", "여비규정", ["7"]]
    assert out["impact"] == [["9"], [["인사규정", ["10"]]]]          # 같은 내규 안·다른 내규의 인용을 함께 찾는다
    assert "가상행정진흥원" in out["enact"] and "농진원" not in out["enact"]
    assert out["health"] == 7


def test_check_org_config_sample_and_ours(tmp_path):
    """도입 점검 도구 — 가상 기관 프로필은 근거 조항이 자기 규칙을 가리키고, 남의 조 번호를 베끼면 짚는다."""
    env = dict(os.environ, ORG_CONFIG=os.path.join(SAMPLE, "org_config.json"),
               REG_DIR=str(tmp_path / "regulations"), REG_MANIFEST=str(tmp_path / "manifest.json"),
               REG_VECTORS=str(tmp_path / "vectors"))
    subprocess.run([sys.executable, "scripts/import_regulations.py", os.path.join(SAMPLE, "regs"), "--reset"],
                   capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT, timeout=120, check=True)
    r = subprocess.run([sys.executable, "scripts/check_org_config.py"], capture_output=True, text=True,
                       encoding="utf-8", env=env, cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "근거 조항 18개 모두 「내규관리규칙」에 있음" in r.stdout and "오류 0" in r.stdout
    # 운영 프로필을 그대로 베낀 경우 — 조 번호가 가상 기관 규칙에 없다고 짚는다
    env["ORG_CONFIG"] = os.path.join(ROOT, "org_config.json")
    r = subprocess.run([sys.executable, "scripts/check_org_config.py"], capture_output=True, text=True,
                       encoding="utf-8", env=env, cwd=ROOT, timeout=300)
    assert "개가 「내규관리규칙」에 없습니다" in r.stdout and "lint_refs.deleted" in r.stdout
    assert "기관명·약칭(한국농업기술진흥원, 농진원)이 들여온 내규 어디에도 없습니다" in r.stdout


def test_check_org_config_our_profile_refs_exist():
    """운영 프로필의 근거 조항(점검·심의·절차)이 모두 우리 「내규관리규칙」에 실제로 있다."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import reg_agent as ra
    import check_org_config as chk
    errs, warns, oks = chk.check(ra.ORG, ra.all_regs())
    assert errs == []
    assert any("모두 「내규관리규칙」에 있음" in x for x in oks), warns
