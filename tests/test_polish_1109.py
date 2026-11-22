"""11/9 화면 다듬기 회귀 시험 — 법제처 아이디가 없을 때의 안내, 알리오 오류 문구, AI 설정 창."""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def no_oc(monkeypatch):
    import api_server as A
    monkeypatch.setattr(A, "OC", "")
    monkeypatch.setattr(A._LAW_SESSION, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("법제처를 부르면 안 된다")))


def test_expc_without_law_oc_explains_instead_of_retry(client, no_oc):
    # LKP-8: 법제처 아이디가 없으면 해석례를 부르지 않고, 다시 시도할 일이 아니라고 알린다(자문 회신은 그대로)
    r = client.post("/api/regagent/expc", json={"question": "출장 중 휴일 일비를 줄 수 있나요", "laws": []})
    d = r.get_json()
    assert r.status_code == 200 and d["success"] and d["items"] == [] and d["law_oc_missing"] and "LAW_OC" in d["error"]


def test_alio_error_hint_not_repeated(ra):
    # UX-14·HLT-12: 알리오 오류 문구에 이미 ‘다시 시도’가 있으면 덧붙이지 않는다
    import alio
    import api_server
    with api_server.app.app_context():
        msg = ra._alio_err(alio.AlioError("NETWORK", "알리오가 응답하지 않습니다. 잠시 뒤에 다시 시도하세요."))[0].get_json()["error"]
        assert msg.count("다시 시도") == 1
        msg = ra._alio_err(alio.AlioError("NETWORK", "연결 끊김"))[0].get_json()["error"]
        assert msg.endswith("잠시 뒤 다시 시도하세요.")
    # 망 차단 안내는 ‘다시 시도’ 대신 무엇이 빠지고 무엇은 되는지 말한다
    src = (ROOT / "alio.py").read_text(encoding="utf-8")
    assert "다른 기관 사례만 빠지고, 우리 기관 내규 작업은 그대로 할 수 있습니다." in src


def test_ai_no_change_message_points_to_fallback():
    # AG-12: AI가 수정안을 주지 않았을 때 — 무엇을 하면 되는지, 규칙 반영은 계속된다는 것
    src = (ROOT / "reg_agent.py").read_text(encoding="utf-8")
    assert "AI 응답에 조문 수정안이 없습니다. 다른 모델로 바꾸거나 다시 시도하세요" in src
    assert "AI가 수정안을 만들지 못했습니다. 개정 의도를 구체적으로" not in src


def test_docs_match_screen_names():
    # ENA-15·UX-13: 구동안내서 제정 단계 이름과 README 내규 등록 단추 위치가 화면과 같다
    guide = (ROOT / "docs" / "contest" / "구동안내서.md").read_text(encoding="utf-8")
    assert "조문 초안 → 점검·검토 → 문서 받기" in guide and "점검·심의 → 문서 세트" not in guide
    js = (ROOT / "assets" / "reg_agent.js").read_text(encoding="utf-8")
    for t in ("조문 초안", "점검·검토", "문서 받기"):
        assert f"{{t:'{t}'" in js
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    ops = (ROOT / "docs" / "운영.md").read_text(encoding="utf-8")     # README는 커넥터 사용만, 운영 안내는 docs/운영.md
    assert "📤 내규 등록" not in readme and "내규똑똑(`/upload`)" in ops     # 화면 등록은 내규똑똑으로 옮겼다
