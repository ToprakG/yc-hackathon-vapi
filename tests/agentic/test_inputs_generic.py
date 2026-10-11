"""Generic input rules of the agentic builder: the tool API must declare operations; no fallback API."""
import json

import pytest

from builder.common.io import InputError, split_inputs


def test_an_api_without_operations_is_refused(tmp_path):
    (tmp_path / "b.md").write_text("brief")
    (tmp_path / "api.json").write_text(json.dumps({"openapi": "3.0.0", "paths": {}}))
    with pytest.raises(InputError, match="no operations"):
        split_inputs([tmp_path / "b.md", tmp_path / "api.json"])


def test_an_api_with_operations_is_accepted(tmp_path):
    (tmp_path / "b.md").write_text("brief")
    (tmp_path / "api.json").write_text(json.dumps({"openapi": "3.0.0", "paths": {"/x/do_it": {}}}))
    briefs, api = split_inputs([tmp_path / "b.md", tmp_path / "api.json"])
    assert api.name == "api.json" and len(briefs) == 1
