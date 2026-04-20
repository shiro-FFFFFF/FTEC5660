"""Chat page — contact selector + thread view."""

from __future__ import annotations

from guardian.state import bootstrap
from guardian.ui import chat


def main() -> None:
    bootstrap()
    chat.render()


main()
