"""사내·공통기반 모델(OpenAI 호환) 제공자: 주소는 서버 환경변수로만, 키는 선택, 모델 이름은 화면에서.
vLLM·Ollama·행정안전부 AI 공통기반(Gemma·GPT-OSS·EXAONE·Solar 등) 어디든 같은 방식으로 붙는다."""
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, json.dumps(body)

    def json(self):
        return self._b


@pytest.fixture
def compat(monkeypatch):
    import api_server as A
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "http://llm.internal:8000/v1/")
    monkeypatch.delenv("OPENAI_COMPAT_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_COMPAT_MODELS", "google/gemma-3-27b-it, gpt-oss-20b")
    calls = []

    def post(url, **kw):
        calls.append({"url": url, **kw})
        return _Resp(200, {"choices": [{"message": {"content": "답"}, "finish_reason": "stop"}]})
    monkeypatch.setattr(A.req_lib, "post", post)
    A._COMPAT_MODELS_CACHE.update({"ts": 0.0, "models": []})
    return calls


def test_compat_call_uses_server_url_model_and_optional_key(compat, monkeypatch):
    import api_server as A
    txt, err = A._ai_generate("compat", "", "google/gemma-3-27b-it", "시스템", "질문")
    assert (txt, err) == ("답", "")
    c = compat[-1]
    assert c["url"] == "http://llm.internal:8000/v1/chat/completions"           # 끝의 / 는 정리
    assert c["json"]["model"] == "google/gemma-3-27b-it" and c["json"]["messages"][0]["role"] == "system"
    assert "Authorization" not in c["headers"]                                     # 키 없이(vLLM·Ollama 기본)
    A._ai_generate("compat", "user-key", "gpt-oss-20b", "s", "u")
    assert compat[-1]["headers"]["Authorization"] == "Bearer user-key"             # 사용자가 넣은 키
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "srv-key")
    A._ai_generate("compat", "", "", "s", "u")                                      # 모델을 비우면 관리자 목록의 첫 모델
    assert compat[-1]["headers"]["Authorization"] == "Bearer srv-key" and compat[-1]["json"]["model"] == "google/gemma-3-27b-it"


def test_compat_rejects_unsafe_model_names_and_reports_errors(compat, monkeypatch):
    import api_server as A
    assert A._ai_generate("compat", "", "../../x y", "s", "u")[1] == "모델 이름 형식이 올바르지 않습니다."
    assert A._ai_generate("gemini", "k", "a/b", "s", "u")[1] == "모델 이름 형식이 올바르지 않습니다."   # 다른 제공자는 / 를 계속 막는다
    monkeypatch.setattr(A.req_lib, "post", lambda url, **kw: _Resp(404, {"error": {"message": "model 'x' not found"}}))
    txt, err = A._ai_generate("compat", "", "x", "s", "u")
    assert txt == "" and err.startswith("사내·공통기반 모델 오류")


def test_compat_not_configured(monkeypatch):
    import api_server as A
    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL", raising=False)
    called = []
    monkeypatch.setattr(A.req_lib, "post", lambda *a, **k: called.append(1))
    txt, err = A._ai_generate("compat", "", "m", "s", "u")
    assert txt == "" and "OPENAI_COMPAT_BASE_URL" in err and not called


def test_models_endpoint_and_config(client, compat, monkeypatch):
    import api_server as A
    monkeypatch.setattr(A.req_lib, "get", lambda url, **kw: _Resp(200, {"data": [{"id": "exaone-3.5"}, {"id": "gpt-oss-20b"}]}))
    d = client.get("/api/ai/models?provider=compat").get_json()
    assert d["ready"] and d["models"] == ["google/gemma-3-27b-it", "gpt-oss-20b", "exaone-3.5"] and d["model"] == "google/gemma-3-27b-it"
    cfg = client.get("/api/regagent/config").get_json()
    assert cfg["compat"] == {"ready": True, "label": "사내·공통기반 모델"}
    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL")
    assert client.get("/api/regagent/config").get_json()["compat"]["ready"] is False
    assert "OPENAI_COMPAT_BASE_URL" in client.get("/api/ai/models?provider=compat").get_json()["error"]


def test_draft_uses_compat_without_key(client, compat, monkeypatch):
    """키가 없어도 서버에 주소가 있으면 AI 경로로 간다(규칙 골격으로 빠지지 않는다)."""
    import reg_agent as R
    seen = []
    draft = {"title": "업무용 드론 운영지침", "articles": [{"chapter": "", "no": "1", "title": "목적", "body": "이 지침은 드론 운영에 필요한 사항을 정한다.", "src": ""}],
             "addenda": ["이 지침은 발령한 날부터 시행한다."], "reason": {"purpose": "드론 운영 기준을 정하려는 것임.", "main": []}, "notes": []}

    def fake(provider, key, mdl, system, user, **kw):
        seen.append((provider, key, mdl))
        return json.dumps(draft, ensure_ascii=False), ""
    monkeypatch.setitem(R._CTX, "ai_generate", fake)
    d = client.post("/api/regagent/draft", json={"mode": "enact", "title": "업무용 드론 운영지침", "provider": "compat", "model": "gpt-oss-20b"}).get_json()
    assert d["success"] and seen and seen[0] == ("compat", "", "gpt-oss-20b")


def test_ui_has_compat_tab():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'data-p="compat"' in html and 'id="aiModelTxt"' in html and "/api/ai/models?provider=compat" in html
    js = (ROOT / "assets" / "reg_agent.js").read_text(encoding="utf-8")
    assert "p==='compat'&&RA_ORG._compat!==false" in js and "RA_ORG._compat=!!(d.compat&&d.compat.ready)" in js
