"""The semantic channel follows inputs and effects through the module's own calls.

Each finding carries a status: DOCUMENTED_PROMISE when the docstring names
the dropped input (the function promises to use it), REVIEW_CANDIDATE
otherwise (no effect was seen, but nothing states that one is owed).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector


def _semantic(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted((f.function, f.kind, tuple(f.inputs), f.status) for f in result.semantic_findings)


def test_an_input_dropped_two_calls_down_is_reported(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def export(rows, fmt):
            return _render(rows, fmt)

        def _render(rows, fmt):
            return _encode(rows, fmt)

        def _encode(rows, fmt):
            return [str(r) for r in rows]
        """,
    )
    assert ("export", "input_never_used", ("fmt",), "REVIEW_CANDIDATE") in found


def test_an_input_used_in_a_condition_down_the_chain_is_not_reported(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def export(rows, fmt):
            return _encode(rows, fmt)

        def _encode(rows, fmt):
            if fmt == "csv":
                return ",".join(map(str, rows))
            return [str(r) for r in rows]
        """,
    )
    assert found == []


def test_an_input_passed_by_keyword_and_dropped_is_reported(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def fetch(url, timeout=30):
            \"\"\"Fetch url; give up after timeout seconds.\"\"\"
            return _get(url, timeout=timeout)

        def _get(url, timeout=None):
            return url.upper()
        """,
    )
    assert ("fetch", "input_never_used", ("timeout",), "DOCUMENTED_PROMISE") in found


def test_an_input_passed_through_star_args_abstains(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def export(rows, *options):
            return _encode(rows, *options)

        def _encode(rows, *options):
            return [str(r) for r in rows]
        """,
    )
    assert [f for f in found if f[0] == "export"] == []


def test_a_function_that_can_report_failure_is_not_success_without_effect(tmp_path):
    found = _semantic(
        tmp_path,
        """
        class Job:
            def run(self, items):
                if not items:
                    return False
                self._prepare(items)
                return True

            def _prepare(self, items):
                return None
        """,
    )
    assert [f for f in found if f[1] == "success_without_effect"] == []


def test_a_helper_writing_state_is_an_effect(tmp_path):
    found = _semantic(
        tmp_path,
        """
        class Job:
            def run(self, items):
                self._store(items)
                return True

            def _store(self, items):
                self.items = list(items)
        """,
    )
    assert [f for f in found if f[1] == "success_without_effect"] == []


def test_success_without_effect_is_a_review_candidate(tmp_path):
    found = _semantic(
        tmp_path,
        """
        class Job:
            def run(self):
                self._prepare()
                return True

            def _prepare(self):
                return None
        """,
    )
    assert ("Job.run", "success_without_effect", (), "REVIEW_CANDIDATE") in found


# --- call binding: a call joins the closed graph only when its target is certain


def test_a_parameter_shadowing_a_module_function_is_not_that_function(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def helper(x):
            return True

        def save(x, helper):
            return helper(x)
        """,
    )
    assert [f for f in found if f[0] == "save"] == []


def test_a_local_rebinding_of_a_module_function_name_is_open(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def helper(x):
            return True

        def save(x, factory):
            helper = factory()
            return helper(x)

        def load(x, handlers):
            return [helper(x) for helper in handlers]
        """,
    )
    assert [f for f in found if f[0] in ("save", "load")] == []


def test_a_module_name_bound_twice_is_ambiguous(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def helper(x):
            return True

        helper = make_helper()

        def save(x):
            return helper(x)
        """,
    )
    assert [f for f in found if f[0] == "save"] == []


def test_an_instance_attribute_shadowing_a_method_is_open(tmp_path):
    found = _semantic(
        tmp_path,
        """
        class Store:
            def __init__(self, writer):
                self._write = writer

            def save(self, record):
                return self._write(record)

            def _write(self, payload):
                return True
        """,
    )
    assert [f for f in found if f[0] == "Store.save"] == []


