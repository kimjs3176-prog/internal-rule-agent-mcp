# MCP로 쓰기 — 규정 제·개정 에이전트를 AI 도우미의 “도구”로

규정 제·개정 에이전트를 **MCP(Model Context Protocol) 서버**로도 쓸 수 있다. MCP를 지원하는 AI 도우미에 등록하면, 그 AI가 대화 중에 이 에이전트의 기능을 직접 부른다. Claude Desktop, Claude Code, ChatGPT 개발자 모드, VS Code Copilot, Cursor, 사내 에이전트 플랫폼 등이 MCP를 지원한다.

- **같은 엔진:** 웹 화면과 같은 엔진과 같은 내규 데이터를 쓴다. 개정문 문형, 신구조문대비표, 개정문 검증, 조문 점검이 화면과 똑같이 나온다.
- **모델 비종속:** 어떤 AI가 부르든 결과는 이 서버의 규칙 엔진이 만든다. AI는 요청을 이해하고 문장을 쓰는 역할만 한다.
- **추가 설치 없음:** 웹 서비스의 `requirements.txt`만으로 돈다(표준 입출력 JSON-RPC). 개정문·대비표·에이전트 도구는 Node.js 18 이상이 필요하다.
- **읽기 위주:** 내규 원문은 읽기만 한다. 파일을 쓰는 것은 `output_dir`을 지정했을 때 문서 세트를 저장하는 것뿐이다. 내규 등록이나 대장 기록 같은 쓰기 기능은 넣지 않았다.

## 1. 실행

```
python mcp_server/server.py
```

- **기관·데이터 위치:** 웹 서비스와 같은 환경변수를 따른다.
  - `ORG_CONFIG`, `REG_DIR`, `REG_MANIFEST`: 다른 기관 프로필과 내규 원문 위치
  - `LAW_OC`: 법제처 조회(상위법)
- **수동 실행은 필요 없다:** 아래처럼 AI 도우미에 등록하면 도우미가 직접 띄운다.

## 2. AI 도우미에 등록

**Claude Desktop**: `claude_desktop_config.json`

```json
{
  "mcpServers": {
    "reg-agent": {
      "command": "python",
      "args": ["C:\\reg-agent\\mcp_server\\server.py"],
      "env": { "LAW_OC": "법제처 Open API 아이디" }
    }
  }
}
```

**Claude Code**

```
claude mcp add reg-agent -- python /경로/mcp_server/server.py
```

**그 밖의 MCP 클라이언트**
- 방식: “표준 입출력(stdio)” 서버
- 명령: `python`
- 인자: `mcp_server/server.py`의 전체 경로
- 지원 판: 2025-06-18, 2025-03-26, 2024-11-05

## 3. 도구

| 도구 | 하는 일 |
|---|---|
| `run_agent` | 한 문장 요청을 웹 화면의 에이전트와 똑같이 끝까지 처리한다(개정·조 삭제·일괄 정비·제정·자문). 단계별 작업 내역과 결론을 돌려주고, 개정이면 개정문·신구조문대비표·개정문 검증을 함께 준다 |
| `amend_regulation` | AI가 고친 조문 전문을 받아 개정문, 신구조문대비표, 개정문 검증, 조문 점검, 인용 영향을 돌려준다. 문서 세트(한글·Word)도 저장할 수 있다 |
| `get_regulation` | 내규 조문 원문(전체 또는 고른 조)과 별표 |
| `search_regulations` · `list_regulations` | 낱말 검색, 내규 목록 |
| `check_regulation` | 내규 하나나 붙여 넣은 조문의 형식 점검(없는 조문 인용, 항·호 번호, 옛 명칭, 표기) |
| `health_check` | 기관 내규 전체 건강검진(점수·등급·문제가 많은 내규) |
| `citation_impact` | 고치거나 지울 조를 인용하는 조·내규·별표 |
| `upper_law_impact` | 상위법 개정 시 그 법을 인용하는 내규 조문 |
| `bulk_rename` | 모든 내규의 명칭 일괄 정비안(내규별 개정문) |
| `advise` | 내규 질의에 근거 조문 회신 |

- **요청을 바로 처리하기:** “여비규정 제15조의 일비를 3만원으로 올려줘”처럼 수치·낱말·조 삭제 요청은 `run_agent` 하나로 끝난다.
- **AI가 직접 고쳐 쓰기:** 자유로운 문장 수정은 AI가 `get_regulation`으로 현행 조문을 읽고 고쳐 쓴 뒤 `amend_regulation`에 넣는다. 그러면 개정문과 검증은 규칙 엔진이 맡는다.
- **검증 결과 알리기:** 개정문 검증(`verification.ok`)이 실패하거나 점검 오류가 나오면 AI가 사용자에게 그대로 알리도록 서버 안내문(instructions)에 적어 두었다.

## 4. 확인(2026-11-06)

- **자동 시험:** `tests/test_mcp_server.py` 4건. 실제 서버를 띄워 표준 입출력으로 주고받는다.
  - 초기화와 도구 목록
  - 옛 판 협상
  - 읽기 도구 7종
  - 엔진 도구: 조 삭제 개정문과 검증·제24조 인용 오류 짚기·한글 파일 저장, 에이전트 “일비 3만원”
- **공식 SDK로 확인:** MCP 공식 Python SDK(mcp 2.3.0) 클라이언트로 초기화 → 도구 목록 → `run_agent` → `check_regulation`이 정상으로 오갔다.
- **처리 시간:** 엔진 도구는 한 번에 0.2~0.5초다(AI 키·외부망 없이).
