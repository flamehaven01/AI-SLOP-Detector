# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 3.12.x (latest release) | Yes |
| < 3.12 | No: upgrade to the latest release |

Fixes are released as a new patch version on PyPI (`ai-slop-detector`) and npm
(`ai-slop-detector`, the wrapper of the same version).

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Email **info@flamehaven.space** with the subject `[security] ai-slop-detector`
and include:

- the version (`slop-detector --version`) and how it was installed (pip, npx, Docker);
- the operating system and Python version;
- the steps or input that reproduce the problem, and what an attacker gains.

We aim to acknowledge a report within 7 days, agree on the impact with you, and
publish the fix and an advisory together. Tell us if you would like to be
credited.

## What the tool does with your code

Useful for judging the impact of a report:

- Analysis runs locally. The CLI makes no network request to analyze code; no
  API key and no model download are needed.
- The analyzed code is parsed, never imported or executed.
- No model file is read from the working directory and nothing is unpickled
  (since 3.9.0).
- `--read-only` writes nothing: no history, no analysis cache. MCP and REST
  scans are read-only by default, and the REST server binds `127.0.0.1`
  (since 3.11.0).
- The npm wrapper runs the Python CLI it finds (an explicit path, the active
  virtual environment, `PATH`, `python -m`) or, if none, the PyPI release of its
  own version through `uvx` or `pipx`. `AI_SLOP_DETECTOR_EXECUTABLE`, when
  set, names the program it runs: treat it like `PATH`.
- Telemetry is off by default; `slop-detector telemetry inspect --example`
  shows a payload before you enable it.

## Supply chain

- PyPI releases are published from GitHub Actions with trusted publishing
  (`.github/workflows/workflow.yml`).
- npm releases after 3.12.0 are published by the same workflow with npm trusted
  publishing and provenance. 3.12.0 was published from the maintainer account
  and carries no provenance.
