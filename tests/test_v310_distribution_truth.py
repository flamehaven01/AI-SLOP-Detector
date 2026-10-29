"""v3.10 distribution truthfulness: a release job says what it published.

Found in the v3.9.2/v3.9.3 releases: the Docker job reported success while
nothing was pushed (no registry login, `push: false`), and the npm wrapper,
never published, carried no guard against an accidental `npm publish`.

Contract:
- the Docker job ends with a step that states PUBLISHED or BUILT_NOT_PUBLISHED
  from the push decision, in the job summary;
- the npm wrapper is published with the same version as the Python package
  (its uvx / pipx fallback runs the PyPI release of that version) and ships
  only its runtime files.
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


def test_npm_wrapper_version_matches_python_package():
    package = json.loads((REPO / "npm-wrapper" / "package.json").read_text(encoding="utf-8"))
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    version = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in pyproject.splitlines()
        if line.startswith("version")
    )
    assert package["version"] == version
    assert package.get("private") is not True
    assert sorted(package["files"]) == ["README.md", "bin", "lib", "types.d.ts"]


def test_npm_release_follows_pypi_with_provenance():
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "workflow.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["npm-publish"]
    assert job["needs"] == "pypi-publish"
    assert job["permissions"]["id-token"] == "write"
    runs = [step.get("run", "") for step in job["steps"]]
    assert any("GITHUB_REF_NAME" in run and "package.json" in run for run in runs)
    assert any(run.startswith("npm publish") and "--provenance" in run for run in runs)
