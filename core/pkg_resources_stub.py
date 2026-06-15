"""Minimal pkg_resources stub for apscheduler compatibility.

setuptools >= 82 removed pkg_resources. apscheduler uses it at import time
for version introspection only. This stub provides just enough to keep
apscheduler happy without pulling in all of setuptools.
"""
import sys
from importlib.metadata import distribution


class _DistributionStub:
    """Mimic pkg_resources Distribution.version for apscheduler."""

    def __init__(self, name: str):
        self._name = name
        self._version = distribution(name).version

    @property
    def version(self):
        return self._version


def get_distribution(name: str):
    """Return a minimal distribution object with .version attribute."""
    return _DistributionStub(name)


# Inject into sys.modules so that `import pkg_resources` resolves
sys.modules["pkg_resources"] = sys.modules[__name__]
