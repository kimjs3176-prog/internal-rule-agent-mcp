"""상위법 개정 감시 — 지난 확인과 견줘 새로 공포·시행된 개정을 찾고(첫 확인은 기준만), 인용 내규를 붙인다."""
import json
import os
import sys

import reg_agent as ra

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
IDX = {"근로기준법": [{"slug": "복무규정", "title": "복무규정"}], "국가재정법": [{"slug": "회계규정", "title": "회계규정"}]}


def test_first_check_only_sets_baseline():
    r = ra.law_watch_diff(None, {"근로기준법": {"ef": "20250101", "next": {"ef": "20990301", "anc": "20990101", "type": "일부개정"}}}, IDX)
    assert r["first"] and r["changes"] == [] and r["snapshot"]["근로기준법"]["next"]["ef"] == "20990301"


def test_new_promulgation_and_enforcement_detected():
    prev = {"근로기준법": {"ef": "20250101", "next": None},
            "국가재정법": {"ef": "20240101", "next": {"ef": "20260101", "anc": "20251201", "type": "일부개정"}}}
    cur = {"근로기준법": {"ef": "20250101", "next": {"ef": "20990301", "anc": "20990101", "type": "일부개정"}},
           "국가재정법": {"ef": "20260101"},
           "새로인용한법": {"ef": "20200101"},            # 기준이 없던 규범은 알리지 않고 기준만
           "조회실패법": {"error": "법제처 응답 지연"}}
    r = ra.law_watch_diff(prev, cur, IDX)
    got = [(c["law"], c["kind"], c["ef"]) for c in r["changes"]]
    assert got == [("근로기준법", "promulgated", "20990301"), ("국가재정법", "enforced", "20260101")]
    assert r["changes"][0]["regs"] == [{"slug": "복무규정", "title": "복무규정"}]
    assert r["changes"][1]["prev_ef"] == "20240101" and r["changes"][1]["anc"] == "20251201"
    assert "새로인용한법" in r["snapshot"] and "조회실패법" not in r["snapshot"]


def test_same_state_no_changes_and_failed_lookup_keeps_baseline():
    prev = {"근로기준법": {"ef": "20250101", "next": {"ef": "20990301", "anc": "20990101", "type": "일부개정"}}}
    r = ra.law_watch_diff(prev, {"근로기준법": {"ef": "20250101", "next": {"ef": "20990301", "anc": "20990101", "type": "일부개정"}}}, IDX)
    assert r["changes"] == []
    r = ra.law_watch_diff(prev, {"근로기준법": {"error": "x"}}, IDX)   # 이번에 못 본 규범은 지난 기준 유지
    assert r["changes"] == [] and r["snapshot"] == {"근로기준법": prev["근로기준법"]}


def test_watch_diff_endpoint(client):
    d = client.post("/api/regagent/watch/diff", json={"prev": None, "cur": {"근로기준법": {"ef": "20250101"}}}).get_json()
    assert d["success"] and d["first"] and d["changes"] == []
    d = client.post("/api/regagent/watch/diff", json={"prev": d["snapshot"], "cur": {"근로기준법": {"ef": "20250101", "next": {"ef": "20990301", "anc": "20990101", "type": "일부개정"}}}}).get_json()
    assert [c["kind"] for c in d["changes"]] == ["promulgated"]
    assert any(r["title"] == "복무규정" for r in d["changes"][0]["regs"])     # 실제 내규에서 인용 내규를 찾는다
    assert client.post("/api/regagent/watch/diff", json={"cur": {str(i): {"ef": "1"} for i in range(1001)}}).status_code == 400


def test_watch_script_baseline_then_alert(tmp_path, capsys, monkeypatch):
    import watch_laws
    monkeypatch.setattr(ra, "law_cite_index", lambda: IDX)
    state = tmp_path / "state.json"
    v1 = {"근로기준법": {"ef": "20250101"}, "국가재정법": {"ef": "20240101"}}
    look = lambda n: v1[n]
    assert watch_laws.main(["--state", str(state)], look_law=look, look_rule=look) == 0
    assert "기준만 저장했습니다" in capsys.readouterr().out
    assert json.loads(state.read_text(encoding="utf-8"))["laws"]["근로기준법"]["ef"] == "20250101"
    v1["근로기준법"] = {"ef": "20250101", "next": {"ef": "20990301", "anc": "20990101", "type": "일부개정"}, "mst": "1", "rank": 0}
    sent = []

    class R:
        status_code = 200
    import requests
    monkeypatch.setattr(requests, "post", lambda url, json=None, timeout=None: sent.append((url, json)) or R())
    assert watch_laws.main(["--state", str(state), "--webhook", "https://hook.example/x"], look_law=look, look_rule=look) == 0
    out = capsys.readouterr().out
    assert "「근로기준법」 새 개정 공포(2099. 1. 1. 공포, 2099. 3. 1. 시행 예정, 일부개정)" in out and "「복무규정」" in out
    assert sent and sent[0][0] == "https://hook.example/x" and "근로기준법" in sent[0][1]["text"]
    # 같은 상태로 다시 돌리면 알림 없음
    assert watch_laws.main(["--state", str(state)], look_law=look, look_rule=look) == 0
    assert "바뀐 상위법·행정규칙이 없습니다" in capsys.readouterr().out


def test_watch_script_all_failed_keeps_state(tmp_path, monkeypatch):
    import watch_laws
    monkeypatch.setattr(ra, "law_cite_index", lambda: IDX)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"laws": {"근로기준법": {"ef": "20250101", "next": None}}}), encoding="utf-8")
    look = lambda n: {"error": "차단"}
    assert watch_laws.main(["--state", str(state)], look_law=look, look_rule=look) == 3
    assert json.loads(state.read_text(encoding="utf-8"))["laws"]["근로기준법"]["ef"] == "20250101"
