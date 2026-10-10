"""Claim-source boundary A2: legal prose in the leading comments is not a claim.

A license notice says "distributed under the License"; that is not a claim that
the code is distributed. Since v3.10 "distributed" is a technical noun and not
counted at all, so the fixtures put the claim word "robust" inside the legal
prose to keep exercising the boundary. Only the leading comments (before the first code token;
a shebang or encoding cookie does not end them) are examined, paragraph by
paragraph (paragraphs are separated by blank lines). A paragraph is legal when
it carries a strong legal marker, or when it directly continues a legal
paragraph with license-notice wording ("the License", WARRANTY, "applicable
law", a licenses/ URL). The bare word "license" is not a marker, and legal text
after the first code token gets no special handling.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from slop_detector.core import SlopDetector

APACHE = (
    "# Copyright 2024 The Example Authors. All rights reserved.\n"
    "#\n"
    '# Licensed under the Apache License, Version 2.0 (the "License");\n'
    "# you may not use this file except in compliance with the License.\n"
    "# You may obtain a copy of the License at\n"
    "#\n"
    "#     http://www.apache.org/licenses/LICENSE-2.0\n"
    "#\n"
    "# Unless required by applicable law or agreed to in writing, software\n"
    '# robust under the License is robust on an "AS IS" BASIS,\n'
    "# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.\n"
)

APACHE_SPLIT = (
    '# Licensed under the Apache License, Version 2.0 (the "License");\n'
    "# you may not use this file except in compliance with the License.\n"
    "\n"
    "#     http://www.apache.org/licenses/LICENSE-2.0\n"
    "\n"
    "# Unless required by applicable law or agreed to in writing, software\n"
    '# robust under the License is robust on an "AS IS" BASIS,\n'
    "# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.\n"
)

CODE = "\n\ndef f(x):\n    return x\n"


@pytest.fixture
def root(tmp_path_factory):
    return tmp_path_factory.mktemp("proj")


def _words(root: Path, source: str) -> List[str]:
    path = root / "m.py"
    path.write_text(source, encoding="utf-8")
    analysis = SlopDetector(read_only=True).analyze_file(str(path))
    return [d["word"] for d in analysis.inflation.jargon_details]


def test_apache_notice_is_not_a_claim(root):
    assert "robust" not in _words(root, APACHE + CODE)


def test_apache_notice_split_into_paragraphs_is_not_a_claim(root):
    assert "robust" not in _words(root, APACHE_SPLIT + CODE)


def test_spdx_paragraph_is_not_a_claim(root):
    source = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# This file is robust under the Apache-2.0 license.\n" + CODE
    )
    assert "robust" not in _words(root, source)


def test_gpl_family_notice_is_not_a_claim(root):
    source = (
        "# This program is free software: you can redistribute it under the terms\n"
        "# of the GNU Affero General Public License, version 3.\n"
        "\n"
        "# This program is robust in the hope that it will be useful,\n"
        "# but WITHOUT ANY WARRANTY; without even the implied warranty of\n"
        "# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.\n" + CODE
    )
    assert "robust" not in _words(root, source)


def test_marker_split_across_lines_and_case_is_recognized(root):
    source = (
        "# licensed under the\n"
        "#   APACHE   license, version 2.0; software is\n"
        "# robust under the License on an AS IS basis.\n" + CODE
    )
    assert "robust" not in _words(root, source)


def test_shebang_and_encoding_do_not_end_the_leading_comments(root):
    source = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n" + APACHE + CODE
    assert "robust" not in _words(root, source)


def test_ordinary_top_comment_is_still_a_claim(root):
    assert "robust" in _words(root, "# A robust scheduler.\n" + CODE)


def test_bare_license_word_is_not_a_legal_marker(root):
    words = _words(root, "# License manager uses robust workers.\n" + CODE)
    assert "robust" in words


def test_description_after_a_legal_notice_is_still_a_claim(root):
    words = _words(root, APACHE + "\n# A scalable, robust scheduler.\n" + CODE)
    assert words.count("robust") == 1, words
    assert "scalable" in words


def test_comment_after_code_is_still_a_claim(root):
    source = APACHE + CODE + "\n\n# A scalable production service.\n"
    assert "scalable" in _words(root, source)


def test_legal_wording_after_code_gets_no_special_handling(root):
    source = "def f(x):\n    return x\n\n\n" + APACHE
    assert "robust" in _words(root, source)


def test_a_description_paragraph_ends_the_legal_notice(root):
    """Continuation wording only extends a notice it directly follows."""
    source = (
        APACHE + "\n# A scalable scheduler.\n\n# Jobs are robust under the License terms.\n" + CODE
    )
    assert "robust" in _words(root, source)
