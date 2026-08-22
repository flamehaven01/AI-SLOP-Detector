# AI-SLOP-Detector v3.8.8 — 외부 감사 진단서

**감사일:** 2026-08-21
**대상:** `D:\Sanctum\AI-SLOP-DETECTOR` @ v3.8.8
**계기:** CuraFrame PR 3건(4,688줄)에 대한 slop 검사를 수행하던 중, 도구 출력을 실물 대조하는 과정에서 발견
**방법:** 도구 출력 전 항목을 소스에 대조. 증상이 아니라 코드 위치와 원인을 특정
**재현:** 6건 전부 `patch/repro/red_t*.py`로 실행 가능. 결함 존재 시 exit 1

모든 수치는 이 저장소에서 직접 측정했으며 재현 명령을 함께 적었습니다.

---

## 결함 목록

| ID | 결함 | 위치 | 성격 | 우선순위 |
|---|---|---|---|---|
| T-1 | ML 스코어러가 한 번도 작동한 적 없고, 실패를 숨긴 채 PASS 출력 | `ml/classifier.py:328`, `ml/scorer.py:151` | 신뢰성 | P0 |
| T-2 | 프로젝트 스캔이 테스트 파일을 조용히 제외하고 CLEAN 선언 | `config.py:101-106` | 신뢰성 | P0 |
| T-6 | 텍스트 리포트가 분석이 찾은 패턴 발화를 표시하지 않음 | 렌더러 (per-file status 게이팅) | 신뢰성 | P0 |
| T-3 | 문서 인플레이션 경계 오류 — 4를 4보다 많다고 보고 | `metrics/docstring_inflation.py:69` + `question_generator.py:224` | 오탐 | P1 |
| T-4 | 클론 지표가 의미가 아닌 형태를 보고, 파일이 클수록 오탐 증가 | `metrics/stub_density.py:135-145` | 오탐 | P1 |
| T-5 | Python만 스캔. 문서·설정은 관할 밖이고 그 사실을 알리지 않음 | `cli_analysis.py:23` | 커버리지 | P2 |

**T-1 / T-2 / T-6은 같은 결함 형태입니다: 보지 않았거나 찾아 놓고도 "깨끗하다"고 말하는 것.**
오탐(T-3, T-4)은 사용자의 시간을 낭비시키지만, 이 셋은 **근거 없는 확신을 줍니다.** 후자가 훨씬 비쌉니다.

---

## T-1 — ML 스코어러 스키마 불일치 + 실패 은폐 (P0)

### 증상

```
[WARNING] [MLScorer] Failed to load model: 'model_type'
...
│ Overall Status │ CLEAN │
[Gate Decision] Status : PASS
```

ML 축이 실행되지 않았는데 리포트는 CLEAN / PASS입니다.

### 원인 — 배포된 모델과 로더의 스키마가 완전히 다릅니다

`src/slop_detector/ml/classifier.py:326-330` 이 읽는 키:

```python
self.model_type = model_data["model_type"]
self.rf_model   = model_data["rf_model"]
self.xgb_model  = model_data["xgb_model"]
```

`models/slop_classifier.pkl` 이 실제로 가진 키:

```
['class_priors', 'class_stats', 'feature_importance',
 'features', 'thresholds', 'type', 'version']
```

`model_type` → `type`, `feature_names` → `features`로 이름이 다르고,
**`rf_model`과 `xgb_model`은 아예 없습니다.**
배포된 `.pkl`은 sklearn 앙상블이 아니라 통계 모델(class_priors / class_stats)입니다.

`save()` / `load()` 쌍은 자기들끼리 일관됩니다. 문제는 **`models/`에 놓인 파일을 다른 생산자가 썼다**는 것입니다.

**파일 타임스탬프 2026-05-01.** 그 이후 이 체크아웃의 모든 스캔이 ML 없이 돌았고, 아무도 몰랐습니다.

### 은폐 지점

`src/slop_detector/ml/scorer.py:151-153`

```python
except Exception as e:
    logger.warning("[MLScorer] Failed to load model: %s", e)
    return None      # 스캔은 계속되고, 리포트는 PASS
```

