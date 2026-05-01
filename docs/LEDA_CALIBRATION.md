# LEDA Calibration Engine — 기술 문서 및 Dogfooding 이력

> **상태:** 1차 Dogfooding 완료 | Global Weight Injection 완료
> **엔진 버전:** LEDA v3.5 | self_calibrator.py v3.5.0 | global_injector.py v1.0
> **최종 갱신:** 2026-05-01

---

## 0. 빠른 시작 (AI 컨텍스트 복구용)

```
# 단일 레포 Dogfooding (진입점)
D:\Sanctum\ai-slop-detector\scripts\leda_turbo.bat "D:\Sanctum\Extra Repo\<REPO>" <N>

# 글로벌 가중치 재주입 (새 레포 3개 이상 추가 후)
D:\Sanctum\ai-slop-detector\.venv\Scripts\python.exe scripts\global_injector.py

# Dry-run (소스 수정 없이 합성값 확인만)
... global_injector.py --dry-run
```

---

## 1. 파일 맵 (현행 확정 구조)

```
D:\Sanctum\ai-slop-detector\
├── scripts\                          ← [SOVEREIGN ASSET] 모든 LEDA 자동화 도구
│   ├── leda_turbo.bat                ← v3.5  Turbo Protocol 진입점 (BAT wrapper)
│   ├── leda_helper.py                ← v3.4  Python 자동화 엔진 (select/fixloop/compare/delta/gapcheck)
│   ├── global_injector.py            ← v1.0  글로벌 가중치 합성 + 소스코드 주입 ★
│   ├── injection_report.json         ← 마지막 주입 결과 감사 증적 (자동 생성)
│   └── generate_download_chart.py    ← (기존 스크립트, LEDA 무관)
│
├── src\slop_detector\
│   ├── config.py                     ← [주입 대상] DEFAULT_CONFIG + DOMAIN_PROFILES
│   └── ml\
│       └── self_calibrator.py        ← [주입 대상 + LEDA 알고리즘 코어]
│
└── docs\
    └── LEDA_CALIBRATION.md           ← 이 문서
```

> **[!] 구버전 루트 파일 정리 완료:**
> `D:\Sanctum\ai-slop-detector\leda_helper.py` — 2026-05-01 삭제됨
> `D:\Sanctum\leda_turbo.bat` — `scripts\leda_turbo.bat`으로 이관됨

---

## 2. 시스템 아키텍처 전체 흐름

```
[External Repo Dogfooding]
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  scripts\leda_turbo.bat  (LEDA TURBO PROTOCOL v3.5) │
│                                                     │
│  STEP 0: Config check (.slopconfig.yaml 존재 확인)  │
│  STEP 1: Baseline Scan                              │
│    → scan_1.json, leda_1.yaml, calibration_1.txt   │
│  STEP 2: File Selection (fixable_ratio 기준)        │
│    leda_helper.py select                            │
│    ├── AUTOFIX 패턴만 있는 파일 최우선              │
│    ├── 구조적 Ceiling 파일 후순위                   │
│    └── → selected_files.txt                         │
│  STEP 3: Auto Fix Loop (--auto 무인 모드)           │
│    leda_helper.py fixloop --auto                    │
│    ├── bare_except, mutable_default_arg 자동 적용   │
│    ├── dry-run → "Would fix 0" → AUTO-SKIP          │
│    └── pre/post scan → REGRESSED → 경고 출력        │
│  STEP 4: Final Scan                                 │
│    → scan_final.json, leda_final.yaml               │
│  STEP 5: LEDA Compare + Score Delta                 │
│    leda_helper.py compare + delta                   │
│  STEP 6: Calibration Gate                           │
│    confidence_gap >= 0.10 → --apply-calibration     │
│    < 0.10 → "signal accumulating" + injector hint   │
└─────────────────────────────────────────────────────┘
        │  leda_final.yaml (모든 타겟에 누적)
        ▼
┌─────────────────────────────────────────────────────┐
│  scripts\global_injector.py  (v1.0)                 │
│                                                     │
│  STEP 1: Harvest                                    │
│    D:\Sanctum\Extra Repo\*\slop_reports\            │
│    leda_final.yaml 전수 파싱                        │
│  STEP 2: Filter & Synthesize                        │
│    Quality Gate: confidence_gap >= 0.05 + events >= 50 │
│    Fallback: valid optimal_weights 보유한 전체      │
│    vote_weight = improvement_events × (1 + gap)     │
│    → Weighted Average → Clamp[0.10,0.65] → Normalize │
│  STEP 3: Inject                                     │
│    config.py L31: DEFAULT_CONFIG["weights"]         │
│    config.py L199: DOMAIN_PROFILES["general"]       │
│    self_calibrator.py L174: calibrate() fallback    │
│  STEP 4: Report                                     │
│    → scripts\injection_report.json                  │
└─────────────────────────────────────────────────────┘
```

