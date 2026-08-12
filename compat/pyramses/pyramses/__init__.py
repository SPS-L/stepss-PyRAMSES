# -*- coding: utf-8 -*-
"""Tombstone: ``pyramses`` is retired, and ``stepss`` replaces it.

Installing this distribution is refused by ``setup.py``, so this module is
normally unreachable. It exists for the one case that gets past that: an
environment where an older ``pyramses`` is already installed and something
upgrades it in place. Raising here is the honest outcome. The alternative,
forwarding to ``stepss``, is what version 3.58.1 did, and it kept the retired
name working well enough that nobody had a reason to stop using it.
"""

raise ImportError(
    "pyramses is retired. Install stepss instead:\n"
    "\n"
    "    pip install stepss\n"
    "\n"
    "Then change `import pyramses` to `import stepss`. The API is unchanged: "
    "cfg, sim, extractor, curplot and HeliosSession keep their names, and "
    "`from pyramses.globals import X` becomes `from stepss.globals import X`.\n"
    "\n"
    "Documentation: https://stepss.sps-lab.org/python/"
)
