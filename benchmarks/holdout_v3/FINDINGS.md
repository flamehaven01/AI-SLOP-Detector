# Hold-out v3 findings

The independent measurement of the frozen detector, by [PROTOCOL.md](PROTOCOL.md).
Scored once, on 2026-10-31.

- Detector: commit `13f08e3` (version string 3.12.0 plus the unreleased fixes
  on main), source digest `87a9c63b...`. The scorer refuses any other source.
- Scored patterns: v1's eight; the frozen version adds no hollow pattern id,
  so the eight-pattern score is the score.
- Labels: fixed and committed (`76f50ea`) before the detector ran on any v3
  repository. The labeler is the rule author, so the labels are blind to the
  detector output but not independent of the rules.
- Measurement: 47 of 47 repositories COMPLETE, 0 functions excluded; both
  tiers are valid.
- Evidence binding: [receipt.json](receipt.json). Full rows: [results.json](results.json).

## Sample

| Tier | Repositories | Functions | R (random) | S (short) | Hollow |
|---|---|---|---|---|---|
| A+B | 16 | 375 | 128 | 247 | 1 |
| AI_ASSOCIATED | 31 | 744 | 248 | 496 | 3 |

AI_ASSOCIATED repositories carry an AI instruction file or AI co-author
trailers in their last 100 commits (PROTOCOL.md section 2). The 16 primaries
gave 2 hollow functions, under the 30 the protocol aimed for, so the 15
reserves were drawn and labeled in walk order, before any scan. 32 of the 70
repositories walked for AI_ASSOCIATED carried a signal.

Hollow functions are rare here: 4 of 1119 (0.4%). Recall therefore rests on 4
functions and says little. The false-alarm rate is the main reading.

## False alarms (genuine functions flagged)

Read the R stratum first. S takes 16 short functions per repository against
R's 8, so short functions are over-represented and a tier total describes
this sample design, not all Python functions.

| Group | Flagged | Wilson 95% | Repository bootstrap 95% |
|---|---|---|---|
| A+B / R | 4 / 128 (3.1%) | 1.2% - 7.8% | 0.0% - 7.0% |
| A+B / S | 5 / 246 (2.0%) | 0.9% - 4.7% | 0.8% - 3.7% |
| A+B (sample total) | 9 / 374 (2.4%) | 1.3% - 4.5% | 1.0% - 4.1% |
| AI_ASSOCIATED / R | 4 / 248 (1.6%) | 0.6% - 4.1% | 0.4% - 3.2% |
| AI_ASSOCIATED / S | 6 / 493 (1.2%) | 0.6% - 2.6% | 0.4% - 2.2% |
| AI_ASSOCIATED (sample total) | 10 / 741 (1.3%) | 0.7% - 2.5% | 0.7% - 2.0% |
| AI / instruction file | 3 / 407 | 0.3% - 2.1% | |
| AI / co-author trailer | 8 / 598 | 0.7% - 2.6% | |

## Recall (hollow functions flagged)

| Group | Flagged | Wilson 95% | Note |
|---|---|---|---|
| A+B | 0 / 1 | 0% - 79% | bootstrap not informative |
| AI_ASSOCIATED | 3 / 3 | 44% - 100% | bootstrap not informative |

All 4 hollow labels carry STATIC evidence; there is no SEMANTIC positive.

## Per pattern

| Pattern | True flags | False flags |
|---|---|---|
| `ignored_parameter` | 1 | 9 |
| `return_constant_stub` | 0 | 7 |
| `pass_placeholder` | 2 | 2 |
| `return_none_placeholder` | 0 | 2 |
| `not_implemented` | 0 | 1 |
| `ellipsis_placeholder`, `failure_as_success`, `return_input_stub` | 0 | 0 |

A function can carry two flags, so the false flags (21) exceed the flagged
genuine functions (19).

## Hollow functions

| ID | Function | Label | Result |
|---|---|---|---|
| T534 | `Luo-Yihao/FaithC` `normalize_mesh_max_fill` | PLACEHOLDER_PLAIN | caught, `pass_placeholder` |
| T577 | `howyoungchen/deepRolePlay` `LoggingUtils.log_response` | PLACEHOLDER_PLAIN | caught, `pass_placeholder` |
| T1114 | `lack-jpg/gov_AP` `BehaviorAnalyzer._detect_loop` | IGNORED_INPUT | caught, `ignored_parameter` |
| T114 | `Alibaba-NLP/ZeroSearch` `CriticWorker.load_checkpoint` | PLACEHOLDER_PLAIN | **missed** |

