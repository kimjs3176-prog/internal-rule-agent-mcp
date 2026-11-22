import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 법제처 Open API 아이디는 서버 환경변수로만 받는다(코드에 기본값 없음). 시험은 법제처 호출을 모두 가짜로 바꾸므로 임의 값을 둔다.
if not os.environ.get("LAW_OC"):                 # 빈 값으로 내보낸 셸에서도 시험이 같게 돈다
    os.environ["LAW_OC"] = "test-oc"
# 시험은 한 주소(127.0.0.1)에서 1분에 수백 번 MCP 를 부른다 — 분당 상한은 따로 시험하고(test_mcp_remote) 나머지에서는 넉넉히
os.environ.setdefault("MCP_PER_MIN", "1000000")


@pytest.fixture(scope="session")
def client():
    import api_server
    api_server.app.config["TESTING"] = True
    return api_server.app.test_client()


@pytest.fixture(scope="session")
def ra():
    import api_server  # noqa: F401 — 블루프린트 등록(HWPX 기본 서식 등 컨텍스트)
    import reg_agent
    return reg_agent


def engine_ok():
    """MCP 화면 엔진 도구를 돌릴 수 있는가: quickjs 패키지나 Node.js."""
    try:
        import quickjs  # noqa: F401
        return True
    except ImportError:
        import shutil
        return bool(shutil.which("node"))


needs_engine = pytest.mark.skipif(not engine_ok(), reason="MCP 엔진 도구는 quickjs 패키지나 Node.js 가 필요하다")
