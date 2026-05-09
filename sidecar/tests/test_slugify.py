import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from slugify import slugify

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "slugify_cases.json")

with open(FIXTURE_PATH, encoding="utf-8") as _f:
    _CASES = json.load(_f)


@pytest.mark.parametrize("case", _CASES, ids=[c["input"][:30] or "(empty)" for c in _CASES])
def test_slugify_table(case):
    assert slugify(case["input"]) == case["expected"]
