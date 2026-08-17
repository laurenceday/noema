"""Command-line entry point for the Noema scaffold."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from noema import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser without performing domain work."""
    parser = argparse.ArgumentParser(
        prog="noema",
        description="Build and verify proof-carrying KRR releases.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse scaffold arguments and return a process exit status."""
    build_parser().parse_args(argv)
    return 0
