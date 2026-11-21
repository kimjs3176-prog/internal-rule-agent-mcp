# 규정 제·개정 에이전트

한 문장 지시로 개정안·신구조문대비표·개정문·검증·제출 문서까지 만드는 공공기관 규정 관리 웹 서비스입니다.

> 2026 공공 AI 대전환 챌린지 세션2 · 지정과제 ③ 출품작(한국농업기술진흥원)

기관의 내규·지자체의 자치법규·중앙부처의 행정규칙은 구성원 전체의 권리·의무를 정하지만, 이를 다듬는 규정 담당자는 기관마다 한두 명입니다. 이 서비스는 그 담당자가 틀리기 쉬운 일을 먼저 막습니다.

- **개정:** “여비규정 제15조의 일비를 3만원으로 올려줘” 한 문장으로 수정안, 대비표, 개정문, 인용 영향, 검토 보고서, 한글·Word 문서를 만듭니다.
- **검증:** 만든 개정문을 현행 규정에 되돌려 적용해 수정안과 같은지 확인합니다.
- **진단:** 기관 규정 전체에서 없는 조 인용, 옛 명칭, 번호 오류, 상위법 개정 미반영을 찾습니다.
- **확산:** 기관 설정 파일과 규정 원문만 바꾸면 다른 기관에서 씁니다. AI 모델은 바꿔 끼울 수 있고, 핵심 기능은 규칙 기반이라 모델이 없어도 동작합니다.

## 목차

