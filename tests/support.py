"""Helpers for loading adapter modules without importing vendor SDKs.

Each adapter package eagerly re-exports its full provider stack from
``__init__.py``.  That is convenient for users but would make pure mapper
tests require six proprietary SDKs.  These helpers create a lightweight
package shell and load only the module under test.
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import pkgutil
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

ADAPTERS = ("groww", "fyers", "upstox", "dhan", "angelone", "zerodha")


def load_adapter_module(adapter: str, module: str):
    """Load ``brokerkit_<adapter>.<module>`` without executing ``__init__``."""
    package_name = f"brokerkit_{adapter}"
    module_name = f"{package_name}.{module}"
    package_dir = REPO_ROOT / "packages" / f"brokerkit-{adapter}" / package_name
    source = package_dir / f"{module}.py"

    if module_name in sys.modules:
        return sys.modules[module_name]

    package = sys.modules.get(package_name)
    if package is None:
        # A shell package: enough for the module's own ``from brokerkit_<a>
        # import ...`` relative imports to resolve, but WITHOUT executing the
        # real __init__ (which would pull in the full vendor-SDK provider
        # stack). Tagged so a later full import (import_adapter) can tell it
        # apart from a genuinely-imported package and replace it.
        package = types.ModuleType(package_name)
        package.__path__ = [str(package_dir)]
        package.__brokerkit_shell__ = True
        sys.modules[package_name] = package

    spec = importlib.util.spec_from_file_location(module_name, source)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def import_adapter(adapter: str):
    """Import the full ``brokerkit_<adapter>`` package (executes ``__init__``,
    which re-exports the whole provider stack).

    Unlike ``load_adapter_module`` this needs every vendor SDK the adapter
    imports at module scope. When one is genuinely missing (no single venv
    holds all six — groww/fyers can't coexist), the caller's test is skipped
    rather than failed; a *brokerkit* import error is re-raised as the real
    bug it is."""
    name = f"brokerkit_{adapter}"
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__brokerkit_shell__", False):
        # A pure mapper test left a partial shell (see load_adapter_module).
        # Drop it and every submodule loaded under it so import_module runs
        # the real __init__ instead of returning the __init__-less shell.
        for mod in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
            del sys.modules[mod]
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        missing = (exc.name or "").split(".")[0]
        if missing.startswith("brokerkit"):
            raise
        pytest.skip(f"{adapter}: vendor SDK {missing!r} not installed")


def iter_adapter_modules(adapter: str):
    """The adapter package plus each of its submodules. Adapters are flat
    (no subpackages), so a single ``iter_modules`` pass covers them."""
    package = import_adapter(adapter)
    yield package
    for info in pkgutil.iter_modules(package.__path__):
        yield importlib.import_module(f"{package.__name__}.{info.name}")
