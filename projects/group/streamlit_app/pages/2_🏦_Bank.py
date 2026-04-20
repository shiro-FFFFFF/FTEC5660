"""Bank page — balance, transfer, pay-bill, history."""

from __future__ import annotations

from guardian.state import bootstrap
from guardian.ui import bank


def main() -> None:
    bootstrap()
    bank.render()


main()