`logger.warning`은 stderr로 한 줄 나가고 리포트 본문에는 흔적이 없습니다.

### 재현

```bash
python patch/repro/red_t1_ml_schema.py
```

---

## T-2 — 테스트 파일 침묵 제외 (P0)

### 증상 (실측)

`governance.py`(263줄) + `tests/test_governance_sink.py`(274줄)가 있는 디렉터리에서:

```
[INFO] Found 1 Python files in .../pr2
│ Total Files │ 1 │  │ Clean Files │ 1 │  │ Overall Status │ CLEAN │
```

**537줄 중 274줄(51%)이 침묵 속에 빠졌고, 리포트는 그 사실을 말하지 않습니다.**

### 원인

`src/slop_detector/config.py:101-106`

```python
"ignore": [
    "**/__init__.py",
    "tests/**",
    "**/*_test.py",
    "**/test_*.py",
    ...
]
```

**제외 자체는 정당한 설계 선택일 수 있습니다** — 테스트는 품질 규범이 다릅니다.
결함은 **제외 사실이 출력 어디에도 없다**는 것입니다. 사용자는 "CLEAN"을 트리 전체에 대한 판정으로 읽습니다.

### 재현

```bash
python patch/repro/red_t2_test_exclusion.py
```

---

## T-6 — 텍스트 리포트가 찾아낸 결함을 감춤 (P0)

### 증상 (자기 코드 스캔 실측)

`slop-detector src --project` 결과:

| | 값 |
|---|---|
| 분석 파일 | 82 |
| **프로젝트 판정** | **clean** |
| deficit files | 3 / 82 |
| **패턴 발화 총계** | **144건** |
| severity 분포 | critical **16**, high 59, medium 49, low 20 |
| **status=clean 파일 안에 있어 텍스트 리포트에 렌더되지 않는 것** | **126건** |

**도구가 자기 코드에서 critical 16건을 찾아 놓고 "clean"이라고 출력합니다.**
`--json`으로만 보입니다.

### 원인

패턴 발화의 렌더링이 **파일 단위 deficit 점수 게이트**에 묶여 있습니다.
deficit이 임계 미만인 파일은 `status=clean`으로 분류되고, 그 파일의 `pattern_issues`는 텍스트 렌더러가 출력하지 않습니다.
severity는 가시성에 영향을 주지 않습니다 — **점수 낮은 파일 안의 critical은 어디에도 나오지 않습니다.**

프로젝트 규모가 커질수록 평균 deficit이 희석되므로, **파일이 많아질수록 더 많이 감춰집니다.**

### 재현

```bash
python patch/repro/red_t6_hidden_findings.py
```

---

## T-3 — 문서 인플레이션 경계 오류 (P1)

### 증상 (실측)

```
[WARNING] (Line 55) '_declare' has more documentation (4 lines)
                                    than implementation (4 lines)
```

**4는 4보다 많지 않습니다.**

### 원인

`src/slop_detector/metrics/docstring_inflation.py:68-70`

```python
CRITICAL_RATIO = 2.0
WARNING_RATIO  = 1.0   # 주석: "Docstring longer than implementation"
INFO_RATIO     = 0.5
```

`ratio = docstring_lines / impl_lines` → `4 / 4 = 1.0` → WARNING 대역에 **포함**됩니다.

`src/slop_detector/question_generator.py:224`

```python
f"'{detail.name}' has more documentation ({detail.docstring_lines} lines) "
f"than implementation ({detail.implementation_lines} lines). "
```

**임계는 경계 포함(`>=`)인데 문구는 엄격 부등호를 주장합니다.**

### 영향

CuraFrame PR 감사에서 나온 docstring 지적 **2건이 전부 이 오류**였습니다 (해당 항목 오탐률 100%).

### 재현

```bash
python patch/repro/red_t3_docstring_boundary.py
```

---

## T-4 — 클론 지표가 형태만 보고, 파일이 클수록 오탐 증가 (P1)

### 원인 — 정규화가 함수 크기를 지웁니다

`src/slop_detector/metrics/stub_density.py:135-145`

