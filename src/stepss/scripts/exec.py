#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Console entry point for the ``ramses`` command.

Provides a thin command-line wrapper around :class:`stepss.sim` so that a
RAMSES simulation can be launched directly from the terminal without writing
a Python script::

    ramses -t cmd.txt

The command file (``cmd.txt``) must follow the RAMSES command-file format
(see :meth:`stepss.cfg.writeCmdFile` for the expected structure).
"""
import sys
import stepss

def run():
    """Parse command-line arguments and execute a RAMSES simulation.

    Expected invocation::

        ramses -t <cmd_file>

    where ``<cmd_file>`` is the path to a RAMSES command file.  The simulation
    output trace is written to ``output_temp.trace`` in the current working
    directory.

    :raises SystemExit: if the argument count or the ``-t`` flag are incorrect.
    """
    args = sys.argv[1:]
    if len(args) != 2 or args[0] != '-t' :
        sys.exit("Wrong arguments. Usage: ramses -t cmd.txt")
    ram = stepss.sim()
    case = stepss.cfg(args[1])
    case.addOut('output_temp.trace')
    ram.execSim(case)
    print("The output_temp.trace file contains the execution trace.")
    