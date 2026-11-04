# 가상 공공기관 예시 (가상행정진흥원)

다른 공공기관이 자기 내규로 에이전트를 쓰는 경로를 시험하는 예시입니다. **실제 기관이 아닌 가상 기관**이며, 내규 7개는 시험용으로 지어낸 것입니다.

| 파일 | 내용 |
|---|---|
| `regs/` | 내규 원문 7개. 텍스트 6개와 Word(docx) 1개입니다. 파일명 괄호 안은 개정 정보로 쓰입니다. |
| `org_config.json` | 기관 프로필(기관명·약칭·기관장·옛 명칭 등). 운영 중인 `org_config.json`과 다른 항목은 7개입니다. |

## 돌려 보기

```bash
# 1) 내규 들여오기 — 저장소 데이터는 건드리지 않도록 별도 폴더에 만든다
export REG_DIR=/tmp/public_org/regulations REG_MANIFEST=/tmp/public_org/manifest.json
python scripts/import_regulations.py samples/public_org/regs --reset

# 2) 기관 프로필을 바꿔 서버 실행
ORG_CONFIG=samples/public_org/org_config.json PORT=5200 python run_local.py

# 3) 설정 점검 — 근거 조항이 우리 규칙에 있는지 등
ORG_CONFIG=samples/public_org/org_config.json python scripts/check_org_config.py
```

단계별 자세한 안내는 `docs/contest/다른기관_도입안내.md`에 있습니다. 자동 시험은 `tests/test_public_org.py`입니다. 들여오기부터 조문 해석, 인용 영향, 제정 초안, 건강검진까지 확인합니다.
