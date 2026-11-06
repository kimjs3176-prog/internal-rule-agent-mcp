"""법제처 Open API 아이디(LAW_OC): 코드에 기본값을 두지 않고 서버 환경변수로만 받는다.
없으면 법제처를 부르지 않고 연결 실패와 구분되는 안내를 돌려준다."""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_hardcoded_oc_in_code():
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    assert 'os.environ.get("LAW_OC", "").strip()' in src
    assert "tjsl0919" not in src                         # 예전 기본값(특정 계정 아이디)이 남아 있지 않다


@pytest.fixture
def no_oc(monkeypatch):
    import api_server as A
    monkeypatch.setattr(A, "OC", "")
    calls = []
    monkeypatch.setattr(A._LAW_SESSION, "get", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("법제처를 부르면 안 된다")))
    return calls


def test_law_calls_refuse_without_oc(no_oc):
    import api_server as A
    with pytest.raises(A.LawNotConfigured, match="LAW_OC"):
        A._law_get_xml("lawSearch.do", {"target": "law", "query": "민법"})
    with pytest.raises(A.LawNotConfigured):
        A._law_get_json({"target": "law", "query": "민법"})
    assert no_oc == []                                    # 네트워크로 나가지 않았다


def test_law_routes_explain_missing_oc(client, no_oc):
    r = client.get("/api/law/articles?name=민법")
    assert r.status_code == 503 and r.get_json()["law_oc_missing"] and "LAW_OC" in r.get_json()["error"]
    r = client.get("/api/law/related?name=민법")
    assert r.status_code == 503 and r.get_json()["law_oc_missing"]
    r = client.post("/api/regagent/health/laws", json={"names": ["민법"]})
    assert r.status_code == 503 and r.get_json()["law_oc_missing"] and "LAW_OC" in r.get_json()["error"]
    assert client.get("/api/regagent/config").get_json()["law"] is False   # 화면은 이 값으로 안내를 띄우고 자동 확인을 건너뛴다


def test_config_reports_law_ready_with_oc(client, monkeypatch):
    import api_server as A
    monkeypatch.setattr(A, "OC", "test-id")
    assert client.get("/api/regagent/config").get_json()["law"] is True


def test_ui_handles_missing_oc():
    js = (ROOT / "assets" / "reg_agent.js").read_text(encoding="utf-8")
    assert "RA_ORG._law=d.law!==false" in js
    assert "RA_ORG._law===false||" in js                 # 자동 확인을 건너뛴다
    assert "서버 환경변수 <code>LAW_OC</code>" in js       # 건강검진 화면 안내
    assert "H.lawErr&&RA_ORG._law===false?''" in js     # 망 차단 안내(“연결하지 못한 N건”)와 섞지 않는다
    assert "if(RA_ORG._law===false){ if(!quiet) _toast(" in js   # 눌러도 서버에 묻지 않고 이유만 알린다
