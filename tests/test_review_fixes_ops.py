"""운영·보안 점검 수정(CORS 출처·알리오 다운로드 오류·캐시 상한·벡터 로드·AI 키 전달·감시 알림)."""
import json
import os
import sys
import threading
import time

import pytest
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import alio  # noqa: E402
import api_server as A  # noqa: E402
import reg_agent as ra  # noqa: E402


# ── 1. CORS 허용 출처 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("origin,ok", [
    ("https://agro-law.vercel.app", True),
    ("https://agro-law-git-main-kimjs3176-5164s-projects.vercel.app", True),
    ("https://agro-law-abc123-kimjs3176-5164s-projects.vercel.app", True),
    ("http://localhost:5000", True),
    ("http://127.0.0.1:8080", True),
    ("https://agro-law-attacker.vercel.app", False),
    ("https://agro-lawx.vercel.app", False),
    ("https://agro-law-x-kimjs3176-5164s-projects.vercel.app.evil.com", False),
    ("https://evil.com", False),
])
def test_cors_origins_pinned(client, origin, ok):
    r = client.get("/api/ping", headers={"Origin": origin})
    assert (r.headers.get("Access-Control-Allow-Origin") == origin) is ok


def test_cors_list_usable_by_mcp_remote():
    """MCP 원격 서버도 같은 목록을 쓴다(정규식 .match 또는 문자열 ==)."""
    def allowed(o):
        return any((hasattr(p, "match") and p.match(o)) or p == o for p in A._cors_origins)
    assert allowed("https://agro-law.vercel.app")
    assert allowed("https://agro-law-git-main-kimjs3176-5164s-projects.vercel.app")
    assert not allowed("https://agro-law-attacker.vercel.app")


# ── 2. 알리오 내려받기 도중 끊김 → AlioError(NETWORK) ──────────────────────────
class _Broken:
    status_code = 200
    headers = {"content-type": "application/octet-stream"}

    @property
    def text(self):
        raise requests.exceptions.ConnectionError("reset")

    def iter_content(self, n):
        yield b"PK\x03\x04abc"
        raise requests.exceptions.ChunkedEncodingError("reset")

    def close(self):
        pass


class _Page:
    status_code = 200
    headers = {}
    text = '<a href="/download/rulefiledown.json?fileNo=123">규정.hwpx</a>'

    def close(self):
        pass


@pytest.mark.parametrize("binary", [True, False])
def test_alio_stream_error_becomes_alio_error(monkeypatch, binary):
    monkeypatch.setattr(alio._S, "request", lambda *a, **k: _Broken())
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(alio.AlioError) as e:
        alio._request("GET", "/x", binary=binary)
    assert e.value.kind == "NETWORK"


def test_alio_rule_routes_answer_normally_on_stream_error(client, monkeypatch):
    monkeypatch.setattr(alio._S, "request", lambda m, url, **k: _Broken() if "rulefiledown" in url else _Page())
    monkeypatch.setattr(time, "sleep", lambda s: None)
    alio._cache["files"].clear()
    alio._cache["text"].clear()
    for path, body in (("/api/regagent/bench/rule", {"orgId": "C0001", "idx": "1", "item": "일비", "unit": "원"}),
                       ("/api/regagent/alio/rule", {"orgId": "C0001", "idx": "2"})):
        r = client.post(path, json=body)
        assert r.status_code != 500, (path, r.get_data(as_text=True))
        assert r.get_json().get("success") is False


# ── 3. 알리오 연결 확인 실패는 짧게만 기억 ─────────────────────────────────────
def test_reachable_failure_cached_briefly(monkeypatch):
    calls = []

    def head(*a, **k):
        calls.append(1)
        raise requests.exceptions.ConnectionError("down")
    monkeypatch.setattr(alio._S, "head", head)
    now = [1_000_000.0]
    monkeypatch.setattr(alio.time, "time", lambda: now[0])
    alio._REACH.update(ok=None, at=0.0)
    assert alio.reachable() is False and len(calls) == 1
    now[0] += 30
    assert alio.reachable() is False and len(calls) == 1          # 잠깐은 다시 묻지 않는다
    now[0] += 40
    assert alio.reachable() is False and len(calls) == 2          # 1분 넘으면 다시 확인
    alio._REACH.update(ok=None, at=0.0)


