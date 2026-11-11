# 공공 GitLab 등록 안내(B-3)

- **대상:** 「2026 공공 AI 대전환 챌린지」 세션 2 산출물 등록
- **등록:** 담당자가 직접 한다. 이 문서는 무엇을 어떻게 올리는지 정리한 것이다.
- **마감:** 11/11까지다. 마감 이후에는 수정할 수 없다.

## 1. 등록 정보

| 항목 | 값 |
|---|---|
| 플랫폼 | 공공 GitLab `gitlab.aigov.go.kr` |
| 공개 범위 | **비공개(Private)** |
| 주제(Topic) | `2026 공공 AI 대전환 챌린지 세션2` |
| 프로젝트 이름(예) | `koat-reg-agent` 또는 「규정 제·개정 에이전트」 |
| 설명(예) | 규정 제·개정 에이전트 — 한 문장 지시로 개정안·신구조문대비표·개정문·검증·문서까지(한국농업기술진흥원) |
| README | 저장소 `README.md` 맨 앞의 “빠른 구동(3분)” 절: 설치 3줄, 접속 주소, 핵심 흐름 3개, 모의데이터 |

## 2. 제출본 만들기 — git 이력 없이 올린다

**이유**
- 저장소의 예전 커밋에는 지운 법제처 Open API 아이디(B-1)와 작업 기록이 남아 있다.
- 그래서 지금 파일만 묶어 새 저장소로 올린다.

**방법:** `git archive`는 커밋된 파일만 이력 없이 묶는다. 아래 3절의 내부 준비 문서는 `.gitattributes`의 `export-ignore`로 자동으로 빠진다.

```bash
# 이 저장소(main 최신)에서
git checkout main && git pull
git archive --format=zip -o koat-reg-agent.zip HEAD
```

새 폴더에 풀어 GitLab에 올린다. 압축 풀기는 Windows 탐색기 ‘압축 풀기’나 아래 python 명령을 쓴다.
- 리눅스 기본 `unzip`은 한글 파일 이름을 깨뜨릴 수 있다. 그래서 python 명령을 권장한다.

```bash
mkdir koat-reg-agent && cd koat-reg-agent
python -m zipfile -e ../koat-reg-agent.zip .
git init -b main
git add . && git commit -m "규정 제·개정 에이전트 — 2026 공공 AI 대전환 챌린지 세션2 제출본"
git remote add origin https://gitlab.aigov.go.kr/<그룹>/<프로젝트>.git
git push -u origin main
```

**올리기 전 확인(풀어 둔 폴더에서)**
- `python -m pytest -q tests`가 모두 통과하는가.
  - 11/11에 이 방법으로 만든 묶음(파일 565개, zip 10.8MB)을 따로 풀어 돌렸다: 428건 통과, JS 91건 통과.
  - 내부 준비 문서는 묶음에 들어가지 않았다. API 키 꼴 문자열은 이 안내 문서의 확인 명령 예시 말고는 없다.
- `python run_local.py` → `http://localhost:5100` 왼쪽 아래에 “등록 내규 126건”이 보이는가.

## 3. 포함·제외 목록

### 포함(커밋된 파일 전부 — 11/8 기준 약 490개, zip 약 10.7MB, 풀면 약 44MB)

| 구분 | 위치 |
|---|---|
| 서버 | `api_server.py`, `reg_agent.py`, `reg_chunks.py`, `reg_import.py`, `reg_upload.py`, `alio.py`, `notation.py`, `hwp5.py`, `hwpx_base.py`, `run_local.py`, `requirements.txt` |
| 화면 | `index.html`, `upload.html`, `assets/`(글꼴 Pretendard·OFL 라이선스 포함) |
| 기관 설정 | `org_config.json` |
| 기본 데이터 | 한국농업기술진흥원 내규 126건(`regulations/`, `regulations_manifest.json`, 의미 검색 색인 `regulations_vectors.*`)<br>알리오 공시 공개본이다. |
| 모의데이터 | `samples/public_org/`(가상행정진흥원 7건), `samples/local_gov/`(가상 지자체 조례 2건) |
| MCP 서버 | `mcp_server/`, `docs/MCP.md` |
| 시험·도구 | `tests/`(Python·JS), `scripts/`(들여오기, 설정 점검, 성과 측정, 구동안내서 점검, 시연영상 제작) |
| 제출 문서 원고 | `docs/contest/`의 다음 문서<br>· 구동안내서, 참가신청서(개요 칸만, 개인정보 없음)<br>· 구동검증, 모델교체시험, 다른기관 도입안내·도입시험<br>· 성과측정, 수작업비교, 시연대본, 시연영상 |
| 라이선스 | `THIRD_PARTY_LICENSES.md`, `assets/fonts/pretendard/LICENSE.txt` |
| 배포 설정(선택) | `vercel.json`, `api/index.py` — 클라우드 시연용이다. 사내 서버에는 쓰지 않는다. |

