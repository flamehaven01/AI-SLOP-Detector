# AI SLOP Detector Configuration Examples

The canonical project config surface is `.slopconfig.yaml`.

---

## Example 1: Minimal Baseline

```yaml
weights:
  ldr: 0.40
  inflation: 0.30
  ddc: 0.20
  purity: 0.10

ignore:
  - "tests/**"
  - "**/__init__.py"
  - ".venv/**"
```

## Example 2: Large-Repo Operational Defaults

```yaml
advanced:
  exact_topology_ceiling: 300
  topology_mode_above_ceiling: deterministic_approximate
  analysis_cache_enabled: true
  churn_commit_window: 200
  coverage_data_file: ".coverage"
  hotspot_limit: 10
  hotspot_weights:
    deficit: 0.50
    churn: 0.30
    coverage_gap: 0.20
```

## Example 3: Layered Architecture Review

```yaml
architecture:
  enabled: true
  preset: layered
  layers: []
```

Notes:

- `architecture.enabled: false` is the default
- without opt-in, `boundary-violations` only reports import cycles
- the built-in `layered` preset allows `api -> domain` and blocks
  `domain -> data`

## Example 4: Domain-Aware Bootstrap Followed by Tuning

```bash
slop-detector --init
```

Then refine the generated file:

```yaml
domain: general

patterns:
  disabled:
    - todo_comment

  god_function:
    domain_overrides:
      - function_pattern: "train_*"
        complexity_threshold: 25
        lines_threshold: 180
```

## Example 5: Cleanup + Dependency Hygiene Review

```yaml
ignore:
  - "tests/**"
  - "node_modules/**"

advanced:
  coverage_data_file: ".coverage"
  churn_commit_window: 200

architecture:
  enabled: true
  preset: layered
```

This configuration works well with:

```bash
slop-detector sweep dead-code . --json
slop-detector sweep dupes . --json
slop-detector sweep unused-deps . --json
slop-detector sweep boundary-violations . --json
```

Expected cleanup semantics:

- cleanup findings may include `confidence`, `action_class`, and `evidence`
- `unused-deps` may emit:
  - `manifest_unused_dependency`
  - `undeclared_import`
- `boundary-violations` may emit:
  - `import_cycle`
  - `layer_boundary_violation`
