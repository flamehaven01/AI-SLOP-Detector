# CI/CD Integration Guide

Integrate AI-SLOP Detector into your CI/CD pipeline with progressive enforcement modes.

## Quick Start

```yaml
# .github/workflows/quality-gate.yml
name: Code Quality Gate

on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install AI-SLOP Detector
        run: pip install ai-slop-detector

      - name: Run Quality Gate
        run: slop-detector --project . --ci-mode hard --ci-report
```

## Enforcement Modes

### Soft Mode (Informational)

**Use Case:** Visibility, onboarding, gradual adoption

```bash
slop-detector --project . --ci-mode soft --ci-report
```

**Behavior:**
- ✅ Never fails build
- 📊 Posts PR comments with findings
- 📈 Tracks metrics
- 🔔 Notifies but doesn't block

**GitHub Actions:**
```yaml
- name: Quality Check (Soft)
  run: slop-detector --project . --ci-mode soft --ci-report
  continue-on-error: true
```

### Hard Mode (Strict)

**Use Case:** Production branches, release gates

```bash
slop-detector --project . --ci-mode hard --ci-report
```

**Behavior:**
- ❌ Fails build if thresholds exceeded
- 🚫 Blocks merge if quality issues
- 📊 Exit code 1 on failure
- 🎯 Enforces quality standards

**Fail Conditions:**
- Deficit score ≥ 70
- Critical patterns ≥ 3
- Inflation score ≥ 1.5
- Dependency usage < 50%

**GitHub Actions:**
```yaml
- name: Quality Gate (Hard)
  run: slop-detector --project . --ci-mode hard --ci-report
  # Build will fail if quality issues detected
```

### Quarantine Mode (Gradual)

**Use Case:** Gradual rollout, repeat offender tracking

```bash
slop-detector --project . --ci-mode quarantine --ci-report
```

**Behavior:**
- 📝 Tracks violations in `.slop_quarantine.json`
- ⚠️ Warns on first 2 violations
- ❌ Fails on 3rd violation (escalation)
- 🔄 Resets after fix

**Escalation Path:**
1. **1st violation:** Warning + tracked
2. **2nd violation:** Warning + tracked
3. **3rd violation:** Build fails

**GitHub Actions:**
```yaml
- name: Quality Gate (Quarantine)
  run: slop-detector --project . --ci-mode quarantine --ci-report

- name: Upload Quarantine DB
  uses: actions/upload-artifact@v3
  with:
    name: quarantine-db
    path: .slop_quarantine.json
```

## Claim-Based Enforcement (v2.6.2)

**Use Case:** Enforce integration test requirements for production claims

```bash
slop-detector --project . --ci-mode hard --ci-claims-strict --ci-report
```

**Behavior:**
- ❌ Fails if production/enterprise/scalable/fault-tolerant claims lack integration tests
- 🧪 Validates test evidence
- 📊 Reports test coverage breakdown

**GitHub Actions:**
```yaml
- name: Quality Gate (Claims Strict)
  run: |
    slop-detector --project . \
      --ci-mode hard \
      --ci-claims-strict \
      --ci-report
```

## Integration Examples

### GitHub Actions (Complete)

```yaml
name: Code Quality Pipeline

on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [main]

jobs:
  quality-gate:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: |
          pip install ai-slop-detector

      - name: Quality Analysis
        run: |
          slop-detector --project . \
            --ci-mode quarantine \
            --ci-claims-strict \
            --ci-report \
            --output quality-report.md

      - name: Upload Report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: quality-report
          path: quality-report.md

      - name: Comment PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v6
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('quality-report.md', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: report
            });
```

### GitLab CI

```yaml
# .gitlab-ci.yml
quality-gate:
  stage: test
  image: python:3.11
  script:
    - pip install ai-slop-detector
    - slop-detector --project . --ci-mode hard --ci-report
  artifacts:
    reports:
      junit: quality-report.xml
    paths:
      - quality-report.md
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: always
```

### CircleCI

```yaml
# .circleci/config.yml
version: 2.1

jobs:
  quality-gate:
    docker:
      - image: cimg/python:3.11
    steps:
      - checkout
      - run:
          name: Install AI-SLOP Detector
          command: pip install ai-slop-detector
      - run:
          name: Run Quality Gate
          command: |
            slop-detector --project . \
              --ci-mode hard \
              --ci-report \
              --output quality-report.md
      - store_artifacts:
          path: quality-report.md

workflows:
  quality-check:
    jobs:
      - quality-gate
```

### Jenkins

```groovy
// Jenkinsfile
pipeline {
    agent any

    stages {
        stage('Quality Gate') {
            steps {
                sh '''
                    pip install ai-slop-detector
                    slop-detector --project . \
                        --ci-mode quarantine \
                        --ci-report \
                        --output quality-report.md
                '''
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'quality-report.md'
        }
    }
}
```

## Configuration

### Custom Thresholds

Create `.slopconfig.yaml`:

```yaml
reporting:
  ci:
    fail_threshold: 50  # Fail if deficit >= 50
    fail_on_critical: true

thresholds:
  ldr:
    critical: 0.40
  inflation:
    critical: 0.8
  ddc:
    critical: 0.60
```

### Branch-Specific Rules

```yaml
# GitHub Actions with branch logic
- name: Quality Gate
  run: |
    if [ "${{ github.ref }}" == "refs/heads/main" ]; then
      slop-detector --project . --ci-mode hard --ci-report
    else
      slop-detector --project . --ci-mode soft --ci-report
    fi
```

## Monitoring & Reporting

### PR Comments

Soft/Quarantine modes automatically generate PR comments:

```markdown
## AI Code Quality Report

**Mode**: QUARANTINE

### Summary
- Analyzed: 47 files (42 clean, 5 with issues)
- Average Deficit Score: 23.4/100

### [CRITICAL] Failed Quality Checks
- `api/handler.py`: Exceeds critical thresholds
- `utils/processor.py`: Exceeds critical thresholds

### Recommendations
Run `slop-detector <file>` locally for detailed analysis.
```

### Artifacts

Store reports for historical analysis:

```yaml
- uses: actions/upload-artifact@v3
  with:
    name: quality-reports
    path: |
      quality-report.md
      .slop_quarantine.json
```

## Best Practices

### 1. Progressive Rollout

```
Week 1-2: Soft mode (visibility)
Week 3-4: Quarantine mode (tracking)
Week 5+:  Hard mode on main (enforcement)
```

### 2. Branch Strategy

```yaml
main:        Hard mode + Claims strict
develop:     Quarantine mode
feature/*:   Soft mode
```

### 3. Performance

```yaml
# Cache pip packages
- uses: actions/cache@v3
  with:
    path: ~/.cache/pip
    key: pip-${{ hashFiles('**/requirements.txt') }}
```

### 4. Notifications

```yaml
- name: Notify on Failure
  if: failure()
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    text: 'Quality gate failed'
```

## Troubleshooting

### Build Always Passing

Check if `--ci-report` flag is present and mode is not soft.

### False Positives

Use `.slopconfig.yaml` to disable specific patterns or adjust thresholds.

### Quarantine Not Escalating

Verify `.slop_quarantine.json` is persisted between runs (use artifacts).

## See Also

- [CLI Usage](CLI_USAGE.md) - Command-line reference
- [Configuration](CONFIGURATION.md) - Customize thresholds
- [Development](DEVELOPMENT.md) - Local testing