- [빠른 구동(3분)](#빠른-구동3분)
- [주요 기능](#주요-기능)
- [검증 결과](#검증-결과)
- [AI 연결](#ai-연결)
- [다른 기관에서 쓰기](#다른-기관에서-쓰기)
- [MCP로 쓰기](#mcp로-쓰기)
- [관리자 안내](#관리자-안내)
- [구조](#구조)
- [문서](#문서)
- [라이선스](#라이선스)

## 빠른 구동(3분)

**1. 설치·실행** — Python 3.12 이상만 있으면 됩니다. DB·미들웨어가 필요 없습니다.

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: python -m venv .venv  →  .venv\Scripts\activate
pip install -r requirements.txt
python run_local.py
```

**2. 접속** — 브라우저로 `http://localhost:5100`을 엽니다. 왼쪽 아래에 “한국농업기술진흥원 · 등록 내규 126건”이 보이면 정상입니다.

- 온라인 시연 주소: (등록 후 기재)

**3. 핵심 흐름 3개** — 각 1초 안팎입니다.

| # | 해 볼 일 | 결과 |
|---|---|---|
| ① 한 문장 개정 | **에이전트**에 `여비규정 제15조의 일비를 3만원으로 올려줘` → **에이전트 실행** | 별표 2 일비 25,000 → 30,000, 신구조문대비표, 개정문, 개정문 검증(“일치”), 검토 보고서, 한글 문서 |
| ② 제정 | **제정**에 내규명 `업무용 드론 운영지침` → **초안까지 한 번에** | 표준 조문 초안, 형식 점검, 문서 세트 |
| ③ 정비·점검 | **건강검진** → **오류 목록**. 또는 에이전트에 `기획운영본부를 경영기획본부로 모든 내규에서 바꿔줘` | 내규 126건 진단, 25개 내규 35곳 일괄 정비안(조사 교정·개정문·부칙) |

**4. 모의데이터로 다른 기관 도입 해 보기** — 가상 기관 「가상행정진흥원」 내규 7건으로 바꿔 띄웁니다. 결과는 `po/` 폴더에 만들고, 저장소 기본 데이터는 건드리지 않습니다.

```bash
export REG_DIR=po/regulations REG_MANIFEST=po/manifest.json ORG_CONFIG=samples/public_org/org_config.json
python scripts/import_regulations.py samples/public_org/regs --reset
python run_local.py
```

Windows PowerShell에서는 첫 줄을 `$env:REG_DIR="po\regulations"; $env:REG_MANIFEST="po\manifest.json"; $env:ORG_CONFIG="samples\public_org\org_config.json"`로 바꿉니다.

**5. 자동 시험(선택)**

```bash
pip install pytest
python -m pytest -q tests            # 428건
node --test tests/js/*.test.mjs      # 91건, Node.js 18 이상
```

## 주요 기능

| 화면 | 하는 일 |
|---|---|
| 에이전트 | 한 문장 지시를 끝까지 처리합니다: 대상 찾기 → 자료 조사 → 수정안 → 인용 영향 → 점검 → 개정문 검증 → 검토 보고서 → 문서 |
| 건강검진 | 기관 규정 전체를 진단합니다: 점수·등급, 오류 목록, 상위법 개정 미반영, 내규 간 수치 불일치, 유관 기관과의 규정 체계 비교 |
| 개정 · 제정 | 단계별로 직접 합니다: 신구조문대비표, 개정문, 조 이동·신설·삭제, 별표·서식 수정, 심의 사전검토, 심의 제출 문서(hwpx·docx) |
| 일괄 정비 | 바뀐 기관명·직위·내규명을 모든 내규에서 조사까지 맞춰 바꾸고 개정문·부칙을 만듭니다 |
| 상위법 영향 | 법령이 개정되면 그 법을 인용한 내규 조문을 찾습니다 |
| 내규 자문 | 직원 질의에 근거 조문을 찾아 회신 초안을 만듭니다 |
| 찾아보기 | 내규 목록·조문 연혁, 용어 사전, 조직·권한, 인용 관계, 절차 안내, 작업 실적 |

- 다른 공공기관이 알리오에 공시한 규정을 찾아 초안과 수치 비교에 참고할 수 있습니다(알리오에 접속되는 망에서).
- PC와 휴대폰 브라우저에서 모두 됩니다.
- 화면별 자세한 설명은 [`docs/기능상세.md`](docs/기능상세.md)에 있습니다.

## 검증 결과

2026-11-11에 등록 내규 126건으로 다시 잰 값입니다. 모델을 연결하지 않고(규칙 기반) 쟀습니다.

| 항목 | 결과 | 다시 재는 방법 |
|---|---|---|
| 오류 주입 적발 | 흔한 오류 10종을 1,243번 심어 1,243번 적발, 짚은 위치도 모두 정확 | `python scripts/contest_bench.py` |
| 개정문 왕복 검증 | 조 신설·삭제·항 끼워 넣기 등 619건 모두 일치 | `node scripts/contest_bench_ui.js` |
| 한 문장 요청 처리 시간 | 0.4~0.8초 | 같은 스크립트 |
| 조직 명칭 일괄 변경 | 25개 내규 35곳, 0.02초(수작업 산정 약 9.6시간) | `docs/contest/수작업비교.md` |
| 다른 기관 도입 | 가상 기관 내규 7건, 코드 수정 0줄 | `docs/contest/다른기관_도입시험.md` |

측정 방법과 한계는 [`docs/contest/성과측정.md`](docs/contest/성과측정.md)에 있습니다.

## AI 연결

AI 연결은 선택입니다. 수치·낱말·조 단위 편집과 점검·문서 작성은 규칙으로 처리하고, 자유로운 문장 수정안과 초안 작성에 AI를 씁니다.

- **연결:** 화면 오른쪽 위 **[AI 미설정]** 단추에서 제공자(Gemini·Claude·GPT·사내·공통기반)와 모델을 고릅니다.
- **사내·공통기반 모델:** 관리자가 서버 환경변수 `OPENAI_COMPAT_BASE_URL`에 OpenAI 호환 주소(vLLM·Ollama·행정안전부 AI 공통기반)를 넣으면 됩니다. 교체 시험은 [`docs/contest/모델교체시험.md`](docs/contest/모델교체시험.md)에 있습니다.
- **사람 확인:** AI가 쓴 조문은 “AI 원문 그대로 / 사람이 고침”으로 표시하고, 심의 제출 전에 검토자가 확인해야 합니다.
- **전송 범위:** AI를 켜면 개정 의도·질의와 대상 조문 본문이 고른 제공자 서버로 갑니다. 공개 전 개정안은 기관 보안지침에 따라 사내 모델이나 규칙 기반 작업을 쓰세요.
- **키 보관:** AI 키는 서버에 저장하지 않습니다. 브라우저 세션에만 두고 탭을 닫으면 지워집니다.
- **개인정보:** 작성 중인 내용과 작업 실적은 기본으로 사용 중인 브라우저에만 남습니다. 기관 전체 대장은 관리자가 `LEDGER_ENABLED=1`로 켤 때만 남고, 본문·질의·검토자 이름은 보내지 않습니다.

## 다른 기관에서 쓰기

1. `org_config.json`을 복사해 기관명·직위·절차·심의기준을 고칩니다.
2. `python scripts/import_regulations.py <폴더> --reset`으로 규정 원문(HWPX·DOCX·HWP·PDF·텍스트)을 넣습니다.
3. (선택) `python scripts/build_embeddings.py`로 의미 검색 색인을 만듭니다.

- 지자체의 조례·규칙, 중앙부처의 훈령·예규·고시도 같은 엔진으로 다룹니다. 가상 지자체 예시는 `samples/local_gov/`에 있습니다.
- 단계별 안내는 [`docs/contest/다른기관_도입안내.md`](docs/contest/다른기관_도입안내.md)에 있습니다.

## MCP로 쓰기

MCP를 지원하는 AI 도우미가 대화 중에 이 에이전트를 도구 17개로 씁니다. 화면과 같은 엔진·데이터라 결과가 같습니다.

- **원격(URL):** 배포 주소의 `https://<배포 주소>/mcp`를 claude.ai·ChatGPT 커넥터, Claude Code(`--transport http`), VS Code·Cursor에 넣습니다. 설치가 필요 없습니다.
- **내 컴퓨터:** `python mcp_server/server.py`를 Claude Desktop·Claude Code에 등록합니다.
- 등록 방법과 환경변수는 [`docs/MCP.md`](docs/MCP.md)에 있습니다.
- **범용(다른 기관 사규):** 등록하지 않은 기관의 사규도 현행 원문(`source_text`)이나 알리오 공시 규정(`alio_id`)과 기관 이름(`org`)을 주면 `amend_regulation`·`check_regulation`·`enact_regulation`이 그 기관 기준으로 개정문·대비표·검증·문서를 만듭니다. 등록된 내규와는 대조하지 않습니다([`docs/MCP.md`](docs/MCP.md) 4-1절).

## 관리자 안내

**배포:** 사내 서버에서는 `python run_local.py`로 띄웁니다. 클라우드 시연은 Vercel(`api/index.py`, `vercel.json`)을 씁니다.

**환경변수(모두 선택)** — 전체 목록은 `.env.example`에 있습니다.

| 이름 | 용도 |
|---|---|
| `GEMINI_API_KEY` 등 | 서버 공용 AI 키(사용자 키가 우선) |
| `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_API_KEY`, `OPENAI_COMPAT_MODELS` | 사내·공통기반 모델(OpenAI 호환)의 주소, 키(선택), 모델 목록(선택) |
| `LAW_OC` | 법제처 Open API 아이디. 없으면 상위법·행정규칙 조회만 꺼지고 화면에 안내가 나옵니다 |
| `REG_UPLOAD_TOKEN` | 내규 등록 암호 |
| `GITHUB_TOKEN`, `GITHUB_REPO` | 읽기 전용 배포에서 내규 등록·작업 실적을 저장소에 커밋 |
| `LEDGER_ENABLED`, `LEDGER_DIR`, `LEDGER_BRANCH` | 작업 실적 기관 대장(기본 꺼짐)과 그 위치 |
| `ORG_CONFIG`, `REG_DIR`, `REG_MANIFEST` | 기관 프로필·규정 원문 위치 |

**내규 원문 등록**

- 웹: 왼쪽 메뉴 맨 아래 **내규 등록** 단추(`/upload`, 좁은 화면에서는 오른쪽 위 첫 아이콘)에서 HWPX·DOCX·HWP·PDF 등을 올립니다. 이름이 비슷한 기존 내규가 있으면 개정판인지 묻습니다.
- 일괄: `python scripts/import_regulations.py <폴더>`(`--reset`으로 새로 구성)

**알아 둘 점**

- 법제처(상위법)와 알리오(다른 기관 사례) 조회는 그 사이트에 접속되는 망에서만 됩니다. 막히면 그 조사만 빠지고 나머지는 그대로 동작합니다.
- MCP의 개정문·에이전트 도구는 Python 3.12까지는 함께 설치되는 `quickjs`로 돌고, 3.13 이상에서는 Node.js 18 이상이 필요합니다.

## 구조

```
index.html, assets/        화면(색·글꼴·간격은 assets/tokens.css 한 곳에서)
reg_agent.py               에이전트 API(/api/regagent/*)
api_server.py              Flask 서버(법령 조회·AI)
reg_upload.py, upload.html 내규 등록
org_config.json            기관 프로필
regulations/               내규 원문(한국농업기술진흥원 126건, 알리오 공시 공개본)
samples/                   모의데이터(가상 공공기관·가상 지자체)
mcp_server/                MCP 서버(도구, 내 컴퓨터 연결, 원격 /mcp, 화면 엔진 실행기)
scripts/, tests/           등록·색인·측정 스크립트, 자동 시험
docs/                      기능 상세, MCP, 출품 문서(docs/contest/)
```

## 문서

| 문서 | 내용 |
|---|---|
| [`docs/기능상세.md`](docs/기능상세.md) | 화면별 기능, 화면 구성, 지자체·중앙부처에서 쓰기 |
| [`docs/contest/구동안내서.md`](docs/contest/구동안내서.md) | 실행 환경, 설치, LLM 연결, 기능 사용 순서, 알려진 제약 |
| [`docs/contest/성과측정.md`](docs/contest/성과측정.md) | 정량 성과와 측정 방법 |
| [`docs/contest/다른기관_도입안내.md`](docs/contest/다른기관_도입안내.md) | 다른 기관 도입 절차 |
| [`docs/MCP.md`](docs/MCP.md) | MCP 연결 방법과 도구 |

## 라이선스

- 쓰는 패키지·글꼴의 판과 라이선스는 [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)에 있습니다. 재배포가 제한되는 구성요소는 없습니다.
- 이 저장소 자체 코드의 라이선스는 기관이 정합니다.

---

최종 검토: 2026-11-11
