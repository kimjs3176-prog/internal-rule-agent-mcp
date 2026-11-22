"""규정 제·개정 에이전트 — MCP(Model Context Protocol) 서버(표준 입출력).

Claude·ChatGPT·Gemini·사내 모델 등 MCP 를 지원하는 AI 도우미가 이 에이전트를 “도구”로 쓰게 한다.
내규똑똑 에이전트 화면과 같은 엔진·같은 내규 데이터를 쓰며, 별도 패키지 없이 표준 입출력(stdio) JSON-RPC 로 동작한다.
배포한 웹 서비스의 /mcp 주소로 원격 연결도 된다(mcp_server/remote.py, docs/MCP.md).

실행: python mcp_server/server.py        (AI 도우미의 MCP 설정에 이 명령을 등록 — docs/MCP.md)
  - 기관 설정·내규 위치는 웹 서비스와 같은 환경변수(ORG_CONFIG, REG_DIR, REG_MANIFEST, LAW_OC 등)를 따른다.
  - 개정문·신구조문대비표·에이전트 도구는 화면 엔진(assets/reg_agent.js)을 QuickJS(requirements.txt)로 돌린다.
    QuickJS 를 설치할 수 없으면 Node.js 18 이상으로 돌린다(mcp_server/engine.py).
  - 문서 저장(output_dir)은 지정한 폴더에만 쓴다. 그 밖의 도구는 내규를 읽기만 한다.
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if sys.path and os.path.abspath(sys.path[0] or ".") == os.path.dirname(os.path.abspath(__file__)):
    sys.path[0] = ROOT                         # 이 폴더의 파일 이름이 다른 모듈을 가리지 않게(패키지 mcp_server 로만 부른다)
elif ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 표준 출력은 MCP 메시지 전용이다. 서버 코드가 찍는 print·로그는 모두 표준 오류로 보낸다.
_PROTO = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8", newline="\n", write_through=True)
os.dup2(2, 1)
sys.stdout = sys.stderr

import api_server  # noqa: E402,F401  (웹 서비스와 같은 앱·블루프린트·데이터)
from mcp_server import core  # noqa: E402

api_server.app.config["TESTING"] = True


def handle(msg):
    return core.handle(msg, mode="stdio")


def _send(obj):
    s = json.dumps(obj, ensure_ascii=False)
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:                        # 깨진 유니코드(짝 없는 대리 문자)는 \u 꼴로 — 서버가 죽지 않게
        s = json.dumps(obj)
    _PROTO.write(s + "\n")
    _PROTO.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        if isinstance(msg, list):                     # 묶음 요청(2025-03-26 이전 판)
            if not msg:
                _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
                continue
            out = [r for r in (handle(m) for m in msg) if r is not None]
            if out:
                _send(out)
        else:
            r = handle(msg)
            if r is not None:
                _send(r)


if __name__ == "__main__":
    main()
