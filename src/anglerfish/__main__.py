"""Module entry point for `python -m anglerfish`."""

import sys

from .cli import main

raise SystemExit(main(sys.argv[1:]))
