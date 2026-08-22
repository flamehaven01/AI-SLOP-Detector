# Legacy LEDA Turbo Protocol Record

**Status:** archived historical record, not a supported workflow
**Last reviewed:** 2026-08-22

This document formerly described a scan/fix/rescan procedure across external
repositories. It is retained only to explain references in repository history.
It is not a current product feature, a source of external validation, or a
recommended agent workflow.

Current users should use the bounded local workflow instead:

```bash
slop-detector review . --format json
slop-detector pulse . --format json
slop-detector sweep dead-code . --format json
```

Apply changes only with repository-owner authorization and rerun the same
surface for evidence. See [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) and
[SELF_CALIBRATION.md](SELF_CALIBRATION.md) for supported behavior.