def test_a_rebound_builtin_is_not_pure(tmp_path):
    found = _semantic(
        tmp_path,
        """
        from audit import record as len

        class Job:
            def run(self, items):
                self._prepare(items)
                return True

            def _prepare(self, items):
                len(items)
        """,
    )
    assert [f for f in found if f[1] == "success_without_effect"] == []


def test_reflection_and_star_arguments_stay_open(tmp_path):
    found = _semantic(
        tmp_path,
        """
        class Store:
            def save(self, record, name):
                return getattr(self, name)(record)

            def put(self, record, *rest):
                return self._write(*rest, record)

            def _write(self, payload, extra=None):
                return True
        """,
    )
    # The target of self._write is certain, so its success answer still counts;
    # only the mapping of the arguments is open.
    assert [f for f in found if f[1] == "input_never_used"] == []


def test_a_uniquely_bound_module_helper_is_followed(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def helper(x, mode):
            return x

        def wrapper(x, mode):
            return helper(x, mode)
        """,
    )
    assert ("wrapper", "input_never_used", ("mode",), "REVIEW_CANDIDATE") in found


# --- input influence: a value that only lands in locals nobody reads is dropped


def test_an_input_built_into_a_discarded_local_is_reported(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def answer(question):
            prompt = f"Q: {question}"
            return "The answer is 42."
        """,
    )
    assert ("answer", "input_never_used", ("question",), "REVIEW_CANDIDATE") in found


def test_an_input_through_a_chain_of_dead_locals_is_reported(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def score(text, weight):
            scaled = weight * 2
            doubled, label = scaled + 1, "w"
            return len(text)
        """,
    )
    assert ("score", "input_never_used", ("weight",), "REVIEW_CANDIDATE") in found


def test_a_local_that_reaches_an_external_call_is_a_use(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def answer(question, llm):
            prompt = f"Q: {question}"
            return llm.complete(prompt)
        """,
    )
    assert found == []


def test_an_input_deciding_a_branch_is_a_use(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def pick(rows, descending):
            flag = not descending
            if flag:
                return rows
            return list(reversed(rows))
        """,
    )
    assert found == []


def test_an_iterated_input_counts_through_the_loop(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def count(items):
            n = 0
            for _ in items:
                n += 1
            return n
        """,
    )
    assert found == []


def test_locals_read_by_locals_or_a_closure_are_used(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def render(template, name):
            title = name + "!"
            return template.format(**locals())

        def later(value):
            kept = value + 1
            return lambda: kept
        """,
    )
    assert found == []


def test_an_attribute_read_is_a_use(tmp_path):
    """`conn.closed` may be a property that runs code."""
    found = _semantic(
        tmp_path,
        """
        def ping(conn):
            state = conn.closed
            return 0
        """,
    )
    assert found == []


def test_an_input_choosing_a_discarded_value_is_reported(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def label(size, verbose):
            text = "long" if verbose else "short"
            return str(size)
        """,
    )
    assert ("label", "input_never_used", ("verbose",), "REVIEW_CANDIDATE") in found


# --- frame reads, overwritten values and unreachable reads


def test_a_dropped_locals_snapshot_is_no_use(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def build_payload_fake(record):
            payload = dict(locals())
            return {"success": True}

        def answer(question):
            prompt = f"Q: {question}"
            unused = dict(locals())
            return "canned"
        """,
    )
    assert ("build_payload_fake", "input_never_used", ("record",), "REVIEW_CANDIDATE") in found
    assert ("answer", "input_never_used", ("question",), "REVIEW_CANDIDATE") in found


def test_a_returned_or_forwarded_locals_snapshot_is_a_use(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def build_payload(record):
            return dict(locals())

        def render(template, name):
            title = name + "!"
            return template.format(**vars())
        """,
    )
    assert found == []


def test_eval_or_exec_leaves_every_input_undecided(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def run(source, value):
            kept = value + 1
            exec(source)
            return 0
        """,
    )
    assert found == []


def test_a_value_overwritten_before_use_is_dropped(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def answer(question):
            prompt = f"Q: {question}"
            prompt = "A canned answer"
            return prompt
        """,
    )
    assert ("answer", "input_never_used", ("question",), "REVIEW_CANDIDATE") in found


