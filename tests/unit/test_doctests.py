"""Run the ``>>>`` examples in every module docstring of the package."""

import doctest
import importlib
import pkgutil
from types import ModuleType

import pytest

import alpaca_gatherer


def _modules() -> list[str]:
    return sorted(
        info.name
        for info in pkgutil.walk_packages(alpaca_gatherer.__path__, "alpaca_gatherer.")
        if info.name != "alpaca_gatherer.main"
    )


@pytest.mark.parametrize("name", _modules())
def test_doctests(name: str) -> None:
    module: ModuleType = importlib.import_module(name)
    result = doctest.testmod(module, optionflags=doctest.ELLIPSIS)
    assert result.failed == 0, f"{result.failed} doctest(s) failed in {name}"
