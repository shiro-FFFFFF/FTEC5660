"""Messages page — SMS inbox."""

from __future__ import annotations

from guardian.state import bootstrap
from guardian.ui import messages


def main() -> None:
    bootstrap()
    messages.render()


main()
