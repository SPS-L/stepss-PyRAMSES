pyramses is retired: install stepss
====================================

This project was renamed. Install `stepss <https://pypi.org/project/stepss/>`_::

   pip install stepss

Then change ``import pyramses`` to ``import stepss``. The API is unchanged:
``cfg``, ``sim``, ``extractor``, ``curplot`` and ``HeliosSession`` keep their
names, and ``from pyramses.globals import X`` becomes
``from stepss.globals import X``.

``stepss`` is the same package under its current name, and it is the only one
that tracks the RAMSES and Helios engines. Installing ``pyramses`` is refused
rather than redirected silently, so that nothing keeps depending on a name that
receives no further releases.

Documentation: https://stepss.sps-lab.org/python/
