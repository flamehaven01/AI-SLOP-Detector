"""H3-2: a claim is CONTRADICTED only when the bounded scope holds an
implementation incompatible with it and nothing unresolved could overturn
it; anything short of that is UNDECIDED with its reason."""

import ast

import pytest

from slop_detector import claim_judge
from slop_detector.claim_judge import judge_claims


def _verdicts(source):
    result = judge_claims(ast.parse(source), False)
    return {(c.function, c.kind): (v.state, v.basis) for c, v in result.verdicts}


CONTRADICTED = '''
import logging
logger = logging.getLogger(__name__)

def fetch_exchange_rates(base):
    """Fetch live exchange rates for the base currency."""
    logger.info("fetching %s", base)
    return {"EUR": 0.92, "GBP": 0.79}

def explain(model, features):
    """Attribute the prediction to each feature with SHAP values."""
    return {f"f{i}": 0.0 for i in range(len(features))}

def validate_record(record):
    """Validate the record."""
    return 42

def validate_config(config):
    """Validate that all required settings are present."""
    # TODO: implement
    return True

class Ensemble:
    def __init__(self):
        pass

    def score(self):
        """Mean of the member scores."""
        return self.scores[0]

def total_parallel(values):
    """Sum the values in parallel."""
    total = 0
    for v in values:
        total += v
    return total

def list_all(path):
    """Fetch every page of the collection."""
    return []
'''


def test_an_incompatible_body_with_no_open_path_is_contradicted():
    v = _verdicts(CONTRADICTED)
    assert v[("fetch_exchange_rates", "live_data")] == ("CONTRADICTED", "literal_result")
    assert v[("explain", "computed_result")] == ("CONTRADICTED", "literal_result")
    # a single outcome cannot tell valid input from invalid: not SUPPORTED
    assert v[("validate_record", "validation")] == ("CONTRADICTED", "single_outcome")
    assert v[("validate_config", "validation")] == ("CONTRADICTED", "single_outcome")
    # a dunder sibling with an empty body does not make the class an extension point
    assert v[("Ensemble.score", "aggregation")] == ("CONTRADICTED", "single_member_read")
    assert v[("total_parallel", "parallel")] == ("CONTRADICTED", "no_concurrent_call")
    assert v[("list_all", "pagination")] == ("CONTRADICTED", "no_request")


UNRESOLVED = '''
import asyncio
import threading
import numpy as np
from tools import BaseTool, register

def sanitize_username(name: str) -> str:
    """Strip whitespace and reject characters outside [a-z0-9_.-]."""
    return name.strip()

class EnsembleModel:
    def predict(self, features):
        """Weighted mean of the member models' scores."""
        return self.models[0].predict(features)

    def blended(self, scores, weights):
        """Weighted mean of the member models' scores."""
        return np.average(scores, weights=weights)

async def upload_all(client, paths):
    """Upload the files in parallel."""
    for path in paths:
        await asyncio.sleep(0)
        await client.put(path)

def upload_many(client, paths):
    """Upload the files in parallel."""
    lock = threading.Lock()
    return [client.put(p) for p in paths]

class RewardTool(BaseTool):
    def calc_reward(self, item):
        """Calculate the reward of the tool."""
        return 0.0

class Hooks:
    def compute_biases(self, messages):
        """Compute per-message compression bias."""
        return {}

    def post_compress(self, result):
        """Run after compression."""
        pass

@register
def compute_score(x):
    """Compute the score of x."""
    return 0

def compute_remote(client, x):
    """Compute the embedding of x."""
    return client.embed(x)

def list_via_client(client):
    """Fetch every page of the collection."""
    return client.list_all()

def check_delay(real, expected):
    """Validate that the measured delay matches the expected one."""
    if real != expected:
        print("delay mismatch", real, expected)

def compute_identity(x):
    """Compute the value of x."""
    return x
'''


