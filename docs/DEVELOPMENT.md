# Development Guide

Guide for contributing to AI-SLOP Detector.

## Quick Setup

```bash
# Clone repository
git clone https://github.com/flamehaven01/AI-SLOP-Detector.git
cd AI-SLOP-Detector

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"

# Verify installation
slop-detector --help
```

## Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/amazing-feature
```

### 2. Make Changes

Edit code in `src/slop_detector/`

### 3. Run Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src/slop_detector --cov-report=html

# Specific test file
pytest tests/test_core.py -v

# Watch mode (requires pytest-watch)
ptw tests/ -- -v
```

### 4. Check Code Quality

```bash
# Linting
ruff check src/ tests/

# Formatting
black src/ tests/

# Type checking (if using mypy)
mypy src/slop_detector
```

### 5. Commit Changes

```bash
git add .
git commit -m "feat: Add amazing feature"
```

**Commit Convention:**
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `test:` Tests
- `chore:` Maintenance

### 6. Push and Create PR

```bash
git push origin feature/amazing-feature
# Open PR on GitHub
```

## Project Structure

```
AI-SLOP-Detector/
├── src/slop_detector/
│   ├── __init__.py
│   ├── core.py              # Main detector logic
│   ├── models.py            # Data models
│   ├── config.py            # Configuration
│   ├── cli.py               # CLI interface
│   ├── question_generator.py # Review questions
│   ├── ci_gate.py           # CI/CD enforcement
│   ├── metrics/             # Analysis metrics
│   │   ├── ldr.py          # Logic Density Ratio
│   │   ├── inflation.py    # Jargon detection
│   │   ├── ddc.py          # Dependency check
│   │   ├── context_jargon.py # Evidence validation
│   │   ├── docstring_inflation.py
│   │   └── hallucination_deps.py
│   ├── patterns/            # Pattern detection
│   │   ├── base.py
│   │   ├── placeholder.py
│   │   ├── structural.py
│   │   └── cross_language.py
│   └── auth/                # Enterprise features
├── tests/                   # Test suite
│   ├── test_core.py
│   ├── test_metrics.py
│   ├── test_patterns.py
│   └── test_ci_gate.py
├── docs/                    # Documentation
├── pyproject.toml          # Project metadata
├── .slopconfig.example.yaml # Config template
└── README.md
```

## Testing

### Running Tests

```bash
# All tests with coverage
pytest tests/ -v --cov=src/slop_detector --cov-report=html

# Open coverage report
open htmlcov/index.html  # On macOS
# Or: start htmlcov/index.html  # On Windows
```

### Writing Tests

```python
# tests/test_my_feature.py
import pytest
from slop_detector.core import SlopDetector

def test_my_feature():
    """Test my amazing feature."""
    detector = SlopDetector()
    result = detector.analyze_file("test_file.py")
    assert result.deficit_score < 30
```

### Test Coverage Requirements

- **Minimum:** 80% overall coverage
- **Target:** 85%+ overall coverage
- **New code:** 90%+ coverage

## Code Style

### Formatting

```bash
# Format code
black src/ tests/

# Check formatting
black --check src/ tests/
```

### Linting

```bash
# Lint code
ruff check src/ tests/

# Fix auto-fixable issues
ruff check --fix src/ tests/
```

### Style Guide

- Follow PEP 8
- Use type hints
- Write docstrings for public APIs
- Keep functions focused (single responsibility)
- Prefer explicit over implicit

## Adding New Features

### 1. Evidence Type

To add a new evidence type (e.g., "caching"):

1. Update `src/slop_detector/metrics/context_jargon.py`:
   ```python
   def _has_caching(self, content: str) -> bool:
       return any(keyword in content for keyword in
                  ["@cache", "redis", "memcache"])
   ```

2. Add to `EVIDENCE_REQUIREMENTS`:
   ```python
   EVIDENCE_REQUIREMENTS = {
       "performance": ["caching", "async_support"],
       # ...
   }
   ```

3. Add tests in `tests/test_context_jargon.py`

### 2. Pattern Detector

To add a new pattern:

1. Create pattern in `src/slop_detector/patterns/`:
   ```python
   class MyPattern(PatternDetector):
       def detect(self, tree: ast.AST) -> List[Issue]:
           # Implementation
   ```

2. Register in `src/slop_detector/patterns/registry.py`

3. Add tests in `tests/test_patterns.py`

### 3. Metric

To add a new metric:

1. Create metric in `src/slop_detector/metrics/my_metric.py`
2. Update `FileAnalysis` model in `models.py`
3. Integrate in `core.py`
4. Add tests in `tests/test_my_metric.py`

## Documentation

### Updating Documentation

```bash
# Documentation files
docs/
├── CONFIGURATION.md  # Configuration guide
├── CLI_USAGE.md      # CLI reference
├── CI_CD.md          # CI/CD integration
└── DEVELOPMENT.md    # This file

# Update README.md for major features
```

### Documentation Style

- Clear, concise language
- Code examples for all features
- Link to related docs
- Keep examples up-to-date

## Release Process

### 1. Version Update

Update version in:
- `pyproject.toml`
- `src/slop_detector/__init__.py`
- `src/slop_detector/auth/__init__.py`

### 2. Update CHANGELOG

Add entry to `CHANGELOG.md`:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New feature

### Changed
- Updated behavior

### Fixed
- Bug fix
```

### 3. Create Tag

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

### 4. Build and Upload

```bash
# Build package
python -m build

# Upload to PyPI
twine upload dist/*
```

## Contribution Guidelines

### Code Review Checklist

- [ ] Tests added/updated
- [ ] Coverage ≥ 80%
- [ ] Black formatted
- [ ] Ruff clean
- [ ] Documentation updated
- [ ] CHANGELOG updated
- [ ] No breaking changes (or documented)

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement

## Testing
Describe testing performed

## Checklist
- [ ] Tests pass
- [ ] Coverage maintained
- [ ] Docs updated
```

## Getting Help

- **Issues:** [GitHub Issues](https://github.com/flamehaven01/AI-SLOP-Detector/issues)
- **Discussions:** [GitHub Discussions](https://github.com/flamehaven01/AI-SLOP-Detector/discussions)
- **Email:** info@flamehaven.space

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## See Also

- [CLI Usage](CLI_USAGE.md) - Command-line reference
- [Configuration](CONFIGURATION.md) - Customize settings
- [CI/CD Integration](CI_CD.md) - Automated testing