### 제외

| 무엇 | 왜·어떻게 |
|---|---|
| git 이력 | 예전 커밋에 지운 법제처 아이디가 있다. `git archive`로 이력 없이 묶는다. |
| 내부 준비 문서 5건<br>`진행표.md`·`보완점검.md`·`기능점검.md`·`예상질의.md`·`제출체크리스트.md` | 제출 준비용 작업 기록이다. `.gitattributes`의 `export-ignore`로 자동으로 빠진다. 발표 준비 자료는 담당자가 따로 보관한다. |
| 실행 중 생기는 파일 | 작업 실적 `ledger/`, 시험 결과 `guide_out/`, 영상 산출물 `demo_out/`·`tts_assets/`, 가상환경 `.venv/`, 모의데이터 결과 `po/`·`lg/`, 백업 `regulations.backup-*`<br>모두 커밋되지 않아(`.gitignore`) 묶음에 들어가지 않는다. |
| 개인정보가 들어가는 제출본 | 서명한 참가신청서 PDF, 구동안내서 PDF, 시연영상 mp4는 저장소에 넣지 않는다. 이메일(databus@nia.or.kr)로 따로 낸다. |
| 비밀값 | AI 키, `LAW_OC`, `REG_UPLOAD_TOKEN`은 서버 환경변수로만 둔다. 코드·문서에 없다. |

## 4. 민감자료 없음 재확인(11/8, 커밋된 파일 전체)

| 점검 | 결과 |
|---|---|
| 실명 | 내규 목록의 등록자 이름을 비웠다(B-2). 등록 화면은 “올린 부서”만 받는다. |
| 전화번호 | 2곳 있다. 화면 입력칸 자리표시 예시 `063-919-0000`, 표기 점검 시험 문장의 기관 대표번호 형식 1곳. 개인 번호는 없다. |
| 이메일·주민등록번호 | 0건 |
| API 키·토큰(Gemini `AIza…`·OpenAI `sk-…`·GitHub `ghp_…` 꼴) | 0건 |
| 법제처 아이디 | 코드 기본값 없음. 환경변수 `LAW_OC`로만 받는다(B-1). |
| 다른 기관 실제 자료 | 없음. 다른 기관 예시는 가상 기관(가상행정진흥원·가온군)이다. |
| 내규 원문 | 알리오에 공시된 공개본이다. |

- **확인 명령:** `git grep -nE "0[1-9]{1,2}-[0-9]{3,4}-[0-9]{4}"`, `git grep -nE "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(kr|com|net|org)"`, `git grep -nE "(AIza|sk-|ghp_)"`
- **확인 범위:** `regulations/` 공개본을 뺀 나머지 파일

## 5. 라이선스

- 제3자 구성요소 목록은 `THIRD_PARTY_LICENSES.md`에 있다. Python 패키지 18종과 Pretendard 글꼴(OFL)이고, 재배포가 제한되는 것은 없다.
- **사용자 확인:** 이 저장소 자체 코드의 라이선스(기관 소유·공공누리 등)는 기관이 정한다. 정해지면 `LICENSE` 파일을 더한다.

## 6. 등록 뒤 할 일

1. GitLab 프로젝트 주소를 참가신청서(양식 1-1)의 ‘공공 GitLab 프로젝트 링크’ 칸에 적는다.
2. 온라인 시연 주소를 정하면(B-4) README “빠른 구동(3분)” 2번 줄과 구동안내서에 적는다. 그다음 다시 묶어 올린다(마감 전까지).
3. GitLab 화면에서 README가 첫 화면에 보이는지, 한글 파일 이름(`regulations/여비규정/…`)이 깨지지 않았는지 본다.