def test_a_path_that_could_overturn_the_judgment_leaves_it_undecided():
    v = _verdicts(UNRESOLVED)
    # a type annotation is not the runtime receiver: `strip` stays an open call
    assert v[("sanitize_username", "rejection")] == ("UNDECIDED", "declared_str_only")
    # the element's own method is an open call: the index alone proves nothing
    assert v[("EnsembleModel.predict", "aggregation")] == ("UNDECIDED", "single_member_open_call")
    assert v[("EnsembleModel.blended", "aggregation")] == ("UNDECIDED", "open_call")
    # a concurrency library call is no evidence of concurrent work
    assert v[("upload_all", "parallel")] == ("UNDECIDED", "async")
    assert v[("upload_many", "parallel")] == ("UNDECIDED", "open_call")
    assert v[("RewardTool.calc_reward", "computed_result")] == ("UNDECIDED", "imported_base")
    assert v[("Hooks.compute_biases", "computed_result")] == (
        "UNDECIDED",
        "extension_point_default",
    )
    assert v[("compute_score", "computed_result")] == ("UNDECIDED", "decorated")
    assert v[("compute_remote", "computed_result")] == ("UNDECIDED", "open_call")
    assert v[("list_via_client", "pagination")] == ("UNDECIDED", "open_call")
    assert v[("check_delay", "validation")] == ("UNDECIDED", "outcome_logged")
    # returning the input unchanged is not a computation, nor its absence
    assert v[("compute_identity", "computed_result")] == ("UNDECIDED", "no_proof")


CONTRACTS = '''
class Scorer:
    def score(self, batch):
        """Compute the batch score."""
        raise NotImplementedError

class NullScorer(Scorer):
    def score(self, batch):
        """Compute the batch score."""
        return 0.0

class MeanScorer(Scorer):
    def score(self, batch):
        """Compute the mean batch score."""
        return 0.0

def wrap(cls):
    return cls

@wrap
class Wrapped:
    def total(self):
        """Compute the total."""
        return 0

class Props:
    @property
    def total(self):
        """Compute the total."""
        return 0

    @staticmethod
    def size():
        """Compute the size."""
        return 0
'''


def test_alternative_implementations_and_decorators_by_origin():
    v = _verdicts(CONTRACTS)
    # the interface's own sentence copied into an implementation
    assert v[("NullScorer.score", "computed_result")] == ("UNDECIDED", "implements_module_contract")
    # an implementation's own claim is judged as its own
    assert v[("MeanScorer.score", "computed_result")] == ("CONTRADICTED", "literal_result")
    assert v[("Wrapped.total", "computed_result")] == ("UNDECIDED", "class_wrapped")
    # builtin property / staticmethod keep the body as written
    assert v[("Props.total", "computed_result")] == ("CONTRADICTED", "literal_result")
    assert v[("Props.size", "computed_result")] == ("CONTRADICTED", "literal_result")
    rebound = "property = lambda f: f\n" + CONTRACTS
    assert _verdicts(rebound)[("Props.total", "computed_result")] == ("UNDECIDED", "decorated")


SUPPORTED = '''
import threading
from concurrent.futures import ThreadPoolExecutor

class Client:
    def get(self, url):
        return self.session.get(url)

    def iter_pages(self, path):
        """Yield every page of a paginated collection, following next links."""
        url = path
        while url:
            page = self.get(url)
            yield page
            url = page.get("next")

def is_valid(value):
    """Validate the address format."""
    return "@" in value and "." in value

def validate_flag(flag):
    """Validate the flag."""
    if flag is None:
        return False
    return True

def validate_name(name):
    """Validate the name."""
    if not name:
        raise ValueError("empty")
    return name

def compute_area(width, height):
    """Compute the area of the rectangle."""
    return width * height

def upload_pool(client, paths):
    """Upload the files in parallel."""
    with ThreadPoolExecutor() as pool:
        return list(pool.map(client.put, paths))

def upload_threads(client, paths):
    """Upload the files in parallel."""
    threads = [threading.Thread(target=client.put, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

class Ensemble:
    def score(self):
        """Mean of the member scores."""
        return sum(m.score() for m in self.members) / len(self.members)
'''


def test_structural_evidence_is_supported():
    v = _verdicts(SUPPORTED)
    assert v[("Client.iter_pages", "pagination")] == ("SUPPORTED", "loop_with_call")
    assert v[("is_valid", "validation")] == ("SUPPORTED", "outcome_from_input")
    assert v[("validate_flag", "validation")] == ("SUPPORTED", "distinct_outcomes")
    assert v[("validate_name", "validation")] == ("SUPPORTED", "raise_or_assert")
    assert v[("compute_area", "computed_result")] == ("SUPPORTED", "computed_from_inputs")
    assert v[("upload_pool", "parallel")] == ("SUPPORTED", "concurrency_structure")
    assert v[("upload_threads", "parallel")] == ("SUPPORTED", "concurrency_structure")
    assert v[("Ensemble.score", "aggregation")] == ("SUPPORTED", "iteration")


