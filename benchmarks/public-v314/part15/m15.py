"""Part 15 measurements against the ai-slop-detector 3.14.2 wheel.

Run with the Python of a venv that has ai-slop-detector==3.14.2 installed:

    python -I m15.py --demo <demo_project> --repo <repo_tree> --out <empty dir>

--demo  examples/demo_project taken from tag v3.14.2 (git archive)
--repo  the whole repository tree at tag v3.14.2 (git archive)
--out   where m15_results.json is written. Scratch work happens in a new
        directory created inside --out with tempfile.mkdtemp; the script
        deletes only that directory, and only after checking that it is a
        real directory (not a symbolic link or junction) inside --out. It
        never edits --demo or --repo (it edits copies) and never reuses or
        deletes a directory it did not create in this run.

Measures:
  1. output surfaces of the demo project, from three CLI invocations on the
     same fixed input: the default terminal summary; `--report-dir`, which
     writes report.md, report.html, report.pdf, ai-report.jsonl, ai-report.md
     and scan.json from one analysis; and the agent work order. Each
     invocation runs its own analysis of identical bytes;
  2. the VOID binding: the work order rendered again from the same scan
     result after one file changed;
  3. prove_state under five edits;
  4. the work-order tiers per token budget.
Tokens are estimated as characters / 4 (the detector's own estimate), not a
tokenizer count.
"""

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import slop_detector
from slop_detector.ai_report import AiReportInvalidError, prove_state, render_ai_report
from slop_detector.ai_report_md import estimate_tokens, render_ai_report_md
from slop_detector.core import SlopDetector

CLI = Path(sys.executable).parent / ("slop-detector.exe" if os.name == "nt" else "slop-detector")
PRICING = "orders/pricing.py"
BUDGETS = [1000, 2000, 3000, 4000, 6000, 8000, 12000, 16000, 24000, 32000, 48000, 64000,
           96000, 128000]


def is_link(path: Path) -> bool:
    """A symbolic link, or on Windows a directory junction."""
    is_junction = getattr(path, "is_junction", None)  # Python 3.12+
    return path.is_symlink() or bool(is_junction and is_junction())


class Work:
    """Scratch directories created by this run, never reused, never followed.

    Every directory comes from tempfile.mkdtemp, so it is new and empty; a
    directory left by an earlier run, or a link planted under --out, is never
    opened or deleted. close() removes only the root this run created."""

    def __init__(self, out: Path):
        if is_link(out):
            raise SystemExit(f"refusing --out {out}: it is a link or junction")
        self.out = out.resolve()
        self.root = Path(tempfile.mkdtemp(prefix="m15_work_", dir=self.out))

    def fresh(self, name: str, source: Path, rel: str = "") -> Path:
        """A new directory holding a copy of `source` at `rel` (or at its
        own name). copytree copies the content of linked files, not the
        links, so an edit to the copy cannot reach outside it."""
        base = Path(tempfile.mkdtemp(prefix=f"{name}_", dir=self.root))
        dest = base / (rel or source.name)
        shutil.copytree(source, dest)
        return dest

    def close(self) -> None:
        remove_owned(self.root, self.out)


def remove_owned(path: Path, owner: Path) -> None:
    """Delete `path` only if it is a real directory strictly inside `owner`."""
    if is_link(path):
        raise SystemExit(f"refusing to delete {path}: it is a link or junction")
    real = path.resolve()
    if owner.resolve() not in real.parents:
        raise SystemExit(f"refusing to delete {real}: not inside {owner}")
    shutil.rmtree(real)


def scan(path, config=None):
    # read_only: no history or cache is written, so the inputs stay untouched
    return SlopDetector(config_path=config, read_only=True).analyze_project(str(path))


def records(result):
    return [json.loads(line) for line in render_ai_report(result).splitlines() if line.strip()]


def size(text):
    return {"bytes": len(text.encode("utf-8")), "lines": text.count("\n") + 1,
            "est_tokens": estimate_tokens(text)}


def run(*args, cwd):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([str(CLI), *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", env=env)


def surfaces(work: Work, demo: Path, out: dict):
    """The demo project rendered for every reader: three CLI invocations on
    the same fixed input, each with its own analysis (see the module text)."""
    project = "examples/demo_project"
    base = work.fresh("surfaces", demo, project).parent.parent
    invocations = [
        ["--project", project],
        ["--project", project, "--report-dir", "bundle"],
        ["--project", project, "--format", "ai-md", "--ai-mode", "agent", "-o", "ai-work.md"],
    ]
    term, bundle, agent = (run(*args, cwd=base) for args in invocations)
    rows = {"terminal (default)": size(term.stdout)}
    for f in sorted((base / "bundle").iterdir()):
        rows[f.name] = ({"bytes": f.stat().st_size} if f.suffix == ".pdf"
                        else size(f.read_text(encoding="utf-8")))
    rows["ai-work.md (agent)"] = size((base / "ai-work.md").read_text(encoding="utf-8"))
    out["surfaces"] = {"invocations": [" ".join(["slop-detector", *a]) for a in invocations],
                       "analyses": len(invocations),
                       "exit": [term.returncode, bundle.returncode, agent.returncode],
                       "bundle_stderr_tail": bundle.stderr.strip()[-400:], "rows": rows}
    out["terminal_demo"] = term.stdout


def void_hold(work: Work, demo: Path, out: dict):
    """Render the work order again from the same scan after one file changed."""
    copy = work.fresh("void", demo)
    result = scan(copy)
    before = render_ai_report_md(result)
    target = copy / PRICING
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited after the scan\n",
                      encoding="utf-8")
    after = render_ai_report_md(result)
    blocks = after.split("\n### W")
    out["void"] = {
        "items": len(records(result)) - 1,
        "void_before": before.count("(VOID:"),
        "void_after": after.count("(VOID:"),
        "void_block": next(("### W" + b for b in blocks if "(VOID:" in b), "")[:1500],
    }


def symbol_present(path, name):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
               for n in ast.walk(tree))


