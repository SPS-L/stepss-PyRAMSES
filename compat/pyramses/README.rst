This package has been decommissioned
=====================================

Install `stepss <https://pypi.org/project/stepss/>`_ instead::

   pip install stepss

``stepss`` is this package under its current name, and the only one that tracks
the RAMSES and Helios engines. Change ``import pyramses`` to ``import stepss``:
``cfg``, ``sim``, ``extractor``, ``curplot`` and ``HeliosSession`` keep their
names, and ``from pyramses.globals import X`` becomes
``from stepss.globals import X``.

This project carries a single release, which exists only to say so. Installing
it fails rather than redirecting silently, so that nothing keeps depending on a
name that receives no further releases.

Documentation: https://stepss.sps-lab.org/python/