---

## 3. 핵심 알고리즘: LEDA Weight Calibration

### 3.1 4차원 가중치 구조 (GQG Geometric Mean)

```python
# GQG = Geometric Quality Grade
deficit_score = 100 × (1 - GQG)

GQG = exp(
    (w_ldr   × log(LDR)
   + w_inf   × log(1 - min(inflation, 2.0) / 2.0)
   + w_ddc   × log(DDC_usage_ratio)
   + w_pur   × log(exp(-0.5 × n_critical_patterns)))
    / (w_ldr + w_inf + w_ddc + w_pur)
)
```

### 3.2 Event 레이블링 (User Behaviour 기반, 타우톨로지 방지)

```
improvement_event  → deficit[i] > 25.0 AND drop >= 10.0 AND git_commit 변경
fp_candidate       → deficit[i] > 25.0 AND file_hash 동일 AND |delta| < 5.0
                     AND git_commit 동일(또는 git 없음) AND 파일당 1회만
```

### 3.3 Confidence Gap (Copilot Guardian 패턴)

```
gap = candidates[1].combined - candidates[0].combined
gap < 0.0001: tiebreak으로 대체
gap < CONFIDENCE_GAP(0.10): weight update 차단 → insufficient_data
```

### 3.4 fixable_ratio 선택기 (Ceiling 회피 핵심)

```python
AUTOFIX   = {bare_except, pass_placeholder, mutable_default_arg, ...}
UNFIXABLE = {god_function, function_clone_cluster, nested_complexity}

fixable_ratio = len(AUTOFIX_patterns) / max(total_patterns, 1)
structural_ceiling = len(unfixable) > 2 OR (unfixable+manual) > fixable*3

# 정렬 우선순위:
# 1. has_autofix (True 우선)
# 2. no_ceiling (False 우선)
# 3. fixable_ratio DESC
# 4. deficit_score DESC
```

---

## 4. Dogfooding 이력 (2026-05-01, 1차 캘리브레이션)

### 4.1 타겟 레포지토리

| 레포 | 규모 | avg_deficit | confidence_gap | optimal_weights (ldr/inf/ddc/pur) |
|------|------|------------|----------------|----------------------------------|
| AI-Scientist | 128파일 | high | 0.0076 | 0.15/0.10/0.65/0.10 |
| LMCache | 334파일 | med | 0.0269 | 0.15/0.10/0.65/0.10 |
| minGPT | 7파일 | 53 | 0.0076 | 0.15/0.10/0.65/0.10 |
| OpenMythos | 8파일 | med | 0.0076 | 0.15/0.10/0.65/0.10 |
| sloppylint | 14파일 | 16.89 | 0.0019 | 0.15/0.20/0.55/0.10 |
| unsloth | 160파일 | ~49 | 0.0019 | 0.15/0.20/0.55/0.10 |
| unstructured | 133파일 | 16 | 0.0073 | 0.15/0.10/0.65/0.10 |

### 4.2 실측 Weight Drift 관측