```python
def _node_histogram(func_node):
    counts = [0.0] * 30                    # AST 노드 '타입'만 카운트
    for node in ast.walk(func_node):
        idx = _NODE_INDEX.get(type(node).__name__)
        if idx is not None:
            counts[idx] += 1.0
    total = sum(counts)
    return [c / total for c in counts]     # 정규화 = 크기 소멸
```

**버려지는 정보:** 식별자 이름, 상수값, 호출 대상, 반환 타입, **그리고 함수 크기.**
남는 것은 30차원 노드 타입 비율뿐이고, guard clause + early return이라는 파이썬 관용구를 공유하는 함수들은 목적과 무관하게 같은 지점에 모입니다.

### 실측 — 도구 자기 코드에서 최대 66.7%

| 파일 | 함수 | 쌍 | JSD<0.05 | 밀도 | 크기 2배↑ 불일치 |
|---|---:|---:|---:|---:|---:|
| `cli_parsers.py` | 6 | 15 | 10 | **66.7%** | 6 |
| `cli.py` | 31 | 465 | 158 | 34.0% | 5 |
| `renderer_rich.py` | 13 | 78 | 25 | 32.1% | 11 |
| `operations.py` | 7 | 21 | 6 | 28.6% | 4 |
| `question_generator.py` | 14 | 91 | 23 | 25.3% | 1 |

**결정적 증거 — 크기가 다른데 히스토그램이 동일한 사례:**

```
_run_impact_command(5줄)  vs _run_operations_command(10줄)  JSD=0.0000  크기 2.0배
get_changed_files(2줄)    vs build_audit_payload(7줄)       JSD=0.0000  크기 3.5배
_build_arg_parser(209줄)  vs _build_operations_parser(40줄) JSD=0.0304  크기 5.2배
_render_rich_project(69줄) vs _build_header_table(10줄)     JSD=0.0461  크기 6.9배
```

**JSD 0.0000은 두 히스토그램이 문자 그대로 같다는 뜻입니다.** 길이가 2~3.5배 다른데도.

### 패턴 발화 vs 원지표 — 구분해서 읽어야 합니다

`FunctionClonePattern`에는 이미 억제 장치가 있습니다:

```python
# patterns/python_clones.py:255-259
if _is_dispatcher_pattern(tree, result.clone_group_names):        return []
if _is_property_accessor_cluster(tree, result.clone_group_names): return []
```

여기에 `_MIN_FUNCTIONS_FOR_CLONE = 4`와 4-멤버 clique 요건이 더해져 일부 파일에서는 발화하지 않습니다.

**그러나 그 가드들이 하중을 받고 있습니다.** 원지표가 위 밀도로 충돌하는 상태에서, 어떤 파일이 걸리는지는 **그 파일이 함수를 몇 개 가졌는가**에 좌우됩니다. 크고 정상적인 파일일수록 4-멤버 clique가 생길 확률이 높습니다. **방향이 반대입니다.**

**실제 발화 (자기 코드 src/, 5건):**

```
cli.py                16 structurally near-identical: _run_analysis_phase,
                      generate_html_report, generate_markdown_report, generate_text_report, ...
config.py              6: is_abc_exception_enabled, is_config_file_exception_enabled, use_radon, ...
placeholder.py         5: _has_optional_return, check_node, check_node, check_node, check_node
renderer_glossary.py   4: _deficit_health, _ldr_health, _icr_health, _ddc_health
renderer_rich.py       4: _build_rich_summary_tables, _build_rich_files_table, ...
```

`placeholder.py` 항목이 **별도 결함**을 드러냅니다. `check_node`가 4번 나열되는데, 실물 확인 결과 이들은 `PassPlaceholderPattern`, `EllipsisPlaceholderPattern`, `NotImplementedPattern`, `EmptyExceptPattern`, `ReturnNonePlaceholderPattern`, `ReturnConstantStubPattern` 등 **서로 다른 클래스의 동일 인터페이스 구현**입니다.

- 클래스로 한정하지 않고 `node.name`만 쓰므로 리포트가 `check_node, check_node, check_node, check_node`가 되어 **어느 클래스인지 알 수 없습니다**
- 그리고 이것은 Strategy 패턴의 정상 구현입니다. "unnecessary decomposition"이라는 제안은 **정확히 반대 방향**입니다

