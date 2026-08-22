# REST API Reference

**Version:** 3.8.9
**Last reviewed:** 2026-08-22

The optional FastAPI surface is a local integration layer over the Python core.
It is useful when a trusted local service needs structured file or project
analysis. The CLI, MCP server, and npm wrapper remain the preferred interfaces
for most users and agents.

## Security Boundary

This server is not a hardened public or multi-tenant deployment surface:

- authentication and request authorization are not built in
- the default CORS middleware permits all origins
- webhook and project-status routes are not documented as supported

Do not expose it directly to an untrusted network. Put authentication,
authorization, network policy, and request limits in front of any deployment.

## Install and Run

```bash
pip install "ai-slop-detector[api]"
slop-api
```

`slop-api` starts the local server on `0.0.0.0:8000`. To choose host, port, or
a configuration path, call the Python entry point explicitly:

```python
from pathlib import Path

from slop_detector.api.server import run_server

run_server(host="127.0.0.1", port=8000, config_path=Path(".slopconfig.yaml"))
```

The running instance publishes its generated OpenAPI contract at `/docs` and
`/redoc`; treat those pages as the exact request/response schema for the
installed version.

## Supported Local Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Service name, version, and discovery links |
| `GET` | `/health` | Basic process liveness |
| `GET` | `/agent/schema` | Agent surface manifest |
| `POST` | `/agent/file` | Structured single-file snapshot |
| `POST` | `/agent/project` | Structured project snapshot |
| `POST` | `/analyze/file` | Compatibility single-file response |
| `POST` | `/analyze/project` | Compatibility project response |
| `GET` | `/history/file/{file_path}` | Local history for one file |
| `GET` | `/trends/project` | Local history trend summary |

`/agent/*` is the preferred API path for new integrations. The older
`/analyze/*` routes remain for compatibility.

## Request Examples

```bash
curl http://127.0.0.1:8000/agent/schema

curl -X POST http://127.0.0.1:8000/agent/file \
  -H "Content-Type: application/json" \
  -d '{"file_path":"/absolute/path/to/module.py","save_history":false}'

curl -X POST http://127.0.0.1:8000/agent/project \
  -H "Content-Type: application/json" \
  -d '{"project_path":"/absolute/path/to/project","save_history":false}'
```

Agent responses contain a summary, signals, analysis details, and generated
timestamp. Project responses also include file results, language-specific
results, priority hotspots, and the suppression ledger.

## Validation

The agent surface is covered by `tests/test_api_agent_surface.py` when the API
extra is installed. API availability does not add external validation to the
structural score; see [VALIDATION.md](VALIDATION.md) for that boundary.
