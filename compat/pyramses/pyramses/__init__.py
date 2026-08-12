# -*- coding: utf-8 -*-
"""Compatibility shim: ``pyramses`` is now ``stepss``.

This distribution exists so that code and notebooks written against
``pyramses`` keep running unchanged. It contains no logic of its own: every
name is the one ``stepss`` defines. It depends on ``stepss>=3.59`` and is not
revised as ``stepss`` grows, so it keeps delivering the current engine
without being updated itself.
"""

import importlib
import sys
import warnings

# Warn BEFORE importing stepss, and do not move this below the import.
# `stepss.cases` and `stepss.extractor` assign `warnings.showwarning =
# CustomWarning` at module scope, which replaces the process-wide warning
# display hook. That is exactly the hook `warnings.catch_warnings(record=True)`
# installs to capture warnings, so any warning issued after `import stepss`
# goes to RAMSES's printer instead of the caller's recorder: it reaches stderr
# but is invisible to `catch_warnings`, `pytest.warns`, and any other tooling
# that intercepts warnings. Issuing it first means this deprecation is
# delivered through whatever handler the *user* configured, which is also the
# more correct behaviour on its own merits.
warnings.warn(
    "pyramses is now stepss: pip install stepss. This compatibility package "
    "forwards to it and will not be updated.",
    DeprecationWarning,
    stacklevel=2,
)

import stepss                 # noqa: E402
from stepss import *          # noqa: F401,F403,E402

# `from stepss import *` binds only the names `stepss.__all__` lists, which is
# the classes and functions. It skips every dunder and every module-level name
# outside `__all__`. Version 3.58.1 of this shim relied on that star import
# alone and so silently dropped `__ramses_version__`, `__helios_version__`,
# `__runTimeObs__` and `__url__`: all four are documented package-level
# attributes, all four worked on pyramses 3.58, and all four raised
# AttributeError through the shim.
#
# Mirror the whole module rather than listing the names. This distribution is
# published once and not revised as `stepss` grows, so an explicit list here
# could only go stale the same way. `setdefault` leaves the names this module
# already owns (`__name__`, `__doc__`, `__file__`, `__spec__`, ...) untouched.
#
# Bind the namespace dict BEFORE the loop. `stepss` carries a submodule named
# `globals`, so the first iteration that copies it shadows the `globals()`
# builtin in this module and the next call raises TypeError.
_ns = globals()
for _name, _value in vars(stepss).items():
    _ns.setdefault(_name, _value)
del _ns, _name, _value

# Mirroring attributes does not recreate submodule *import paths*, and
# `from pyramses.globals import RAMSESError` is a documented usage (it is how
# the Nordic regression test imports it). Alias the real modules into this
# package's namespace so those imports resolve to the same objects. `scripts`
# is in the list because `ramses = pyramses.scripts.exec:run` was the old
# console script, so `from pyramses.scripts.exec import run` is a shape that
# worked before the rename.
for _sub in ('globals', 'cases', 'simulator', 'extractor', 'helios', 'scripts'):
    sys.modules[__name__ + '.' + _sub] = importlib.import_module('stepss.' + _sub)
del _sub
