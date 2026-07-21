"""get_type_hints sweep over every adapter.

Regression guard for a latent annotation bug this project shipped: a provider
method named ``list`` shadowed the builtin used in sibling annotations
(``ZerodhaGtt.list`` — since renamed to ``list_triggers``). Under Python 3.14's
PEP 649 deferred annotations it was invisible until something introspected the
hints. Calling ``get_type_hints`` on every class, function and method keeps
that class of bug from coming back on any adapter.
"""

import inspect
import typing

import pytest

from tests.support import ADAPTERS, iter_adapter_modules


def _hintable_objects(adapter: str):
    """(label, object) for every class, function and method *defined* in the
    adapter (imported names are skipped via the __module__ check)."""
    for module in iter_adapter_modules(adapter):
        modname = module.__name__
        for obj in vars(module).values():
            if isinstance(obj, type) and obj.__module__ == modname:
                yield f"{modname}.{obj.__qualname__}", obj
                for attr, member in vars(obj).items():
                    func = member.__func__ if isinstance(member, (classmethod, staticmethod)) else member
                    if inspect.isfunction(func):
                        yield f"{modname}.{obj.__qualname__}.{attr}", func
            elif inspect.isfunction(obj) and obj.__module__ == modname:
                yield f"{modname}.{obj.__qualname__}", obj


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_type_hints_resolve_for_every_definition(adapter):
    failures: dict[str, str] = {}
    checked = 0
    for label, obj in _hintable_objects(adapter):
        checked += 1
        try:
            typing.get_type_hints(obj)
        except Exception as exc:  # noqa: BLE001 — any failure is the finding
            failures[label] = f"{type(exc).__name__}: {exc}"
    assert checked > 0, f"{adapter}: swept no definitions — walker is broken"
    assert not failures, f"{adapter}: unresolvable type hints:\n" + "\n".join(
        f"  {k} -> {v}" for k, v in failures.items()
    )
