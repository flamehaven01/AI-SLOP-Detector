"""H3-1: behavioral promises extracted from docstrings (no judgment of the body)."""

import ast

from slop_detector.claims import extract_claims

PROMISES = '''
class PartnerClient:
    def list_all(self, path):
        """Fetch every page of a paginated collection."""
        return self.get(path).get("items", [])

    def iter_pages(self, path):
        """Yield every page of a paginated collection, following next links."""
        yield from ()

    def post_with_retry(self, path, body):
        """POST with up to five retries and exponential backoff on 5xx responses."""
        return self.session.post(path, json=body)

    def fetch_exchange_rates(self, base="USD"):
        """Fetch live exchange rates for the base currency."""
        return {"EUR": 0.92}

def upload_many(client, paths, bucket):
    """Upload files in parallel and return their URLs in input order."""
    return [client.put(bucket, p) for p in paths]

class EnsembleModel:
    def predict(self, features):
        """Weighted mean of the member models' scores."""
        return self.models[0].predict(features)

def sanitize_username(name):
    """Strip whitespace and reject characters outside [a-z0-9_.-]."""
    return name.strip()

def explain(model, features):
    """Attribute the prediction to each feature with SHAP values."""
    return {}

class MetadataCache:
    def get(self, key):
        """Return cached metadata for key, fetching it when missing or expired."""
        return self.client.fetch(key)

def validate_root_access(client):
    """Validate ROOT access against a read-only admin endpoint."""
    return client.check()
'''

NOT_PROMISES = '''
def first_page(client):
    """Fetch the first page only, never following next links."""
    return client.get()

def is_retryable(error):
    """Return True for Windows rename failures a retry might clear."""
    return True

def all_fetched(state):
    """Return True when every page of the results was fetched."""
    return state.done

def cache_description(self, text):
    """Update the cached description (from the most recent HELLO)."""
    self.description = text

def register_cda_section_config(name):
    """Register a validation model for a CDA section configuration."""
    return name

def list_via_client(client):
    """Fetch every page of the collection by delegating to the client's paginator."""
    return client.paginate()

def describe_load():
    """Test that list_all fetches every page of the collection."""
    return None

def upload(client, paths):
    """Upload the files. Runs in parallel through the worker pool."""
    return paths

def parallel_weight_loader(param, weight):
    """Parallel Linear weight loader."""
    return weight

def save_caches(store):
    """Save all caches to disk."""
    return store

def latest_checkpoint(store):
    """Get the latest checkpoint for a given workflow name."""
    return store.last()

def clear_defs():
    """Drop memoized get_tool_definitions() results."""
    return None

def save_merged(records):
    """Used in parallel by save_all to write out the merged records."""
    return records

def export_space(space):
    """Export all pages in this space to Markdown."""
    return space

def shutdown_phase(manager):
    """Get the current shutdown phase."""
    return manager.phase

def evict(cache):
    """Free the engines + caches held by a cached inference before dropping it."""
    cache.clear()

def format_analyzer(doc):
    """Analyze document format - runs as an activity in parallel with word_count."""
    return doc

def fetch_with_config(client):
    """Fetch every page of the results with the pagination config."""
    return client.get()

def configure_retry(adapter):
    """Configure the adapter with exponential backoff."""
    adapter.retries = 5
'''

OTHER_SCOPES = '''
def outer(items):
    """Return the items unchanged."""
    def inner(pages):
        """Fetch every page of the collection."""
        return pages
    return items

def chinese(path):
    """检查文件大小是否在可接受的范围内。"""
    return path

def no_doc(x):
    return x

class Base:
    def fetch_all(self):
        """Fetch every page of the collection."""
        raise NotImplementedError

import abc

class Source(abc.ABC):
    @abc.abstractmethod
    def fetch_all(self):
        """Fetch every page of the collection."""
        return []
'''


def _claims(source, is_test=False):
    return extract_claims(ast.parse(source), is_test)


def test_a_promise_of_the_function_s_own_mechanism_is_extracted():
    found = {(c.function, c.kind) for c in _claims(PROMISES).claims}
    assert found >= {
        ("PartnerClient.list_all", "pagination"),
        ("PartnerClient.iter_pages", "pagination"),
        ("PartnerClient.post_with_retry", "retry"),
        ("PartnerClient.fetch_exchange_rates", "live_data"),
        ("upload_many", "parallel"),
        ("EnsembleModel.predict", "aggregation"),
        ("sanitize_username", "rejection"),
        ("explain", "computed_result"),
        ("MetadataCache.get", "cache"),
        ("validate_root_access", "validation"),
    }
    claim = next(c for c in _claims(PROMISES).claims if c.function == "PartnerClient.list_all")
    record = claim.to_dict()
    assert record["source"]["text"] == "Fetch every page of a paginated collection."
    assert record["source"]["line"] == 4  # the docstring's line in the source
    assert record["extraction"] == {
        "state": "EXTRACTED", "scope": "FIRST_SUMMARY_SENTENCE", "confidence_basis": "EXPLICIT_BEHAVIORAL_PROMISE",
    }
    assert record["mechanism"] == {"state": "NOT_EVALUATED"}


def test_a_topic_an_object_a_negation_or_another_component_is_not_a_promise():
    result = _claims(NOT_PROMISES)
    assert result.claims == []
    # each excluded match is counted by its reason, never dropped silently
    assert set(result.excluded) >= {
        "negated", "predicate_about_mechanism", "attributed_elsewhere", "test_description", "mechanism_as_object",
    }
    # a promise only in the second sentence is out of scope, not absent
    assert result.out_of_scope["later_sentences_not_analyzed"] >= 1


def test_functions_left_out_are_counted_by_reason():
    result = _claims(OTHER_SCOPES)
    # a nested function's promise is its own, under its own name
    assert [(c.function, c.kind) for c in result.claims] == [("outer.inner", "pagination")]
    assert result.not_analyzed == {"non_english": 1, "no_docstring": 1, "stub_body": 1, "contract_or_abstract": 1}
    coverage = result.coverage()
    assert coverage["functions"] == 6 and coverage["eligible_functions"] == 2
    assert coverage["functions_with_claims"] == 1 and coverage["extracted_claims"] == 1


def test_test_code_and_unknown_test_status_are_not_analyzed():
    in_tests = _claims(PROMISES, is_test=True)
    assert in_tests.claims == [] and in_tests.not_analyzed == {"test_code": 10}
    unknown = _claims(PROMISES, is_test=None)
    assert unknown.claims == [] and unknown.not_analyzed == {"test_status_unknown": 10}