즉 클론 오탐에는 최소 세 부류가 있습니다:
1. guard-clause 검증 함수군 (CuraFrame `cr_ep_cli.py` 사례)
2. 크기가 크게 다른 함수쌍 (정규화가 지움)
3. **형제 클래스의 인터페이스 구현** (`check_node` 사례)

기존 가드 2개는 1·2·3 중 어느 것도 덮지 않습니다. **네 번째 예외를 추가하는 것이 아니라 판별 채널을 넣어야 합니다.**

### 재현

```bash
python patch/repro/red_t4_clone_fp.py            # 자기 src/ 스캔
python patch/repro/red_t4_clone_fp.py <경로>      # 임의 파일/디렉터리
```

---

## T-5 — Python만 스캔하고 그 사실을 알리지 않음 (P2)

### 원인

`src/slop_detector/cli_analysis.py:23`

```python
for fp in scan_root.rglob("*.py")
```

`languages/`에는 `python_analyzer` / `js_analyzer` / `go_analyzer`만 있고, js·go는 opt-in 플래그입니다.
**Markdown / YAML / JSON 분석기: 없음.**

### 실측

자기 `src/` 트리:

```
scanned (.py)         94 files   23,782 lines   95.2%
opt-in (--js / go)     0 files        0 lines    0.0%
never read             7 files    1,204 lines    4.8%
```

CuraFrame PR(4,688줄) 대상:

```
스캔됨 (Python)      3,431줄   73.2%
미스캔 (JSON 스키마)   672줄
미스캔 (MD/YAML)       564줄
미스캔 (core.py 21줄)   21줄
─────────────────────────────
미스캔 합계          1,257줄   26.8%   ← PR #3 전체
```

### 왜 중요한가

CuraFrame 감사에서 실제로 잡힌 결함 8건이 **전부 그 26.8% 안에 있었습니다:**

| 결함 | 도구가 볼 수 있나 |
|---|---|
| 존재하지 않는 파일을 문서화 | 아니오 |
| 작동하지 않는 롤백 절차 | 아니오 |
| 문서 내 로컬 절대경로 (`D:\Sanctum\...`) | 아니오 |
| 낡은 수치 3종 (286행 vs 실제 430행 등) | 아니오 |
| `.gitignore` 이름 드리프트 (960KB 추적) | 아니오 |
| CI 26배 감속 (`ci.yml`) | 아니오 |
| 루트 선언 문서의 거짓 진술 | 아니오 |

`--ci-claims-strict`가 있지만 이는 **코드 안의 주장**("production/enterprise/scalable" 같은 단어에 통합 테스트가 있는가)을 검사할 뿐, **문서-코드 정합성은 보지 않습니다.**

### 재현

```bash
python patch/repro/red_t5_coverage.py
```

---

## 감사 소견

이 도구는 CuraFrame PR 감사에서 지적 7건 중 **VALID 3 / FALSE POSITIVE 3 / 정보 1**, 실효 정확도 약 43%를 기록했습니다. 그리고 그 3건의 VALID 중 1건(`main()` 301줄 god function)은 **수동 감사 8회가 놓친 것**이었습니다. 도구를 돌린 것은 정당했습니다.

그러나 정확도는 이 진단서의 주제가 아닙니다.

**T-1 · T-2 · T-6은 도구가 "보지 않은 것" 또는 "찾아 놓고 말하지 않은 것"을 "깨끗하다"로 보고하게 만듭니다.** 2026-05-01 이후 모든 스캔이 ML 축 없이 돌았고, 모든 프로젝트 스캔이 테스트를 빼고 CLEAN이라 말했으며, 자기 코드의 critical 16건이 텍스트 리포트에 한 줄도 나오지 않았습니다.

오탐은 사용자의 시간을 씁니다. 이 셋은 사용자의 판단을 삽니다.

이번 주 P0 세 건은 알고리즘 개선이 아니라 **정직성 수정**이며, 각각 수 줄입니다.
