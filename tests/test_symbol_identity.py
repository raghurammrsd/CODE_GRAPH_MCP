from __future__ import annotations

from codegraph.indexing.models import build_canonical_id, normalize_module
from codegraph.indexing.parser import parse


def test_normalize_module_variants() -> None:
    """Verify module normalization strips source extensions, leading slashes, and index files."""
    assert normalize_module("./src/auth/service.py") == "src.auth.service"
    assert normalize_module("src/auth/service.pyi") == "src.auth.service"
    assert normalize_module("components/button.tsx") == "components.button"
    assert normalize_module("types/index.d.ts") == "types"
    assert normalize_module("src/auth/__init__.py") == "src.auth"
    assert normalize_module("lib/utils/index.ts") == "lib.utils"
    assert normalize_module("lib\\utils\\index.js") == "lib.utils"


def test_build_canonical_id_rules() -> None:
    """Verify deterministic canonical ID construction from module, scope, and name."""
    assert build_canonical_id("src.auth", "", "login") == "src.auth.login"
    assert build_canonical_id("src.auth", "AuthService", "login") == "src.auth.AuthService.login"
    assert build_canonical_id("src.auth", "AuthService.helper", "inner") == "src.auth.AuthService.helper.inner"


def test_canonical_id_stability_across_line_shifts() -> None:
    """Verify that inserting lines or comments does not alter symbol canonical ID."""
    code_v1 = """
class DataPipeline:
    def execute(self, payload):
        return payload
"""

    code_v2 = """
# Adding license and extensive documentation
# Multiple comment lines
# to shift the line numbers

import time
import sys



class DataPipeline:
    \"\"\"Docstring with several lines
    explaining DataPipeline.
    \"\"\"
    def execute(self, payload):
        return payload
"""

    result_v1 = parse(code_v1, "python", "src/pipeline.py")
    result_v2 = parse(code_v2, "python", "src/pipeline.py")

    v1_syms = {s.name: s for s in result_v1.symbols}
    v2_syms = {s.name: s for s in result_v2.symbols}

    assert v1_syms["DataPipeline"].canonical_id == v2_syms["DataPipeline"].canonical_id
    assert v1_syms["execute"].canonical_id == v2_syms["execute"].canonical_id
    assert v1_syms["execute"].canonical_id == "src.pipeline.DataPipeline.execute"

    # Line numbers changed, but canonical ID is invariant
    assert v1_syms["execute"].start_line != v2_syms["execute"].start_line


def test_duplicate_symbol_disambiguation_across_modules() -> None:
    """Verify identically named symbols in different files maintain distinct identities."""
    code_auth = """
def login(username, password):
    return True
"""
    code_api = """
def login(req):
    return {"status": 200}
"""
    auth_result = parse(code_auth, "python", "auth/service.py")
    api_result = parse(code_api, "python", "api/views.py")

    auth_login = next(s for s in auth_result.symbols if s.name == "login")
    api_login = next(s for s in api_result.symbols if s.name == "login")

    assert auth_login.canonical_id == "auth.service.login"
    assert api_login.canonical_id == "api.views.login"
    assert auth_login.canonical_id != api_login.canonical_id
