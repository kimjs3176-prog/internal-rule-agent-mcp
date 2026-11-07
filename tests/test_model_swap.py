"""모델 비종속 입증(A-2): 같은 제정·개정 요청을 ① 규칙 모드(AI 없음) ② 사내·공통기반 모델 A(OpenAI 호환) ③ 같은 서버의 모델 B
④ 다른 OpenAI 호환 서버(설정만 바꿔 교체) ⑤ Ollama 고유 API 로 보내, 코드 변경 없이 제공자·모델만 바꿔 돈다는 것을 확인한다.
모델 서버는 시험 안에서 띄우는 가짜 서버다(실제 모델 구동은 docs/contest/모델교체시험.md 의 절차로 사람이 확인)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


def _enact(model):
    return {"title": "업무용 드론 운영지침", "articles": [
        {"chapter": "", "no": "1", "title": "목적", "body": "이 지침은 업무용 드론의 안전한 운영에 필요한 사항을 정함을 목적으로 한다.", "src": ""},
        {"chapter": "", "no": "2", "title": "운영책임자", "body": "① 원장은 드론 운영책임자를 지정한다.\n② 운영책임자는 비행 전 안전점검을 하여야 한다.", "src": ""}],
        "addenda": ["이 지침은 발령한 날부터 시행한다."], "reason": {"purpose": f"드론 운영 기준을 정하려는 것임({model}).", "main": []}, "notes": []}


def _amend(model):
    return {"changes": [{"type": "modify", "no": "17", "title": "근무지내 국내출장시의 여비",
                         "body": "① 근무지내 국내출장의 경우에는 제15조의 규정에 불구하고 출장여행시간이 4시간 이상인 자에 대하여는 3만원을, 4시간 미만인 자에 대하여는 1만5천원을 지급한다.",
                         "why": "근무지내 출장 여비를 현실화"}],
            "reason": {"purpose": f"근무지내 출장 여비를 현실화하려는 것임({model}).", "main": ["근무지내 출장 여비 인상(안 제17조)"]},
            "addenda": ["이 규정은 발령한 날부터 시행한다."], "notes": []}


class FakeModelServer:
    """OpenAI 호환(/v1/models, /v1/chat/completions)과 Ollama 고유(/api/chat)를 함께 흉내 낸다. 받은 요청을 기록한다."""

    def __init__(self, name):
        self.name, self.calls = name, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                b = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                self._send({"object": "list", "data": [{"id": "google/gemma-3-27b-it"}, {"id": "exaone-3.5-32b"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                system = body["messages"][0]["content"]
                model = body.get("model")
                outer.calls.append({"path": self.path, "model": model, "auth": self.headers.get("Authorization")})
                content = json.dumps((_amend if '"changes"' in system else _enact)(f"{outer.name}:{model}"), ensure_ascii=False)
                if self.path == "/api/chat":                      # Ollama 고유 응답 형식
                    self._send({"model": model, "message": {"role": "assistant", "content": content}, "done": True})
                else:                                             # OpenAI 호환 응답 형식
                    self._send({"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def servers(monkeypatch):
    import api_server as A
    a, b = FakeModelServer("vLLM"), FakeModelServer("공통기반")
    monkeypatch.delenv("OPENAI_COMPAT_API_KEY", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    A._COMPAT_MODELS_CACHE.update({"ts": 0.0, "models": []})
    yield a, b
    a.close(), b.close()


def _enact_req(client, **ai):
    return client.post("/api/regagent/draft", json={"mode": "enact", "title": "업무용 드론 운영지침", **ai}).get_json()


def _amend_req(client, **ai):
    return client.post("/api/regagent/draft", json={"mode": "amend", "slug": "여비규정", "intent": "근무지내 출장 여비를 현실화",
                                                    "targets": [{"no": "17", "title": "근무지내 국내출장시의 여비", "body": "(현행)"}], **ai}).get_json()


def test_same_requests_run_on_rule_mode_and_four_model_paths(client, servers, monkeypatch):
    a, b = servers
    # ① 규칙 모드(AI 없음): 표준 조문 골격
    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL", raising=False)
    d = _enact_req(client)
    assert d["success"] and "표준 조문 골격" in (d.get("notice") or "") and d["draft"]["articles"]

    # ② 사내·공통기반 모델 A(OpenAI 호환, vLLM) — 키 없이
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", a.url + "/v1")
    d = _enact_req(client, provider="compat", model="google/gemma-3-27b-it")
    assert d["success"] and [x["title"] for x in d["draft"]["articles"]] == ["목적", "운영책임자"]
    assert a.calls[-1] == {"path": "/v1/chat/completions", "model": "google/gemma-3-27b-it", "auth": None}

    # ③ 같은 서버의 다른 모델 B — 화면에서 모델 이름만 바꾼다
    d = _amend_req(client, provider="compat", model="exaone-3.5-32b")
    assert d["success"] and d["draft"]["changes"][0]["no"] == "17" and "3만원" in d["draft"]["changes"][0]["body"]
    assert "vLLM:exaone-3.5-32b" in d["draft"]["reason"]["purpose"]

    # ④ 다른 OpenAI 호환 서버(행안부 AI 공통기반 등) — 관리자가 주소·키만 바꾼다(코드 변경 없음)
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", b.url + "/v1")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "gov-key")
    d = _amend_req(client, provider="compat", model="gpt-oss-120b")
    assert d["success"] and "공통기반:gpt-oss-120b" in d["draft"]["reason"]["purpose"]
    assert b.calls[-1]["auth"] == "Bearer gov-key" and len(a.calls) == 2       # 앞 서버로는 더 가지 않았다

    # ⑤ Ollama 고유 API(사내 PC·서버)
    monkeypatch.setenv("OLLAMA_BASE_URL", a.url)
    d = _enact_req(client, provider="ollama", model="gemma2")
    assert d["success"] and a.calls[-1]["path"] == "/api/chat" and a.calls[-1]["model"] == "gemma2"


def test_models_list_follows_the_configured_server(client, servers, monkeypatch):
    a, _ = servers
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", a.url + "/v1")
    d = client.get("/api/ai/models?provider=compat").get_json()
    assert d["ready"] and d["models"] == ["google/gemma-3-27b-it", "exaone-3.5-32b"]
