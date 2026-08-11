# -*- coding: utf-8 -*-
"""Compatibility shim: ``pyramses`` is now ``stepss``.

This distribution exists so that code and notebooks written against
``pyramses`` keep running unchanged. It contains no logic of its own: every
name is the one ``stepss`` defines. It depends on ``stepss>=3.58.1`` and is
published once, so it keeps delivering the current engine without ever
being updated itself.
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
from stepss import __all__, __version__   # noqa: E402

# `from stepss import *` binds the public API but does not recreate submodule
# paths, and `from pyramses.globals import RAMSESError` is a documented usage
# (it is how the Nordic regression test imports it). Alias the real modules
# into this package's namespace so those imports resolve to the same objects.
for _sub in ('globals', 'cases', 'simulator', 'extractor', 'helios'):
    sys.modules[__name__ + '.' + _sub] = importlib.import_module('stepss.' + _sub)
del _sub
