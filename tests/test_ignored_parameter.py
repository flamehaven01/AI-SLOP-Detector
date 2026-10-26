"""A parameter the function never reads, or reads only to log it, does not shape its result.

`upload(..., timeout_s=30.0)` that never applies the timeout, `verify_token(token,
secret)` that never checks the signature, `fetch_exchange_rates(base)` that logs
the base and returns a fixed table (recall corpus: 8 functions). `ignored_parameter`
reports each such parameter.

Not reported: `self` / `cls`, names starting with `_`, `*args` / `**kwargs`,
dunder methods, and functions whose signature is fixed elsewhere: abstract or
contract methods, overrides of a module base, callbacks registered by value,
decorated functions (routes, fixtures, properties), and methods of a class with
a base defined outside the module.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector

PID = "ignored_parameter"


def _found(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted((i.line, i.message) for i in result.pattern_issues if i.pattern_id == PID)


def test_an_unused_parameter_is_reported(tmp_path):
    source = """
    def upload(client, path, bucket, timeout_s=30.0):
        data = path.read_bytes()
        return client.put(bucket, path.name, data)
    """
    found = _found(tmp_path, source)
    assert [line for line, _ in found] == [2]
    assert "'timeout_s'" in found[0][1]


def test_a_parameter_read_only_by_logging_is_not_reported(tmp_path):
    """External replay: `logging_name` (AlphaFold3), `reason` (hermes-agent) exist to be
    logged; a log line is a use."""
    source = """
    import logging
    logger = logging.getLogger(__name__)

    def get_conformer(mol, logging_name="", seed=0):
        try:
            return mol.embed(seed)
        except ValueError:
            logger.warning("embedding failed for %s", logging_name)
            raise
    """
    assert _found(tmp_path, source) == []


def test_a_same_name_parameter_of_a_nested_function_is_not_a_use(tmp_path):
    """Audit F-P1-02: the inner `timeout` is another variable."""
    source = """
    def validate(job, timeout=30):
        def helper(timeout):
            return timeout * 2
        return job.check(helper(5))
    """
    found = _found(tmp_path, source)
    assert len(found) == 1 and "'timeout'" in found[0][1]


def test_a_nested_function_reading_the_outer_parameter_is_a_use(tmp_path):
    source = """
    def schedule(jobs, timeout=30):
        def run(job):
            return job.go(timeout)
        return [run(j) for j in jobs]
    """
    assert _found(tmp_path, source) == []


def test_each_ignored_parameter_is_one_finding(tmp_path):
    source = """
    def can_delete(user, resource=None, reason=""):
        return user is not None
    """
    found = _found(tmp_path, source)
    assert len(found) == 2
    assert "'resource'" in found[0][1] + found[1][1] and "'reason'" in found[0][1] + found[1][1]


def test_parameters_that_shape_the_result_are_not_reported(tmp_path):
    source = """
    def scale(values, factor=2.0, *, offset=0.0):
        return [v * factor + offset for v in values]

    def nested(items, key):
        def pick(item):
            return item[key]
        return [pick(i) for i in items]
    """
    assert _found(tmp_path, source) == []


@pytest.mark.parametrize(
    "source",
    [
        "def handler(_event, context):\n    return context.id\n",  # underscore name
        "def handler(*args, **kwargs):\n    return 1\n",  # varargs
        "class A:\n    def method(self, x):\n        return x\n    @classmethod\n    def make(cls):\n        return 1\n",
        "class A:\n    def __exit__(self, exc_type, exc, tb):\n        return None\n",  # dunder
        "import abc\nclass A(abc.ABC):\n    @abc.abstractmethod\n    def run(self, job):\n        raise NotImplementedError\n",
        "class Base:\n    def run(self, job):\n        return job.go()\nclass Child(Base):\n    def run(self, job):\n        return 1\n",  # override
        "def on_event(event, ctx):\n    return 'ok'\n\nregister(on_event)\n",  # callback
        "@app.get('/health')\ndef health(request):\n    return {'ok': True}\n",  # decorated
        "import torch\nclass Net(torch.nn.Module):\n    def forward(self, x, mask=None):\n        return x\n",  # external base
    ],
)
def test_signatures_fixed_elsewhere_are_not_reported(tmp_path, source):
    assert _found(tmp_path, source) == []


def test_an_unused_positional_in_a_function_returning_nothing_is_not_reported(tmp_path):
    """External replay: SAX-style handlers `_start_x(self, name, attributes)` and
    output helpers `print_step(message)` take fixed arguments and return nothing."""
    source = """
    def start_element(name, attributes):
        STACK.append(1)

    def print_step(step, message):
        print("step", step)
    """
    assert _found(tmp_path, source) == []


def test_an_unused_positional_is_reported_when_no_return_depends_on_any_input(tmp_path):
    source = """
    def summarize(records):
        return {"2024-01": 120, "2024-02": 98}

    def can_delete(user, resource):
        return True
    """
    found = _found(tmp_path, source)
    assert len(found) == 3  # records; user and resource


def test_an_unused_positional_beside_a_result_that_uses_another_input_is_not_reported(tmp_path):
    source = """
    def resize(image, interpolation):
        return image.scaled(2)
    """
    assert _found(tmp_path, source) == []


@pytest.mark.parametrize(
    "source",
    [
        # (a) an explicit discard (alphafold3 table.get_row_by_key)
        "def get_row(key, column_name_map=None):\n    del column_name_map\n    return TABLE[key]\n",
        # (c) the docstring says why it is kept (biopython, HealthChain)
        'def get_all(file_format=""):\n    """file_format: a legacy parameter left to avoid breaking changes."""\n    return fetch()\n',
        'def demographics(patients, admissions=None):\n    """admissions: not used, kept for compatibility."""\n    return patients.age\n',
        # (d) the body is a stub; other patterns report stubs
        'def autocommit(conn, y=1):\n    """Set autocommit."""\n',
        "def autocommit(conn, y=1):\n    pass\n",
        # (b) a result built from the inputs through a local is not input-free
        "def tv(codons1, codons2, table):\n    counts = [0, 0]\n    for a, b in zip(codons1, codons2):\n        counts[0] += a != b\n    return counts\n",
        # (b) methods answering with a literal are hooks of their class
        "class Pattern:\n    def check_node(self, node, file, lines):\n        return []\n",
        "class Location:\n    def _flip(self, length):\n        return self\n",
    ],
)
def test_declared_or_derived_cases_from_the_external_replay_are_not_reported(tmp_path, source):
    assert _found(tmp_path, source) == []


def test_methods_sharing_a_parameter_list_are_an_interface(tmp_path):
    """(e) biopython PrintFormat: `_make_map_only(self, ls, title, nc=(), s1="")` and its
    siblings take the same arguments and are dispatched by name."""
    source = """
    class PrintFormat:
        def _make_list(self, ls, title, nc=(), s1=""):
            return title + str(ls) + str(nc) + s1

        def _make_map_only(self, ls, title, nc=(), s1=""):
            return title + str(ls) + s1
    """
    assert _found(tmp_path, source) == []


def test_an_option_the_docstring_promises_and_the_body_ignores_is_reported(tmp_path):
    """External replay true positive (jieba lac_small): `for_infer` is documented, unused."""
    source = '''
    def lex_net(word, vocab_size, for_infer=True):
        """for_infer: whether the model is built for training or predicting."""
        emb = embed(word, vocab_size)
        return predict(emb)
    '''
    found = _found(tmp_path, source)
    assert len(found) == 1 and "'for_infer'" in found[0][1]


def test_a_nested_default_callback_is_not_reported(tmp_path):
    """External replay (biopython Phylo): a nested default answering with a literal."""
    source = """
    def draw(tree, label_colors=None):
        if label_colors:
            return paint(tree, label_colors)
        def get_label_color(label):
            return "black"
        return paint(tree, get_label_color)
    """
    assert _found(tmp_path, source) == []


def test_sibling_methods_with_the_same_names_in_another_order_are_an_interface(tmp_path):
    source = """
    class PrintFormat:
        def _make_list(self, ls, title, nc=(), s1=""):
            return title + str(ls) + str(nc) + s1

        def _make_nocut_only(self, nc, s1, ls=(), title=""):
            return s1 + str(nc)
    """
    assert _found(tmp_path, source) == []


def test_a_command_handler_returning_exit_codes_is_not_reported(tmp_path):
    """External replay (hermes-agent CLI): `_cmd_open(args) -> int` answers 0 or 1."""
    source = """
    def cmd_open(args):
        if not launch():
            return 1
        return 0
    """
    assert _found(tmp_path, source) == []


def test_a_boolean_answer_ignoring_its_inputs_is_still_reported(tmp_path):
    source = """
    def can_delete(user, resource):
        return True
    """
    assert len(_found(tmp_path, source)) == 2
