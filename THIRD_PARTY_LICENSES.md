# 제3자 구성요소와 라이선스

이 서비스에 들어가거나 함께 배포되는 외부 구성요소와 그 라이선스입니다. 재배포가 제한되는 구성요소는 없습니다.

- **확인 날짜:** 2026-11-07
- **확인 방법:** 새 가상환경(Python 3.12)에 `pip install -r requirements.txt`로 설치된 패키지를 그대로 조사했습니다(설치 정보의 License 항목).
- **이 저장소의 자체 코드:** 기관이 정한 라이선스를 따릅니다.

## 1. 실행에 필요한 Python 패키지

`requirements.txt`의 8종과, 그 패키지들이 함께 설치하는 9종을 더한 17종입니다.

| 패키지 | 설치된 판 | 라이선스 | 출처 |
|---|---|---|---|
| Flask | 3.1.3 | BSD-3-Clause | https://github.com/pallets/flask |
| flask-cors | 6.0.5 | MIT | https://github.com/corydolphin/flask-cors |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3 |
| numpy | 2.5.4 | BSD-3-Clause(일부 0BSD·MIT·Zlib·CC0-1.0) | https://numpy.org |
| defusedxml | 0.7.1 | PSF-2.0 | https://github.com/tiran/defusedxml |
| olefile | 0.47 | BSD-2-Clause | https://github.com/decalage2/olefile |
| pypdf | 6.21.4 | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| Werkzeug *(Flask)* | 3.1.9 | BSD-3-Clause | https://github.com/pallets/werkzeug |
| Jinja2 *(Flask)* | 3.1.6 | BSD-3-Clause | https://github.com/pallets/jinja |
| MarkupSafe *(Flask)* | 3.0.4 | BSD-3-Clause | https://github.com/pallets/markupsafe |
| itsdangerous *(Flask)* | 2.2.0 | BSD-3-Clause | https://github.com/pallets/itsdangerous |
| click *(Flask)* | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click |
| blinker *(Flask)* | 1.9.0 | MIT | https://github.com/pallets-eco/blinker |
| certifi *(requests)* | 2026.10.23 | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer *(requests)* | 3.5.2 | MIT | https://github.com/jawah/charset_normalizer |
| idna *(requests)* | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |

- 판은 설치 시점의 최신판입니다. `requirements.txt`는 최소 판만 정합니다.
- **certifi(MPL-2.0):** 인증서 묶음입니다. 파일을 고치지 않고 그대로 쓰므로, 수정본 공개 의무는 생기지 않습니다.

## 2. 저장소에 함께 들어 있는 것

| 구성요소 | 위치 | 라이선스 | 비고 |
|---|---|---|---|
| Pretendard 글꼴 1.3.9(Variable, 동적 서브셋) | `assets/fonts/pretendard/` | SIL OFL 1.1 | 저작권 Kil Hyung-jin. 라이선스 전문을 `assets/fonts/pretendard/LICENSE.txt`로 함께 넣었습니다. 글꼴만 따로 팔지 않는 한 자유롭게 쓰고 재배포할 수 있습니다 |

- 화면(HTML·CSS·JavaScript)은 외부 라이브러리 없이 직접 작성했습니다.
- **알리오 조회(`alio.py`):** 요청 방식만 MIT 라이선스 오픈소스 [alio-mcp](https://github.com/chromehearts79/alio-mcp)를 참고했고, 코드는 직접 작성했습니다.

## 3. 선택 실행 환경(설치하면 쓰는 기능)

| 구성요소 | 쓰는 곳 | 라이선스 |
|---|---|---|
| Node.js 18 이상 | MCP 서버의 개정문·대비표 도구(`mcp_server/engine.mjs`), 화면 로직 시험 | MIT |
| AI 모델(Gemini·Claude·GPT, 사내·공통기반 모델) | AI 수정안·초안(선택) | 각 제공자의 이용약관·모델 라이선스를 따릅니다. 이 저장소에는 모델이 들어 있지 않습니다 |

## 4. 개발·시연 자료 제작에만 쓴 도구(서비스에는 들어가지 않음)

| 도구 | 쓰임 | 라이선스 |
|---|---|---|
| pytest | 자동 시험 | MIT |
| Playwright·Chromium | 화면 시험·시연영상 녹화 | Apache-2.0 · BSD-3-Clause |
| ffmpeg | 시연영상 인코딩 | LGPL-2.1+ / GPL(빌드에 따라) |
| Supertonic 3 | 시연영상 음성(오프라인 TTS) | 코드 MIT · 모델 OpenRAIL-M |
| kordoc | 제출 서식(HWPX) 채우기·검증 | MIT |

## 5. 데이터

- **기본 내규 126건:** 알리오(공공기관 경영정보 공개시스템)에 공시된 한국농업기술진흥원 내부규정 공개본입니다.
- **모의데이터(`samples/`):** 가상 기관 자료로, 실제 기관과 관계없습니다.