def prove(work: Work, demo: Path, out: dict):
    """prove_state for one item of orders/pricing.py after each of five edits."""
    before = records(scan(demo))[1:]
    pick = lambda rule: next(r for r in before if r["rule"] == rule and r["file"] == PRICING)
    stub, todo = pick("return_constant_stub"), pick("todo_comment")
    src = (demo / PRICING).read_text(encoding="utf-8")
    edits = {
        "unrelated: 3 comment lines added at the top": ("# a\n# b\n# c\n" + src, None),
        "real fix: compute_discount reads the order": (src.replace(
            "    # TODO: use the customer's tier\n    return 0.1",
            "    # TODO: use the customer's tier\n    return order.get(\"discount_rate\", 0.0)"),
            stub),
        "reworded: the TODO says the same thing differently": (src.replace(
            "# TODO: use the customer's tier",
            "# TODO: take the tier of the customer into account"), todo),
        "deleted: compute_discount removed": (re.sub(
            r"def compute_discount\(order\):\n(?:    .*\n)+\n\n", "", src), stub),
        "only the TODO comment deleted": (src.replace(
            "    # TODO: use the customer's tier\n", ""), todo),
    }
    rows = []
    for name, (text, item) in edits.items():
        if text == src:
            raise SystemExit(f"edit did not apply: {name}")
        copy = work.fresh("prove", demo)
        (copy / PRICING).write_text(text, encoding="utf-8")
        after = records(scan(copy))[1:]
        after_ids = {a["id"] for a in after}
        if item is None:
            kept = [r for r in before if r["file"] == PRICING]
            rows.append({"edit": name, "pricing_items": len(kept),
                         "ids_kept": sum(r["id"] in after_ids for r in kept),
                         "states": sorted({prove_state(before, after, r["id"], True)
                                           for r in kept})})
            continue
        present = symbol_present(copy / PRICING, item["symbol"]) if item.get("symbol") else True
        rows.append({"edit": name, "item": f"{item['id']} {item['rule']}",
                     "symbol_present": present,
                     "state": prove_state(before, after, item["id"], present),
                     "other_pricing_items_still_present": {
                         f"{r['id']} {r['rule']}": r["id"] in after_ids
                         for r in before if r["file"] == PRICING and r["id"] != item["id"]}})
    out["prove"] = {"items_before": len(before), "rows": rows}


def budget(repo: Path, out: dict):
    """Tiers per token budget on the repository source (read only)."""
    config = repo / ".slopconfig.yaml"
    result = scan(repo, str(config) if config.exists() else None)
    head = records(result)[0]
    rows = []
    for b in BUDGETS:
        try:
            doc = render_ai_report_md(result, token_budget=b)
        except AiReportInvalidError as exc:
            rows.append({"budget": b, "refused": str(exc)})
            continue
        m = re.search(r"tiers T1 (\d+), T2 (\d+), T3 (\d+)", doc)
        rows.append({"budget": b, "est_tokens": estimate_tokens(doc),
                     "T1": int(m.group(1)), "T2": int(m.group(2)), "T3": int(m.group(3))})
    out["budget"] = {"target": "repository source at tag v3.14.2 with its own .slopconfig.yaml",
                     "files": head["files"], "items": head["findings"] + head["candidates"],
                     "unbudgeted": size(render_ai_report_md(result)), "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", required=True, type=Path)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    if is_link(a.out):  # checked before resolve(), which would follow the link
        raise SystemExit(f"refusing --out {a.out}: it is a link or junction")
    demo, repo, outdir = a.demo.resolve(), a.repo.resolve(), a.out.resolve()
    for p in (demo, repo):
        if outdir == p or outdir in p.parents or p in outdir.parents:
            raise SystemExit("--out must not overlap --demo or --repo")
    outdir.mkdir(parents=True, exist_ok=True)
    work = Work(outdir)
    out = {"tool_version": slop_detector.__version__, "python": sys.version.split()[0]}
    try:
        surfaces(work, demo, out)
        void_hold(work, demo, out)
        prove(work, demo, out)
        budget(repo, out)
    finally:
        work.close()
    # LF on every OS: the manifest digests the file as the repository stores it
    with open(outdir / "m15_results.json", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "terminal_demo"}, indent=1)[:4000])


if __name__ == "__main__":
    main()
