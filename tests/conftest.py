import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 법제처 Open API 아이디는 서버 환경변수로만 받는다(코드에 기본값 없음). 시험은 법제처 호출을 모두 가짜로 바꾸므로 임의 값을 둔다.
os.environ.setdefault("LAW_OC", "test-oc")


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
