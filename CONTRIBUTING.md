# Contributing to AI SLOP Detector

Thank you for your interest in contributing!

## Development Setup

```bash
# Clone repository
git clone https://github.com/flamehaven/ai-slop-detector
cd ai-slop-detector

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linters
make lint
```

## Code Standards

- **Python**: 3.8+ compatibility required
- **Formatting**: Black with 100 char line length
- **Linting**: Ruff for imports and style
- **Type hints**: Required for public APIs
- **Tests**: pytest with >80% coverage

## Pull Request Process

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Make changes with tests
4. Run tests and linters (`make test lint`)
5. Commit with descriptive message
6. Push to branch
7. Open Pull Request

## Priority Areas

### High Priority
- [ ] JavaScript/TypeScript support
- [ ] Better complexity metrics
- [ ] ML-based detection

### Medium Priority
- [ ] IDE plugins (VS Code, PyCharm)
- [ ] Historical trend analysis
- [ ] Auto-fix suggestions

### Low Priority
- [ ] Java/Go support
- [ ] Web dashboard
- [ ] Slack/Discord integration

## Questions?

Open an issue or email: slop-detector@flamehaven.io
