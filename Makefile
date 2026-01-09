# Makefile for AI SLOP Detector

.PHONY: help install dev test lint format clean docker

help:
	@echo "AI SLOP Detector - Development Commands"
	@echo ""
	@echo "  install     Install package"
	@echo "  dev         Install with dev dependencies"
	@echo "  test        Run tests"
	@echo "  lint        Run linters"
	@echo "  format      Format code"
	@echo "  clean       Clean build artifacts"
	@echo "  docker      Build Docker image"

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest --cov --cov-report=term-missing --cov-report=html

lint:
	ruff check src/ tests/
	mypy src/

format:
	black src/ tests/
	ruff check --fix src/ tests/

clean:
	rm -rf build/ dist/ *.egg-info/
	rm -rf .pytest_cache/ htmlcov/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

docker:
	docker build -t flamehaven/ai-slop-detector:2.0.0 .
	docker tag flamehaven/ai-slop-detector:2.0.0 flamehaven/ai-slop-detector:latest
