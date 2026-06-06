### Patch the findings

Most structural findings have a concrete, safe remedy. The extension surfaces
fixes where they are unambiguous and leaves judgment calls to you.

- **Auto-Fix Detected Issues** applies (or previews) the safe patterns:
  mutable-default arguments, bare excepts, and similar mechanical fixes.
- **QuickFix lightbulb** on `phantom_import`, `god_function`, and `lint_escape`
  diagnostics offers targeted actions, including adding an entry to
  `.slopconfig.yaml`.

[Auto-Fix](command:slop-detector.autoFix)

Review-first: cleanup advice carries a confidence and an evidence trail. Read the
evidence before removing anything flagged `needs` or `unsafe`.
