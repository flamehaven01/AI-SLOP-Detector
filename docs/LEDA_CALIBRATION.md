# Legacy LEDA Calibration Notes

**Status:** archived maintainer notes, not a supported product workflow
**Last reviewed:** 2026-08-22

Earlier revisions described multi-repository dogfooding, global weight
injection, and automation scripts under the LEDA name. Those materials are not
the current user-facing calibration model and must not be read as evidence of
external validation, team consensus, or a production governance control.

The supported behavior is documented in [SELF_CALIBRATION.md](SELF_CALIBRATION.md):

- calibration is repository-scoped and local
- it is an operational review-sensitivity aid, not ground truth
- it does not export repository history as a validation channel
- it does not establish generalization outside the local calibration loop

Legacy scripts may remain in the repository for maintainers investigating past
work, but they are not an approved collection, automatic-fix, or global-config
workflow. Do not run them against another repository without explicit owner
authorization.

For the current claim boundary, see [VALIDATION.md](VALIDATION.md).
