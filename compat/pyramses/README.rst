pyramses is now stepss
======================

This package is a compatibility shim. The project it used to hold was renamed
to `stepss <https://pypi.org/project/stepss/>`_.

Install the real package::

   pip install stepss

Then change ``import pyramses`` to ``import stepss``. The API is otherwise
identical: ``cfg``, ``sim``, ``extractor``, ``curplot``, ``HeliosSession`` and
the rest keep their names.

Installing ``pyramses`` still works and still gives you the current engine: it
pulls in ``stepss`` and forwards every name to it, including the package-level
attributes such as ``__ramses_version__`` and ``__runTimeObs__``, and submodule
imports such as ``from pyramses.globals import RAMSESError``. It emits a
``DeprecationWarning`` on import, and it tracks no further ``stepss`` releases.

Upgrade past ``3.58.1`` if you are on it: that first shim forwarded only the
classes and functions, so the package-level attributes raised
``AttributeError``.

Documentation: https://stepss.sps-lab.org/python/