DELEGATION = '''
def _require(value):
    if not value:
        raise ValueError("missing")

def _always_ok(value):
    return True

def _remote(client, value):
    return client.check(value)

def validate_present(value):
    """Validate the value."""
    _require(value)
    return True

def validate_shallow(value):
    """Validate the value."""
    _always_ok(value)
    return True

def validate_remote(client, value):
    """Validate the value."""
    _remote(client, value)
    return True

def _d4(v):
    if not v:
        raise ValueError(v)

def _d3(v):
    _d4(v)

def _d2(v):
    _d3(v)

def _d1(v):
    _d2(v)

def validate_deep(v):
    """Validate the value."""
    _d1(v)
    return True
'''


def test_closed_callees_are_judged_by_the_same_rule():
    v = _verdicts(DELEGATION)
    assert v[("validate_present", "validation")] == ("DELEGATED_IN_MODULE", "closed_callee")
    # a callee that keeps no promise either does not overturn the judgment
    assert v[("validate_shallow", "validation")] == ("CONTRADICTED", "single_outcome")
    assert v[("validate_remote", "validation")] == ("UNDECIDED", "closed_callee_undecided")
    # past the depth bound the chain is open, not assumed empty
    assert v[("validate_deep", "validation")] == ("UNDECIDED", "closed_callee_undecided")


def test_coverage_keeps_states_reasons_and_failures_apart(monkeypatch):
    source = (
        CONTRADICTED
        + '''
def get_with_retry(client):
    """GET with up to five retries."""
    return client.get()
'''
    )
    result = judge_claims(ast.parse(source), False)
    cov = result.coverage()
    assert cov["extracted_claims"] == 8 and cov["contradicted"] == 7
    assert cov["not_evaluated"] == {"phase2": 1}
    assert cov["unmeasured"] == 0 and cov["provided_elsewhere"] == 0
    assert cov["by_kind"]["validation"]["contradicted"] == 2

    def broken(*args):
        raise RuntimeError("channel failure")

    monkeypatch.setitem(claim_judge.RULES, "validation", broken)
    failed = judge_claims(ast.parse(source), False).coverage()
    # a channel failure is UNMEASURED, never UNDECIDED
    assert failed["unmeasured"] == 2 and failed["undecided"] == 0


@pytest.mark.parametrize("is_test", [True, None])
def test_no_claim_is_judged_outside_product_code(is_test):
    result = judge_claims(ast.parse(CONTRADICTED), is_test)
    assert result.verdicts == [] and result.coverage()["extracted_claims"] == 0


