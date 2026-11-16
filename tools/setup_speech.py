"""Compatibility entry point for explicit user-facing speech bootstrap.

Historical development install evidence remains intact, but is not an input to
onboarding. No invocation without --approve-download installs anything.
"""

import sys

from .bootstrap import main as bootstrap_main


def main(argv=None):
    return bootstrap_main(["setup", "speech", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    raise SystemExit(main())
