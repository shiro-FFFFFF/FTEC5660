"""Settings page — account holder, trusted contacts, override PIN."""

from __future__ import annotations

from guardian.state import bootstrap
from guardian.ui import settings


def main() -> None:
    bootstrap()
    settings.render()


main()