# One control per branch: each source isolates the rule it names.
BRANCH_CASES = {
    "shadowed_len_is_an_open_call": (
        '''
len = lambda x: 3
def explain(model, features):
    """Attribute the prediction to each feature with SHAP values."""
    return {f"f{i}": 0.0 for i in range(len(features))}
''',
        "explain",
        "computed_result",
        ("UNDECIDED", "open_call"),
    ),
    "rebound_import_has_no_origin": (
        '''
import threading
threading = object()
def upload_threads(client, paths):
    """Upload the files in parallel."""
    threads = [threading.Thread(target=client.put, args=(p,)) for p in paths]
    for t in threads:
        t.start()
''',
        "upload_threads",
        "parallel",
        ("UNDECIDED", "open_call"),
    ),
    "dict_key_from_input_is_not_literal": (
        '''
def score_for(name):
    """Compute the score for the name."""
    return {name: 0.0}
''',
        "score_for",
        "computed_result",
        ("UNDECIDED", "no_proof"),
    ),
    "closed_result_returned_is_not_an_input_read": (
        '''
def _always_ok(value):
    return True
def validate_wrapped(value):
    """Validate the value."""
    return _always_ok(value)
''',
        "validate_wrapped",
        "validation",
        ("CONTRADICTED", "single_outcome"),
    ),
    "state_store_is_another_way_out": (
        '''
class Totals:
    def compute_total(self, items):
        """Compute the total of the items."""
        self.total = 5
        return 0
''',
        "Totals.compute_total",
        "computed_result",
        ("UNDECIDED", "stores_state"),
    ),
    "falling_through_is_an_outcome": (
        '''
def validate_soft(value):
    """Validate the value."""
    if not value:
        return False
''',
        "validate_soft",
        "validation",
        ("SUPPORTED", "distinct_outcomes"),
    ),
    "falling_through_is_no_value_return": (
        '''
def compute_maybe(x):
    """Compute the value of x."""
    if x:
        return 0
''',
        "compute_maybe",
        "computed_result",
        ("UNDECIDED", "no_value_return"),
    ),
    "rebound_parameter_is_not_declared_str": (
        '''
def lookup(name):
    return name
def reject_unknown(name: str):
    """Reject names outside the list."""
    name = lookup(name)
    return name.strip()
''',
        "reject_unknown",
        "rejection",
        ("UNDECIDED", "open_call"),
    ),
    "two_level_delegation": (
        '''
def _require(value):
    if not value:
        raise ValueError(value)
def _mid(value):
    _require(value)
def validate_chain(value):
    """Validate the value."""
    _mid(value)
    return True
''',
        "validate_chain",
        "validation",
        ("DELEGATED_IN_MODULE", "closed_callee"),
    ),
    "declared_str_call_as_statement": (
        '''
def reject_spaces(name: str):
    """Reject names with spaces."""
    name.strip()
    return True
''',
        "reject_spaces",
        "rejection",
        ("UNDECIDED", "declared_str_only"),
    ),
    "strip_with_a_variable_argument": (
        '''
def reject_chars(name: str, chars):
    """Reject names with these characters."""
    return name.strip(chars)
''',
        "reject_chars",
        "rejection",
        ("UNDECIDED", "open_call"),
    ),
    "input_returned_is_an_outcome": (
        '''
def validate_positive(value):
    """Validate the value."""
    if value < 0:
        return None
    return value
''',
        "validate_positive",
        "validation",
        ("SUPPORTED", "distinct_outcomes"),
    ),
    "open_call_return_among_constants": (
        '''
def validate_mixed(client, value):
    """Validate the value."""
    if value is None:
        return False
    if value == "":
        return True
    return client.check(value)
''',
        "validate_mixed",
        "validation",
        ("UNDECIDED", "open_call"),
    ),
    "generator_validator": (
        '''
def validate_items(items):
    """Validate the items."""
    for item in items:
        yield item
''',
        "validate_items",
        "validation",
        ("UNDECIDED", "generator"),
    ),
    "live_io_by_origin": (
        '''
import requests
URL = "https://example.invalid/rates"
def fetch_live_prices():
    """Fetch live prices from the exchange."""
    return requests.get(URL).json()
''',
        "fetch_live_prices",
        "live_data",
        ("SUPPORTED", "io_call_by_origin"),
    ),
    "live_without_io": (
        '''
def fetch_live_scaled(rate):
    """Fetch live rates scaled by two."""
    return rate * 2
''',
        "fetch_live_scaled",
        "live_data",
        ("UNDECIDED", "no_io_proof"),
    ),
    "reduction": (
        '''
class Pool:
    def mean(self):
        """Mean of the member scores."""
        return sum(self.scores) / len(self.scores)
''',
        "Pool.mean",
        "aggregation",
        ("SUPPORTED", "reduction"),
    ),
    "element_call_beside_another_open_call": (
        '''
class Ens:
    def predict(self, x):
        """Weighted mean of the member models' scores."""
        record(x)
        return self.models[0].predict(x)
''',
        "Ens.predict",
        "aggregation",
        ("UNDECIDED", "open_call"),
    ),
    "collection_read_another_way": (
        '''
class Ens:
    def score(self):
        """Mean of the member scores."""
        everything = self.scores
        return self.scores[0]
''',
        "Ens.score",
        "aggregation",
        ("UNDECIDED", "no_proof"),
    ),
    "yield_from_call": (
        '''
class Pages:
    def fetch_all(self):
        """Fetch every page of the collection."""
        yield from self.client.pages()
''',
        "Pages.fetch_all",
        "pagination",
        ("SUPPORTED", "yield_from_call"),
    ),
    "recursion": (
        '''
class Walker:
    def get(self, url):
        return self.session.get(url)

    def fetch_all(self, url):
        """Fetch every page of the collection."""
        page = self.get(url)
        if page.next:
            return [page] + self.fetch_all(page.next)
        return [page]
''',
        "Walker.fetch_all",
        "pagination",
        ("SUPPORTED", "recursion"),
    ),
    "single_request_by_origin": (
        '''
import requests
def list_everything(url):
    """Fetch every page of the collection."""
    return requests.get(url)
''',
        "list_everything",
        "pagination",
        ("CONTRADICTED", "single_request"),
    ),
    "runner_called_with_work": (
        '''
from joblib import Parallel, delayed
def run_all(work, items):
    """Run the work in parallel."""
    return Parallel(n_jobs=4)(delayed(work)(i) for i in items)
''',
        "run_all",
        "parallel",
        ("SUPPORTED", "concurrency_structure"),
    ),
    "thread_given_no_work": (
        '''
import threading
def run_jobs(client, jobs):
    """Run the jobs in parallel."""
    threading.Thread().start()
    return [client.run(j) for j in jobs]
''',
        "run_jobs",
        "parallel",
        ("UNDECIDED", "open_call"),
    ),
    # H3-F06: a Thread or Process runs only once started; built and handed
    # back, the caller decides, so the claim is not proven here
    "threads_built_never_started": (
        '''
import threading
def upload_threads(client, paths):
    """Upload the files in parallel."""
    threads = [threading.Thread(target=client.put, args=(p,)) for p in paths]
    return threads
''',
        "upload_threads",
        "parallel",
        ("UNDECIDED", "open_call"),
    ),
    "process_built_never_started": (
        '''
import multiprocessing
def run_jobs(client, jobs):
    """Run the jobs in parallel."""
    procs = [multiprocessing.Process(target=client.run, args=(j,)) for j in jobs]
    for p in procs:
        p.join()
''',
        "run_jobs",
        "parallel",
        ("UNDECIDED", "open_call"),
    ),
    "start_called_on_another_name": (
        '''
import threading
def upload_one(client, path, other):
    """Upload the file in parallel."""
    t = threading.Thread(target=client.put, args=(path,))
    other.start()
    return t
''',
        "upload_one",
        "parallel",
        ("UNDECIDED", "open_call"),
    ),
    "thread_started_by_name": (
        '''
import threading
def upload_one(client, path):
    """Upload the file in parallel."""
    t = threading.Thread(target=client.put, args=(path,))
    t.start()
    t.join()
''',
        "upload_one",
        "parallel",
        ("SUPPORTED", "concurrency_structure"),
    ),
    "thread_started_chained": (
        '''
import threading
def upload_one(client, path):
    """Upload the file in parallel."""
    threading.Thread(target=client.put, args=(path,)).start()
''',
        "upload_one",
        "parallel",
        ("SUPPORTED", "concurrency_structure"),
    ),
    # the caller may run several of these coroutines at once
    "async_without_calls": (
        '''
async def total_async(values):
    """Sum the values in parallel."""
    total = 0
    for v in values:
        total += v
    return total
''',
        "total_async",
        "parallel",
        ("UNDECIDED", "async"),
    ),
    "attribute_read_may_run_anything": (
        '''
class Summer:
    def total(self):
        """Sum the values in parallel."""
        total = 0
        for v in self.values:
            total += v
        return total
''',
        "Summer.total",
        "parallel",
        ("UNDECIDED", "no_proof"),
    ),
    "rebound_staticmethod": (
        '''
staticmethod = lambda f: f
class Props:
    @staticmethod
    def size():
        """Compute the size."""
        return 0
''',
        "Props.size",
        "computed_result",
        ("UNDECIDED", "decorated"),
    ),
    # (an ABC's methods are contracts and never reach the judge)
    "neutral_base": (
        '''
from typing import Generic, TypeVar
T = TypeVar("T")
class Strict(Generic[T]):
    def compute_rate(self):
        """Compute the rate."""
        return 0.5
''',
        "Strict.compute_rate",
        "computed_result",
        ("CONTRADICTED", "literal_result"),
    ),
    "imported_base_through_a_module_base": (
        '''
from vendor import Imported
class Middle(Imported):
    pass
class Leaf(Middle):
    def compute_rate(self):
        """Compute the rate."""
        return 0.5
''',
        "Leaf.compute_rate",
        "computed_result",
        ("UNDECIDED", "imported_base"),
    ),
}


@pytest.mark.parametrize("case", sorted(BRANCH_CASES))
def test_each_branch_has_its_control(case):
    source, function, kind, expected = BRANCH_CASES[case]
    assert _verdicts(source)[(function, kind)] == expected