def test_an_augmented_value_keeps_its_input(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def shout(text):
            line = text
            line += "!"
            return line
        """,
    )
    assert found == []


def test_a_value_overwritten_in_a_branch_may_survive(tmp_path):
    """Only straight-line definitions are versioned; a branch keeps the name whole."""
    found = _semantic(
        tmp_path,
        """
        def answer(question, short):
            prompt = f"Q: {question}"
            if short:
                prompt = "brief"
            return prompt
        """,
    )
    assert found == []


def test_a_read_after_return_is_no_use(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def bump(value):
            kept = value + 1
            return 0
            print(kept)
        """,
    )
    assert ("bump", "input_never_used", ("value",), "REVIEW_CANDIDATE") in found


def test_an_effect_after_return_does_not_count(tmp_path):
    found = _semantic(
        tmp_path,
        """
        class Job:
            def run(self):
                self._prepare()
                return True
                self.items = []

            def _prepare(self):
                return None
        """,
    )
    assert ("Job.run", "success_without_effect", (), "REVIEW_CANDIDATE") in found


# --- a parameter overwritten before use: the caller's value is dropped


def test_an_overwritten_parameter_is_dropped(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def answer(question):
            question = "The answer is always 42."
            return question
        """,
    )
    assert ("answer", "input_never_used", ("question",), "REVIEW_CANDIDATE") in found


def test_a_parameter_used_before_or_in_its_update_is_kept(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def shout(question, suffix):
            question += suffix
            return question

        def clean(question):
            question = question.strip()
            return question

        def logged(question, log):
            log.info(question)
            question = "next"
            return question
        """,
    )
    assert found == []


def test_a_parameter_overwritten_in_a_branch_may_survive(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def answer(question, short):
            if short:
                question = "brief"
            return question
        """,
    )
    assert found == []


def test_an_explicit_discard_into_underscore_is_handled(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def build(cfg, model, batch):
            _ = (cfg, model)
            return {"x": batch}
        """,
    )
    assert found == []


def test_a_store_to_a_declared_global_is_an_effect(tmp_path):
    found = _semantic(
        tmp_path,
        """
        _handler = None

        def start(on_event, mode):
            global _handler
            _handler = on_event
            return mode
        """,
    )
    assert found == []


def test_an_annotation_without_a_value_defines_nothing(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def load(components, reader):
            components: dict
            components = reader.read(components)
            return list(components)
        """,
    )
    assert found == []


def test_a_parameter_reserved_for_future_use_is_declared(tmp_path):
    found = _semantic(
        tmp_path,
        '''
        def run(genotypes, options=None):
            """Report on genotypes.

            options: Reserved for future use.
            """
            options = options or {}
            return sorted(genotypes)
        ''',
    )
    assert found == []


def test_an_annotated_parameter_still_flows_like_any_other(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def score(weight, text):
            weight: float
            scaled = weight * 2
            return len(text)
        """,
    )
    assert ("score", "input_never_used", ("weight",), "REVIEW_CANDIDATE") in found


# --- paths: a failure that ends in a success report


def _kinds(found, function):
    return {kind for name, kind, _, _ in found if name == function}


def test_a_swallowed_failure_falling_through_to_success_is_reported(tmp_path):
    found = _semantic(
        tmp_path,
        """
        import logging
        log = logging.getLogger(__name__)

        def send(client, msg):
            try:
                client.send(msg)
            except Exception:
                log.error("send failed")
            return True
        """,
    )
    assert "failure_reported_as_success" in _kinds(found, "send")


def test_a_handler_that_reports_or_raises_is_not_a_hidden_failure(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def send(client, msg):
            try:
                client.send(msg)
            except Exception:
                return False
            return True

        def push(client, msg):
            try:
                client.send(msg)
            except Exception as error:
                raise RuntimeError("push failed") from error
            return True

        def ping(client):
            try:
                client.ping()
            except TimeoutError:
                pass
            return True
        """,
    )
    assert [f for f in found if f[1] == "failure_reported_as_success"] == []


def test_a_return_in_finally_hides_every_failure(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def send(client, msg):
            try:
                client.send(msg)
            finally:
                return True

        def close(client):
            try:
                client.flush()
            finally:
                client.close()
            return True
        """,
    )
    assert "finally_return_hides_failure" in _kinds(found, "send")
    assert "finally_return_hides_failure" not in _kinds(found, "close")


