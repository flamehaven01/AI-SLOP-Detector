# ai-slop-detector

Thin Node distribution for the `AI-SLOP-DETECTOR` Python CLI.

This package does **not** reimplement analysis logic in Node. It forwards all
arguments to the Python backend and preserves:

- command semantics
- stdout / stderr
- exit codes

## Install

```bash
npm install --save-dev ai-slop-detector
# or:
# pnpm add -D ai-slop-detector
# yarn add -D ai-slop-detector
# bun add -d ai-slop-detector
```

## Python Backend Requirement

The npm wrapper needs a Python backend to execute.

Supported backend discovery order:

1. `AI_SLOP_DETECTOR_EXECUTABLE`
2. active `VIRTUAL_ENV` scripts
3. `ai-slop-detector` / `slop-detector` on `PATH`
4. `python -m slop_detector.cli`
5. `python3 -m slop_detector.cli`
6. `py -m slop_detector.cli` on Windows

Recommended Python install:

```bash
pip install ai-slop-detector
```

## Usage

```bash
npx ai-slop-detector scan .
npx ai-slop-detector review . --format json
npx ai-slop-detector pulse . --format json
npx ai-slop-detector sweep dead-code . --format json
npx ai-slop-detector mcp
```

## Typed Output Contract

The wrapper also ships version-pinned TypeScript interfaces for the structured
CLI outputs:

```ts
import type { ScanOutput, ReviewOutput, HealthOutput, SweepOutput } from "ai-slop-detector/types";
```

These types mirror the current JSON contracts for:

- `scan`
- `review`
- `pulse`
- `sweep`
- `explain`

## Notes

- `--format json` and `--json` are equivalent structured-output surfaces.
- The wrapper is intentionally thin so Node-first teams can adopt the CLI
  without changing product semantics.
