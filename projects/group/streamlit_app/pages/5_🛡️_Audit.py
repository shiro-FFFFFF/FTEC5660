"""Audit page — XAI assessment cards + tool trace."""

from __future__ import annotations

from guardian.state import bootstrap
from guardian.ui import audit


def main() -> None:
    bootstrap()
    audit.render()


main()