# ── 4. 캐시 상한 ────────────────────────────────────────────────────────────
def test_alio_trunc_cache_bounded_and_cleared(monkeypatch):
    def fake_json(method, path, body=None, deadline=None):
        return {"data": {"result": [{"idx": 1, "title": "t"}], "page": {"totalPage": 1, "totalCount": 99}}}
    monkeypatch.setattr(alio, "_json", fake_json)
    alio._cache["search"].clear()
    alio._cache.pop("trunc", None)
    for i in range(2100):
        alio._search_org({"id": f"O{i}", "name": "n"}, "kw", "")
        assert len(alio._cache.get("trunc", {})) <= 2000
    assert len(alio._cache["trunc"]) == len(alio._cache["search"])     # 검색 캐시를 비울 때 함께 비운다
    alio._cache["search"].clear()
    alio._cache["trunc"].clear()


def test_rel_cache_bounded(client, monkeypatch):
    monkeypatch.setattr(A, "OC", "test-oc")
    monkeypatch.setattr(A, "_lookup_law", lambda n, k: {"mst": "1", "id": "1", "rank": 0, "name": n})
    monkeypatch.setattr(A, "_law_get_xml", lambda *a, **k: A.ET.fromstring("<r/>"))
    monkeypatch.setattr(A, "_law_rel_items", lambda root, me: [{"name": me + " 시행령", "rel": "하위법", "id": "", "mst": ""}])
    A._REL_CACHE.clear()
    for i in range(A._REL_CACHE_MAX + 20):
        assert client.get(f"/api/law/related?name=법령{i}").status_code == 200
    assert len(A._REL_CACHE) <= A._REL_CACHE_MAX
    assert f"법령{A._REL_CACHE_MAX + 19}" in A._REL_CACHE                # 최근 것은 남는다
    A._REL_CACHE.clear()


# ── 5. 벡터 로드 경쟁 ───────────────────────────────────────────────────────
def test_vec_load_concurrent_first_request_waits(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    meta = tmp_path / "v.json"
    meta.write_text(json.dumps({"dim": 2, "count": 1, "chunks": [{}]}), encoding="utf-8")
    np.array([1, 0], dtype=np.int8).tofile(str(tmp_path / "v.bin"))
    monkeypatch.setattr(A, "_VEC_META", str(meta))
    monkeypatch.setattr(A, "_VEC_BIN", str(tmp_path / "v.bin"))
    saved = dict(A._VEC_CACHE)
    A._VEC_CACHE.update({"loaded": False, "meta": None, "mat": None, "np": None})
    real = np.fromfile
    gate = threading.Event()

    def slow(*a, **k):
        gate.wait(2)
        return real(*a, **k)
    monkeypatch.setattr(np, "fromfile", slow)
    try:
        out = []
        t1 = threading.Thread(target=lambda: out.append(A._vec_load()["mat"] is not None))
        t1.start()
        time.sleep(0.1)
        t2 = threading.Thread(target=lambda: out.append(A._vec_load()["mat"] is not None))
        t2.start()
        time.sleep(0.1)
        gate.set()
        t1.join(5); t2.join(5)
        assert out == [True, True]
    finally:
        A._VEC_CACHE.clear()
        A._VEC_CACHE.update(saved)


# ── 6·7. /api/ai/models 키 전달·전역 캐시 ─────────────────────────────────────
class _Models:
    status_code = 200

    def __init__(self, names):
        self._n = names

    def json(self):
        return {"models": [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]} for n in self._n]}


