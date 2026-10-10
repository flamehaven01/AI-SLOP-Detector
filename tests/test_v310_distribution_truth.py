"""v3.10 distribution truthfulness: a release job says what it published.

Found in the v3.9.2/v3.9.3 releases: the Docker job reported success while
nothing was pushed (no registry login, `push: false`), and the npm wrapper,
never published, carried no guard against an accidental `npm publish`.

Contract:
- the Docker job ends with a step that states PUBLISHED or BUILT_NOT_PUBLISHED
  from the push decision, in the job summary;
- the npm wrapper is private (it is shipped in the repository, not on npm).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def _docker_steps():
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    return workflow["jobs"]["docker"]["steps"]


def test_docker_job_states_its_publish_outcome():
    steps = _docker_steps()
    build = next(
        step for step in steps if step.get("uses", "").startswith("docker/build-push-action")
    )
    last = steps[-1]
    assert last is not build
    script = last.get("run", "")
    assert "BUILT_NOT_PUBLISHED" in script and "PUBLISHED" in script
    assert "GITHUB_STEP_SUMMARY" in script
    # The outcome comes from the same decision the build step used.
    assert build["with"]["push"].strip("${} ") in last.get("env", {}).get("PUSHED", "")


def test_npm_wrapper_is_private():
    package = json.loads((REPO / "npm-wrapper" / "package.json").read_text(encoding="utf-8"))
    assert package.get("private") is True
