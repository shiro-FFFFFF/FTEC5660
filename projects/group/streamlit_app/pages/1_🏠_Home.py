"""Home page — re-exports the landing content."""

from __future__ import annotations

from guardian.state import bootstrap
from guardian.ui import home


def main() -> None:
    bootstrap()
    home.render()


main()