def test_success_after_discarding_the_operation_outcome_is_reported(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def send(client, msg):
            ok = client.send(msg)
            return True
        """,
    )
    assert "success_ignores_outcome" in _kinds(found, "send")


def test_a_checked_or_deliberately_discarded_outcome_is_not_ignored(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def send(client, msg):
            ok = client.send(msg)
            if not ok:
                return False
            return True

        def fire(client, msg):
            _ = client.send(msg)
            return True

        def store(client, msg):
            receipt = client.send(msg)
            return receipt
        """,
    )
    assert [f for f in found if f[1] == "success_ignores_outcome"] == []


def test_path_findings_need_work_a_final_success_and_a_dead_outcome(tmp_path):
    found = _semantic(
        tmp_path,
        """
        import logging
        log = logging.getLogger(__name__)

        def lookup(data):
            try:
                value = data["key"]
            except Exception:
                log.error("missing")
            return True

        def maybe(client, msg, flag):
            try:
                client.send(msg)
            except Exception:
                log.error("send failed")
            if flag:
                return True

        def logged(client, msg):
            ok = client.send(msg)
            log.info("sent: %s", ok)
            return True

        def echo(client, msg):
            ok = client.send(msg)
            return msg

        def relay(client, msg):
            try:
                client.send(msg)
            except Exception:
                log.error("send failed")
            return msg
        """,
    )
    kinds = {"failure_reported_as_success", "success_ignores_outcome"}
    assert [f for f in found if f[1] in kinds] == []


def test_a_best_effort_step_inside_larger_work_is_not_a_hidden_failure(tmp_path):
    found = _semantic(
        tmp_path,
        """
        import logging
        log = logging.getLogger(__name__)

        class Gateway:
            def start(self, config):
                self.load(config)
                try:
                    self.enable_diagnostics()
                except Exception:
                    log.debug("diagnostics unavailable")
                self.serve()
                return True
        """,
    )
    assert [f for f in found if f[1] == "failure_reported_as_success"] == []


