"""Shared parametrization for fake and real adapter conformance cases.

Each suite calls ``implementation_params`` in ``pytest.mark.parametrize``.
The value is a zero-argument factory, so every case gets a fresh adapter.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

import pytest


def implementation_params(
    suite: str,
    fake_factory: Callable[[], Any],
    real_module: str,
    real_factory_name: str,
    dist: str,
) -> list[pytest.ParameterSet]:
    """Return ``suite[fake]`` and ``suite[real]`` parameters.

    The real parameter is skipped when its module cannot import; an adapter
    marker is retained so attribution can associate a real failure with dist.
    """
    if not suite or not dist:
        raise ValueError("suite and dist must be non-empty")
    fake = pytest.param(fake_factory, id=f"{suite}[fake]")
    marker = pytest.mark.adapter(dist)
    try:
        module = importlib.import_module(real_module)
    except ImportError as error:
        real = pytest.param(
            None,
            marks=(marker, pytest.mark.skip(reason=f"{real_module}: {error}")),
            id=f"{suite}[real]",
        )
    else:
        factory = getattr(module, real_factory_name)
        if not callable(factory):
            raise TypeError(f"{real_module}.{real_factory_name} is not callable")
        real = pytest.param(factory, marks=marker, id=f"{suite}[real]")
    return [fake, real]