**T114 missed.** `verl/workers/megatron_workers.py:575-577`: a bare `pass`
under `@register(dispatch_mode=Dispatch.ONE_TO_ALL)`. `is_declared_body`
(`patterns/declared_intent.py`) accepts an empty body under any decorator that
is not an accessor or a signature marker (`has_implementing_decorator`), so a
registering decorator alone declares it. Fix direction: a registering
decorator should exempt `...` (the decorator supplies the body), not `pass`;
an empty registered method should need the same declaration `_declared_noop`
asks for.

## Flagged genuine functions and fix direction

**A parameter fixed by a shared signature (`ignored_parameter`, 7):**

- T148, T151 `nv-tlabs/3dgrut` `Tracer.render(..., train=False, ...)`: two
  sibling tracers share the signature.
- T217, T229 `mahm/dspy-demo` metrics `(gold, pred, trace=None)`: the DSPy
  metric signature, and the docstring says `trace` is unused.
- T472 `xuc865/roleagent` `load_state_dict_to_megatron_llama(...,
  tie_word_embeddings=False)`: deprecated loader keeping the current loader's
  signature.
- T984 `PrunaAI/pruna` `get_model_dependent_hyperparameter_defaults(self,
  model, smash_config)`: a method of an algorithm base interface.
- T527 `Luo-Yihao/FaithC` `scatter_mean(..., fill_value=0)`: a
  `torch_scatter` compatibility shim. Labeled genuine because the shim keeps
  the library signature; note that the accepted `fill_value` has no effect, so
  this is the borderline case of the set.

Direction: do not report a parameter whose function shares its name and
parameter list with a sibling in the same repository, matches a known
framework callback signature, or overrides a method, and honour a docstring
that says the parameter is unused.

**A constant that is the answer (`return_constant_stub`, 7):**

- T857 `dsphper/lanhu-mcp` `_get_stage4_prompt_developer`, T628
  `axcslmd/video-auto-maker` `blocked_message`, T591
  `howyoungchen/deepRolePlay` `create_done_message`: the name says it returns
  a prompt or message.
- T245 `ericjiang18/Agent-Q-Mix` `write_document`: a `@tool` whose
  acknowledgement string is the protocol answer.
- T104 `Alibaba-NLP/ZeroSearch` `TokenizerGroup.ping`: a local object is
  alive by construction.
- T903 `khscience/OSkhQuant` `normalize_data_source`, T965 `open-webui/oikb`
  `parse_hubspot_source`: the docstring or comment declares the single answer
  (these also carry `ignored_parameter`).

Direction: treat a function whose name ends in `_prompt` or `_message`, or
starts with `create_` and returns a string literal, as a constant provider; a
multi-line string constant is content, not a stub; a docstring or leading
comment that names the fixed answer declares it.

**An empty or `None` interface method (4) and a dispatch default (1):**

- T264 `AbdelStark/jev-benchmarks` `GLiNERBackend.close` (`return None`),
  T320 `DeepExperience/VAD_Multimodal_OPD` `LocalLogger.flush` (`pass`): no-op
  members of an adapter or logger interface whose base is not in the module.
- T184 `dexmal/dexbotic` `get_output_embeddings` (`return None`): a
  transformers hook, and the comment says why it returns `None`.
- T595 `porterminal/porterminal` `PTYManagerAdapter.spawn`: the docstring says
  "Already spawned in factory.", a no-op declared without the words the rule
  looks for.
- T421 `MINT-SJTU/Evo-RL` `close_envs`: the `@singledispatch` default raising
  `NotImplementedError` for unknown types is the dispatch contract.

Direction: a `@singledispatch` base function is a contract; an override of a
known framework hook (`get_output_embeddings`) is declared; a comment directly
above `return None` declares it. The adapter no-ops need the base, which is
outside the module, so they stay a known limit.

## Compared with v2

v2 (842 functions, development data since its fixes) measured 3.12.0 at 3 of
12 hollow found and 12 of 828 genuine flagged. v3 is a new draw and a newer
detector, so the two are not the same measurement. v3 is now spent: by
PROTOCOL.md section 10, a rule changed after reading these results makes v3
development data, and the next independent figure needs a new draw.
