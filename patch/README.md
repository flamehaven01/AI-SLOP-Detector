# patch/ — v3.8.9 감사 및 패치 문서

**초기 감사:** 2026-08-21 · AI-SLOP-Detector v3.8.8
**재검증:** 2026-08-22 · AI-SLOP-Detector v3.8.9
**계기:** CuraFrame PR 3건(4,688줄) slop 검사 중, 도구 출력을 실물 대조하다가 발견

This directory preserves the original audit evidence as a historical baseline.
For the remediated state and bounded validation results, see
[PATCH_PLAN_REVALIDATED.md](PATCH_PLAN_REVALIDATED.md) and
[CURAFRAME_REVALIDATION.md](CURAFRAME_REVALIDATION.md).

---

## 파일

| 파일 | 내용 |
|---|---|
| [FINDINGS.md](FINDINGS.md) | 결함 6건의 근본 원인. 코드 위치, 재현 수치, 왜 그렇게 되는지 |
| [PATCH_PLAN.md](PATCH_PLAN.md) | P0–P4 계획. 사전 확정 수용 기준, 이번 주 실행 순서 |
| [PATCH_PLAN_REVALIDATED.md](PATCH_PLAN_REVALIDATED.md) | 수정 후 P0–P4 실행 결과와 release gate evidence |
| [CURAFRAME_REVALIDATION.md](CURAFRAME_REVALIDATION.md) | CuraFrame 재측정 결과와 남은 경계 |
| `repro/red_t*.py` | 결함별 RED 재현 스크립트. 결함 존재 시 exit 1 |
| `repro/contract_t*.py` | 수정 후 출력 계약을 검증하는 GREEN 스크립트 |

---

## 결함 6건 요약

| ID | 결함 | 위치 | 우선순위 |
|---|---|---|---|
| T-1 | ML 스코어러가 2026-05-01 이후 한 번도 작동하지 않았고, 실패를 숨긴 채 PASS 출력 | `ml/classifier.py:328`<br>`ml/scorer.py:151` | **P0** |
| T-2 | 프로젝트 스캔이 테스트 파일을 조용히 제외하고 CLEAN 선언 | `config.py:101-106` | **P0** |
| T-6 | 텍스트 리포트가 분석이 찾은 패턴 발화 144건 중 126건을 표시하지 않음 | 렌더러 (deficit 게이팅) | **P0** |
| T-3 | 문서 인플레이션 경계 오류 — 4를 4보다 많다고 보고 | `docstring_inflation.py:69`<br>`question_generator.py:224` | P1 |
| T-4 | 클론 지표가 형태만 보고, 파일이 클수록 오탐 증가 (최대 66.7%) | `stub_density.py:135-145` | P1 |
| T-5 | Python만 스캔. 문서·설정은 관할 밖이고 그 사실을 알리지 않음 | `cli_analysis.py:23` | P2 |

**T-1 · T-2 · T-6은 같은 형태입니다: 보지 않았거나, 찾아 놓고도 "깨끗하다"고 말하는 것.**

---

## 재현 실행

전부 저장소 루트에서 실행합니다. 외부 체크아웃이 필요 없고, 이 저장소 자신을 대상으로 돕니다.

```bash
python patch/repro/red_t1_ml_schema.py
python patch/repro/red_t2_test_exclusion.py
python patch/repro/red_t3_docstring_boundary.py
python patch/repro/red_t4_clone_fp.py
python patch/repro/red_t5_coverage.py
python patch/repro/red_t6_hidden_findings.py
```

한 번에:

```bash
for f in patch/repro/red_t*.py; do python "$f" >/dev/null 2>&1; echo "$f exit=$?"; done
```

**초기 v3.8.8 실행에서는 6개 전부 exit 1 (RED)였습니다.** 이 기록은
발견 당시의 기준선이며, v3.8.9의 재검증 결과로 해석하면 안 됩니다.
수정 후 계약 검증은 `contract_t*.py`와
[PATCH_PLAN_REVALIDATED.md](PATCH_PLAN_REVALIDATED.md)를 기준으로 합니다.

`red_t6`은 전체 스캔을 돌리므로 1분 정도 걸립니다. 나머지는 즉시 끝납니다.

---

## 자기 코드 스캔이 말하는 것

```
slop-detector src --project

  분석 파일        82
  프로젝트 판정    clean
  deficit files    3 / 82

  실제 패턴 발화   144건  (critical 16, high 59, medium 49, low 20)
  텍스트에 미표시  126건
  ML 축            미실행 (2026-05-01 이후)
```

초기 감사에서 도구는 자기 코드의 critical 16건을 찾아 놓고 "clean"이라고
출력했습니다. v3.8.9는 finding summary와 scan coverage를 별도로 노출해 이
상태를 숨기지 않도록 바꿨습니다.

---

## 이번 주 순서

1일차 작업 4건은 전부 **표기 추가 또는 한 줄 수정**이며 알고리즘을 건드리지 않습니다.
이것만으로 T-2 · T-6 · T-3과 T-5의 절반이 해소됩니다.

```
1일차   P0-1a  텍스트 리포트에 패턴 총계
        P0-2a  Excluded Files 표기
        P2-a   Unscanned 표기
        P1-1   docstring 비교 연산자
2일차   P0-3   ML 실패 은폐 차단 (모델 재학습은 범위 밖)
        P0-1b  critical 게이팅 정책 결정
3일차   P3     회귀 코퍼스 + 계약 테스트     ← P1-2의 전제
4-5일차 P1-2   클론 판별 채널
        P2-b/c 문서 경로 검증
마감    P4     재측정 → 3.8.9
```

세부 수용 기준은 [PATCH_PLAN.md](PATCH_PLAN.md)에 있습니다.

---

## 주의

- **P1-2(클론)는 P3-2(회귀 코퍼스) 없이 착수하지 마십시오.** 진짜 클론 코퍼스 없이 임계값을 조이면 탐지력을 잃고 그 사실을 모릅니다.
- **P0-1b는 정책 결정입니다.** critical이 `clean`을 막게 하면 이 저장소 자신의 CI가 빨간불이 됩니다. 그것이 정확한 결과일 수 있으나 결정은 오너의 것입니다.
- **P2에서 "문서 주장이 실제로 되는가"는 시도하지 마십시오.** 정적 분석 범위 밖입니다. 할 수 있다고 주장하면 T-1과 같은 형태의 거짓말이 됩니다.