```
[unsloth, N=6 run]
  inflation: opt 0.10 → 0.20  (+0.10)  이유: ML 코드의 bare_except 밀도
  ddc:       opt 0.65 → 0.55  (-0.10)  이유: LMCache 과잉 보정 자가 회복

[sloppylint 구조 리팩토링 후]
  hallucinations.py → PlaceholderPatternBase 기반 클래스 추출
  helpers.py        → deep nesting 제거
  → deficit score 유의미 하락 확인
```

### 4.3 Global Injection 결과 (2026-05-01 적용)

**합성된 글로벌 가중치 (7개 레포, vote-weight 가중 평균):**

```
  ldr         0.1500  ######
  inflation   0.1285  #####
  ddc         0.6215  ########################
  purity      0.1000  ####
```

**변화 해석:**

| 차원 | 이전 | 이후 | 변화 | 해석 |
|------|------|------|------|------|
| ldr | 0.40 | **0.15** | -62.5% | 단순 Logic Density가 FP 과잉의 주원인 |
| inflation | 0.30 | **0.13** | -57% | ML/OS 코드의 bare_except 과잉 패널티 |
| ddc | 0.30 | **0.62** | +107% | 의존성 사용률이 실질 Slop의 핵심 지표 |
| purity | 0.10 | **0.10** | 0% | 안정 — 변동 없음 |

---

## 5. leda_helper.py 커맨드 레퍼런스

```bash
python scripts\leda_helper.py select   <scan.json> [N]
python scripts\leda_helper.py fixloop  <selected.txt> <python> [cfg] [--auto]
python scripts\leda_helper.py compare  <leda_1.yaml> <leda_final.yaml>
python scripts\leda_helper.py delta    <scan_1.json> <scan_final.json>
python scripts\leda_helper.py gapcheck <leda_final.yaml>
  → stdout: "OK" | "LOW 0.0019"
```

## 6. global_injector.py 커맨드 레퍼런스

```bash
# 기본 실행 (Extra Repo 전체 하베스트 → 주입)
python scripts\global_injector.py

# 변경 없이 합성 결과만 확인
python scripts\global_injector.py --dry-run

# 다른 Extra Repo 디렉토리 지정
python scripts\global_injector.py --extra-repos "E:\OtherRepos"
```

**출력 파일:** `scripts\injection_report.json`

---

## 7. 슬롭_리포트 출력물 설명

```
<TARGET>\slop_reports\
  scan_1.json            ← 기준선 전체 스캔 (JSON)
  leda_1.yaml            ← 기준선 LEDA 상태 (calibration 포함)
  calibration_1.txt      ← 기준선 캘리브레이션 텍스트
  selected_files.txt     ← 자동 선택된 Fix 타겟 파일 목록
  <file>_before.json     ← 파일별 Fix 전 스캔
  <file>_after.json      ← 파일별 Fix 후 스캔
  <file>_fix_preview.txt ← dry-run 미리보기
  <file>_fix.txt         ← 실제 Fix 로그
  scan_final.json        ← 최종 전체 스캔
  leda_final.yaml        ← 최종 LEDA 상태 ★ (global_injector 입력)
  calibration_final.txt  ← 최종 캘리브레이션
  gap_check.txt          ← "OK" or "LOW 0.XXXX"
```

---

## 8. 다음 단계 (Next Actions)

1. **confidence_gap 0.10 돌파를 위한 추가 Dogfooding:**
   - 소규모 고밀도 레포 (50~100파일) 추가 스캔
   - N=20~30으로 improvement_events 밀도 집중 확보
   - 현재 LMCache가 gap=0.0269으로 가장 근접 → 집중 공략 권장

2. **global_injector.py 재실행 기준:**
   - 신규 Dogfooding 타겟 3개 이상 추가 시
   - 첫 trusted signal (gap >= 0.05 + events >= 50) 출현 시

3. **Sentinel V-Engine 통합:**
   - 가중치 안정화 확인 후 `SENTINEL_CERT.md` 업데이트
   - `git commit -am 'feat(leda): inject dogfooding-calibrated global weights v2'`