def test_ai_models_key_from_header_not_query(client, monkeypatch):
    seen = []
    monkeypatch.setattr(A._SESSION, "get", lambda url, params=None, headers=None, timeout=None:
                        seen.append((headers or {}).get("x-goog-api-key")) or _Models(["gemini-3.0-flash"]))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    saved = dict(A._GEMINI_MODEL_CACHE)
    A._GEMINI_MODEL_CACHE.update({"model": None, "ts": 0.0, "ranked": []})
    try:
        d = client.get("/api/ai/models?provider=gemini&api_key=QUERYKEY").get_json()
        assert seen == [] and d["resolved"] is False                    # 쿼리의 키는 쓰지 않는다
        d = client.get("/api/ai/models?provider=gemini", headers={"X-Gemini-Key": "HDRKEY"}).get_json()
        assert seen == ["HDRKEY"] and d["resolved"] is True and d["model"] == "gemini-3.0-flash"
    finally:
        A._GEMINI_MODEL_CACHE.clear()
        A._GEMINI_MODEL_CACHE.update(saved)


def test_user_key_does_not_set_global_model(client, monkeypatch):
    lists = {"USERKEY": ["gemini-9.9-flash"], "SRVKEY": ["gemini-3.0-flash"]}
    monkeypatch.setattr(A._SESSION, "get", lambda url, params=None, headers=None, timeout=None:
                        _Models(lists[headers["x-goog-api-key"]]))
    monkeypatch.setenv("GEMINI_API_KEY", "SRVKEY")
    saved = dict(A._GEMINI_MODEL_CACHE)
    A._GEMINI_MODEL_CACHE.update({"model": None, "ts": 0.0, "ranked": []})
    try:
        d = client.get("/api/ai/models?provider=gemini", headers={"X-Gemini-Key": "USERKEY"}).get_json()
        assert d["model"] == "gemini-9.9-flash"                        # 그 사용자에게는 결과를 알려 주되
        assert A._GEMINI_MODEL_CACHE["model"] is None and A._GEMINI_MODEL_CACHE["ranked"] == []   # 모두의 기본은 안 바꾼다
        assert A._default_model_for("gemini") == A.GEMINI_DEFAULT_MODEL
        d = client.get("/api/ai/models?provider=gemini").get_json()      # 서버 키 결과만 기억한다
        assert d["model"] == "gemini-3.0-flash" and A._GEMINI_MODEL_CACHE["model"] == "gemini-3.0-flash"
    finally:
        A._GEMINI_MODEL_CACHE.clear()
        A._GEMINI_MODEL_CACHE.update(saved)


# ── 8. 감시 스크립트: 알림이 성공해야 기준을 바꾼다 ─────────────────────────────
IDX = {"근로기준법": [{"title": "복무규정", "articles": ["제1조"]}]}


def _changed_run(tmp_path, monkeypatch, post):
    import watch_laws
    monkeypatch.setattr(ra, "law_cite_index", lambda: IDX)
    state = tmp_path / "state.json"
    v = {"근로기준법": {"ef": "20250101"}}
    look = lambda n: v[n]
    assert watch_laws.main(["--state", str(state)], look_law=look, look_rule=look) == 0
    base = state.read_text(encoding="utf-8")
    v["근로기준법"] = {"ef": "20250101", "next": {"ef": "20990301", "anc": "20990101", "type": "일부개정"}, "mst": "1", "rank": 0}
    monkeypatch.setattr(requests, "post", post)
    rc = watch_laws.main(["--state", str(state), "--webhook", "https://hook.example/x"], look_law=look, look_rule=look)
    return rc, base, state.read_text(encoding="utf-8")


class _St:
    def __init__(self, c):
        self.status_code = c


def test_watch_webhook_non_2xx_keeps_baseline(tmp_path, monkeypatch):
    rc, base, after = _changed_run(tmp_path, monkeypatch, lambda url, json=None, timeout=None: _St(500))
    assert rc != 0 and after == base


def test_watch_webhook_exception_keeps_baseline(tmp_path, monkeypatch):
    def boom(url, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("down")
    rc, base, after = _changed_run(tmp_path, monkeypatch, boom)
    assert rc != 0 and after == base


def test_watch_webhook_ok_saves_baseline(tmp_path, monkeypatch):
    rc, base, after = _changed_run(tmp_path, monkeypatch, lambda url, json=None, timeout=None: _St(204))
    assert rc == 0 and after != base and "20990301" in after
