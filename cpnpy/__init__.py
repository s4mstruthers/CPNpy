"""``cpnpy``: the old name of :mod:`openprocess` (CPNpy, up to 0.6).

``import cpnpy`` and ``from cpnpy.flow import box`` keep working: every
``cpnpy.*`` module is the ``openprocess.*`` module under its old name, so a
box file or an exercise pack written for CPNpy runs unchanged.  New code
should import ``openprocess``; this shim warns once per process.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
import warnings

import openprocess as _new

__version__ = _new.__version__
__all__ = list(getattr(_new, "__all__", []))


class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """``cpnpy.x.y`` resolves to the already-imported ``openprocess.x.y``."""

    def find_spec(self, name, path=None, target=None):
        if name == __name__ or not name.startswith(__name__ + "."):
            return None
        return importlib.machinery.ModuleSpec(name, self)

    def create_module(self, spec):
        module = importlib.import_module(_new.__name__ + spec.name[len(__name__):])
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module):
        pass


sys.meta_path.insert(0, _Alias())
warnings.warn("cpnpy is now openprocess: import openprocess instead (cpnpy keeps working for now)",
              DeprecationWarning, stacklevel=2)


def __getattr__(name):
    return getattr(_new, name)