def test_a_return_in_a_function_defined_in_finally_is_not_a_finally_return(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def run(workers):
            try:
                workers.start()
            finally:
                def close(worker):
                    return worker.close()
                workers.each(close)
            return True
        """,
    )
    assert [f for f in found if f[1] == "finally_return_hides_failure"] == []


def _effect_states(source: str) -> dict:
    import ast

    from slop_detector import semantic

    graph = semantic._Graph(ast.parse(textwrap.dedent(source)))
    states = semantic._with_effect(graph)[0]
    return {graph.qualname(f): state for f, state in states.items()}


def test_effects_are_observed_unknown_or_absent_in_the_closed_graph():
    states = _effect_states(
        """
        def push(client, record):
            client.post("/records", json=record)
            return True

        def remember(cache, record):
            cache[record.id] = record
            return True

        def check(record):
            return _valid(record)

        def _valid(record):
            return record is not None

        def both(cache, client, record):
            push(client, record)
            remember(cache, record)
            return True

        async def settle(future):
            await future
            return True
        """
    )
    assert states["push"] == "EFFECT_UNKNOWN"
    assert states["remember"] == "EFFECT_OBSERVED"
    assert states["check"] == "NO_EFFECT_IN_CLOSED_GRAPH"
    assert states["_valid"] == "NO_EFFECT_IN_CLOSED_GRAPH"
    assert states["both"] == "EFFECT_OBSERVED"
    assert states["settle"] == "EFFECT_UNKNOWN"


def test_a_bare_call_to_a_module_coroutine_never_runs(tmp_path):
    source = """
        class Store:
            async def _write(self, record):
                await self.db.insert(record)

            async def save(self, record):
                self._write(record)
                return True

            async def save_awaited(self, record):
                await self._write(record)
                return True

            def save_scheduled(self, loop, record):
                loop.create_task(self._write(record))
                return True
        """
    found = _semantic(tmp_path, source)
    assert [f[0] for f in found if f[1] == "effect_never_runs"] == ["Store.save"]
    states = _effect_states(source)
    assert states["Store.save"] == "NO_EFFECT_IN_CLOSED_GRAPH"
    assert states["Store.save_awaited"] == "EFFECT_UNKNOWN"


def test_a_bare_call_to_a_module_generator_never_runs(tmp_path):
    found = _semantic(
        tmp_path,
        """
        def _flush(rows):
            for row in rows:
                row.commit()
                yield row

        def _nothing():
            return
            yield

        def flush(rows):
            _flush(rows)
            _nothing()
            return True

        def flush_all(rows):
            list(_flush(rows))
            for _ in _flush(rows):
                pass
            return True
        """,
    )
    never = sorted((f[0], f[2]) for f in found if f[1] == "effect_never_runs")
    assert never == [("flush", ("_flush",)), ("flush", ("_nothing",))]


def test_a_decorated_or_plain_callee_runs_when_called(tmp_path):
    found = _semantic(
        tmp_path,
        """
        import contextlib

        @contextlib.contextmanager
        def _session():
            yield

        def _commit(rows):
            for row in rows:
                row.commit()

        def run(rows):
            _session()
            _commit(rows)
            return True

        def rerun(rows):
            _commit(rows)
            return True
        """,
    )
    assert [f for f in found if f[1] == "effect_never_runs"] == []


def test_a_name_bound_again_resolves_open_and_recursion_stays_closed():
    states = _effect_states(
        """
        def _store(record):
            return True

        def install(fake):
            global _store
            _store = fake

        def save(record):
            _store(record)
            return True

        def _write(record):
            return True

        def save_local(record):
            from backend import _write
            _write(record)
            return True

        def _walk(node):
            if node:
                return _walk(node.next)
            return True
        """
    )
    assert states["save"] == "EFFECT_UNKNOWN"
    assert states["save_local"] == "EFFECT_UNKNOWN"
    assert states["_walk"] == "NO_EFFECT_IN_CLOSED_GRAPH"


def test_a_self_call_to_a_method_left_to_subclasses_is_open(tmp_path):
    source = """
        class Extractor:
            def prepare(self, events):
                self._get_data(events)
                return True

            def _get_data(self, events):
                for _ in events:
                    yield None
                raise NotImplementedError
        """
    found = _semantic(tmp_path, source)
    assert [f for f in found if f[1] == "effect_never_runs"] == []
    assert _effect_states(source)["Extractor.prepare"] == "EFFECT_UNKNOWN"


def test_a_context_manager_or_an_async_step_runs_code_from_elsewhere(tmp_path):
    source = """
        class Repo:
            def save(self, record):
                with self.session:
                    self._check(record)
                return True

            def _check(self, record):
                return record is not None

        async def drain(stream):
            async for _ in stream:
                pass
            return True

        async def collect(stream):
            return [item async for item in stream]

        async def guarded(lock):
            async with lock:
                pass
            return True

        def scan(rows):
            for _ in rows:
                pass
            return True
        """
    states = _effect_states(source)
    for name in ("Repo.save", "drain", "collect", "guarded"):
        assert states[name] == "EFFECT_UNKNOWN", name
    assert states["scan"] == "NO_EFFECT_IN_CLOSED_GRAPH"
    # The unknown ones are never candidates; `scan` walks its input, does
    # nothing and reports success: a check that passes whatever it finds.
    assert [f[0] for f in _semantic(tmp_path, source) if f[1] == "success_without_effect"] == ["scan"]
    import ast

    from slop_detector import semantic

    graph = semantic._Graph(ast.parse(textwrap.dedent(source)))
    reasons = {graph.qualname(f): r for f, r in semantic._with_effect(graph)[2].items()}
    assert reasons["Repo.save"] == {"context_manager"}
    assert reasons["guarded"] == {"context_manager"}
    assert reasons["drain"] == reasons["collect"] == {"external_awaitable"}
