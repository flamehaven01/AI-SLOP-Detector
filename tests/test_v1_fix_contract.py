"""The four changes of benchmarks/holdout/FIX_CONTRACT.md, from hold-out v1 shapes.

Fixtures follow the shapes of the v1 evidence (H124/H147/H160/H162, H149, H123,
H119, H017); they are written here, not copied from the third-party source.
Each positive has a genuine neighbour that must stay clean.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector


def _found(tmp_path: Path, source: str, pattern: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted((i.line, i.message) for i in result.pattern_issues if i.pattern_id == pattern)


# 1. Constant success report (return_constant_stub) ---------------------------


def test_success_report_built_from_literals_is_reported(tmp_path):
    source = """
    class ModeReport:
        def __init__(self, mode, ok, detail):
            self.mode, self.ok, self.detail = mode, ok, detail

    def run_tunnel_mode(target: str) -> ModeReport:
        return ModeReport("tunnel", True, f"Tunnel placeholder prepared for {target}")
    """
    found = _found(tmp_path, source, "return_constant_stub")
    assert [line for line, _ in found] == [6]
    assert "ModeReport" in found[0][1] and "True" in found[0][1]


def test_healthy_status_without_a_check_is_reported(tmp_path):
    source = '''
    import enum

    class Health(enum.Enum):
        HEALTHY = "healthy"
        DOWN = "down"

    class Checker:
        def _check_queue(self):
            """Check the queue backend."""
            return Report(name="queue", status=Health.HEALTHY, message="queue reachable")
    '''
    found = _found(tmp_path, source, "return_constant_stub")
    assert [line for line, _ in found] == [9]
    assert "HEALTHY" in found[0][1]


def test_report_built_from_measured_values_is_not_reported(tmp_path):
    source = """
    def run_tunnel_mode(target: str):
        ok = connect(target)
        return ModeReport("tunnel", ok, f"connected to {target}")

    def make_config():
        return Config(name="default", retries=3)

    def default_options():
        return Options(verbose=True, retries=3)

    def enter_owned_context():
        return _OWNED.set(True)
    """
    assert _found(tmp_path, source, "return_constant_stub") == []


# 2. Swallowed failure, then a placeholder value (failure_as_success) ---------


def test_swallowed_failure_then_fabricated_value_is_reported(tmp_path):
    source = """
    import sys

    def total_memory_gb() -> float:
        try:
            if sys.platform == "linux":
                return read_meminfo() / 1024
        except Exception:
            pass
        return 8 * 1.0  # placeholder estimate
    """
    found = _found(tmp_path, source, "failure_as_success")
    assert [line for line, _ in found] == [8]
    assert "8 * 1.0" in found[0][1] and "placeholder" in found[0][1]


def test_swallowed_failure_then_chosen_default_is_not_reported(tmp_path):
    source = """
    def resolve_region(config):
        try:
            return config["aws"]["region"]
        except Exception:
            pass
        return "us-east-1"
    """
    assert _found(tmp_path, source, "failure_as_success") == []


def test_swallowed_failure_then_neutral_value_is_not_reported(tmp_path):
    source = """
    def total_memory_gb() -> float:
        try:
            return read_meminfo() / 1024
        except Exception:
            pass
        return 0.0  # placeholder: unknown

    def parse_port(text):
        try:
            return int(text)
        except Exception:
            pass
        return None  # placeholder
    """
    assert _found(tmp_path, source, "failure_as_success") == []


# 3. Documented parameter never read (ignored_parameter) ----------------------


def test_documented_parameter_its_siblings_read_is_reported_on_an_outside_base(tmp_path):
    source = '''
    import torch.nn as nn

    class Encoder(nn.Module):
        def mask_for(self, namespace):
            return self.masks[namespace]

        def forward(self, namespace):
            """Encode the graph.

            Args:
                namespace: which sub-graph to encode ("bp", "mf" or "all")
            """
            # namespace-aware pooling could go here later
            return self.reduce(self.layers(self.terms))
    '''
    found = _found(tmp_path, source, "ignored_parameter")
    assert [line for line, _ in found] == [8]
    assert "'namespace'" in found[0][1]


def test_documented_hook_argument_of_an_outside_base_is_not_reported(tmp_path):
    source = '''
    import lightning as L

    class Module(L.LightningModule):
        def predict_step(self, batch, batch_idx, dataloader_idx=0):
            """Args:
                batch_idx: index of the batch
                dataloader_idx: index of the dataloader
            """
            return self(batch)
    '''
    assert _found(tmp_path, source, "ignored_parameter") == []


def test_documented_argument_every_sibling_ignores_is_not_reported(tmp_path):
    source = '''
    class Steps:
        def training_step(self, batch, batch_idx):
            """Args:
                batch_idx: index of the batch
            """
            return self.loss(batch)

        def validation_step(self, batch, batch_idx):
            return self.loss(batch)
    '''
    assert _found(tmp_path, source, "ignored_parameter") == []


def test_annotated_tool_argument_is_not_reported(tmp_path):
    source = '''
    from typing import Annotated

    async def article_details(call_benefit: Annotated[str, "why this is called"], pmid):
        """Fetch an article.

        Parameters:
        - call_benefit: why this function is called
        - pmid: the article id
        """
        return await fetch(pmid)
    '''
    assert _found(tmp_path, source, "ignored_parameter") == []


def test_undocumented_parameter_of_an_outside_base_is_not_reported(tmp_path):
    source = '''
    import torch.nn as nn

    class Encoder(nn.Module):
        def forward(self, x, mask):
            """Encode the input."""
            return self.layers(x)
    '''
    assert _found(tmp_path, source, "ignored_parameter") == []


def test_documented_parameter_that_is_read_is_not_reported(tmp_path):
    source = '''
    def encode(terms, namespace):
        """Encode terms.

        Args:
            namespace: which sub-graph to encode
        """
        return [t for t in terms if t.space == namespace]
    '''
    assert _found(tmp_path, source, "ignored_parameter") == []


# 4. Two false alarms ----------------------------------------------------------


def test_dependency_injected_parameters_are_not_reported(tmp_path):
    source = """
    from fastapi import Depends

    async def update_settings(body, session=Depends(get_session), user=Depends(require_admin)):
        return await save(body)
    """
    assert _found(tmp_path, source, "ignored_parameter") == []


def test_a_plain_unused_option_is_still_reported(tmp_path):
    source = """
    async def update_settings(body, retries=3):
        return await save(body)
    """
    assert [line for line, _ in _found(tmp_path, source, "ignored_parameter")] == [2]


def test_empty_init_is_not_a_placeholder(tmp_path):
    source = """
    class Retriever:
        def __init__(self):
            pass
    """
    assert _found(tmp_path, source, "pass_placeholder") == []


def test_empty_method_is_still_a_placeholder(tmp_path):
    source = """
    class Retriever:
        def retrieve(self, query):
            pass
    """
    assert [line for line, _ in _found(tmp_path, source, "pass_placeholder")] == [3]


def test_documented_parameter_in_a_sibling_family_is_reported(tmp_path):
    source = '''
    class Encoder:
        def mask_for(self, namespace):
            return self.masks[namespace]

        def encode(self, namespace):
            """Encode the graph.

            Args:
                namespace: which sub-graph to encode
            """
            return self.reduce(self.terms)
    '''
    assert [line for line, _ in _found(tmp_path, source, "ignored_parameter")] == [6]


def test_undocumented_parameter_in_a_sibling_family_is_not_reported(tmp_path):
    source = """
    class Handlers:
        def on_open(self, event, force=False):
            return self.log(event, force)

        def on_close(self, event, force=False):
            return self.flush()
    """
    assert _found(tmp_path, source, "ignored_parameter") == []
