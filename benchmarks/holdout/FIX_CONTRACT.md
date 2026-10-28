# Fix contract from hold-out v1 (fixed before implementation)

Scope: the four changes below and nothing else. Each is motivated by v1
evidence only (`benchmarks/holdout/labels.json`, scored at c98702b). Defects
first seen in hold-out v2 are out of scope here, in particular the
`print` + `raise NotImplementedError` stubs and the placeholder-family false
alarms on base-class hooks and null objects; a change made for them would make
v2 development data.

Fixtures are written from the v1 shapes, not copied from the third-party
source. v2 is re-scored exactly once, after all four are in.

## 1. Constant success report

v1 evidence: H124, H147, H160 (`return Report(<literal>, True, f"... {arg}")`),
H162 (`return ComponentHealth(status=HealthStatus.HEALTHY, message="...")`).

Rule: the body, past a docstring and cosmetic statements, is one `return` of a
call whose every argument is a literal, an f-string or an enum-style attribute,
and one argument marks success (`True`, or an attribute named HEALTHY, OK,
SUCCESS, SUCCEEDED, PASSED, READY, CONNECTED). Parameters may appear only
inside f-strings. The finding names the call and the success argument; a
literal containing placeholder/simulated/stub is quoted as extra evidence.
Declared intent (contract, override of a module base, accessor, registered
callback) exempts it, as for the other stub patterns.

## 2. Swallowed failure, then a placeholder value

v1 evidence: H149 (`try: ... return measured` / `except Exception: pass` /
`return <constant expression>  # placeholder`).

Rule: a `try` whose body returns, and a handler that neither returns nor
raises (pass, continue, logging), followed by a final `return` of a constant
expression that is not a neutral value. Neutral, per the v1 label rules, is
None, False, 0, 0.0, an empty string or an empty container. The finding names
the handler line and the value returned in its place.

## 3. Documented parameter never read

v1 evidence: H123 (`namespace` described in the docstring, read only in a
comment).

Rule: `ignored_parameter` also covers parameters without a default when the
docstring documents the parameter (an argument entry: `name: ...` or
`name (type): ...` or `name : type`) and the body never reads it. Such an entry
is the function's own promise about that argument, so it also overrides the
outside-base exemption (H123 is `forward` of an `nn.Module`); the other
exemptions apply (self/cls, underscore names, documented as kept or unused,
stub bodies, contracts, overrides of a module base, callbacks, decorators).

Amendment after the first implementation pass (v1 evidence only): H123 was
still exempt through the sibling-signature rule (three other methods of its
class take `(self, namespace)`). The same reasoning holds there, so a
docstring entry overrides the sibling-signature exemption too.

## 4. Two false alarms

v1 evidence: H119 (FastAPI `Depends(...)` parameters reported as ignored) and
H017 (`def __init__(self): pass` reported as a placeholder).

Rule: `ignored_parameter` skips a parameter whose default is a call to
`Depends` or `Security`; `pass_placeholder` skips an `__init__` whose body is
only `pass` (and a docstring).

## Amendment 2: narrowed on the development replay (14 repositories)

The first full implementation added 80 replay findings; reading them showed
three over-broad rules, narrowed before hold-out v2 is touched again:

- 1: `_NON_DISPATCHER_OWNED_CONTEXT.set(True)` is a method acting, not a
  report. The call must construct a class (callee name starts upper-case).
- 2: 36 of 37 were settings resolvers answering a failed lookup with a chosen
  default (`return "us-east-1"`, `return True`). The fallback is reported only
  when a comment between the `try` and the `return` calls it invented
  (placeholder, unreliable, dummy, fake, made up, arbitrary), as H149's does.
- 3: framework hooks document arguments the framework fixes (Lightning
  `training_step(batch, batch_idx)`), and MCP tools take `Annotated[...]`
  arguments such as `call_benefit` by design. The outside-base exemption stays;
  in a sibling family a documented argument is reported only when a sibling
  reads it (H123's siblings read `namespace`); `Annotated` arguments are not
  covered by the documented-argument rule.

## Acceptance

- A failing control for each item before the change, passing after; each
  control falsified by mutating the change back.
- `benchmarks/recall`: no genuine function newly flagged.
- Hold-out v1 (development data now): the evidence functions above flagged,
  H017 and H119 no longer flagged.
- External replay (14 repositories): every added finding read in source.
- Then hold-out v2 re-scored once, with the new pattern ids in `ADDED_PATTERNS`
  and the eight-pattern score kept for comparison. Because v2's baseline was
  seen before this contract, that score shows whether pre-declared changes
  carry over; the fully independent measurement is a new v3.
