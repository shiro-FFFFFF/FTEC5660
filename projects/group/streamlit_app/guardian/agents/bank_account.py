"""Mock bank account ledger. 1:1 port of ``app/lib/agents/bank_account.dart``.

Starts with a small seeded transaction history so the Bank screen looks
lived-in. ``commit_transfer`` mutates the balance + prepends a new row;
``pay_bill`` does the same for utility payments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from guardian.scenarios.events import TransactionEvent


class TxnCategory(str, Enum):
    TRANSFER = "transfer"
    BILL = "bill"
    SALARY = "salary"
    SHOPPING = "shopping"
    OTHER = "other"


@dataclass(frozen=True)
class BankTransaction:
    id: str
    timestamp: datetime
    label: str
    amount_hkd: float  # negative = debit, positive = credit
    category: TxnCategory
    account: str | None = None
    new_payee: bool = False


_STARTING_BALANCE = 482_530.55


@dataclass
class BankAccountState:
    balance_hkd: float
    history: list[BankTransaction] = field(default_factory=list)  # newest first


class BankAccount:
    def __init__(self) -> None:
        seed = datetime.now()
        self._state = BankAccountState(
            balance_hkd=_STARTING_BALANCE,
            history=[
                BankTransaction(
                    id="seed_pension",
                    timestamp=seed - timedelta(days=2),
                    label="Pension — MPF",
                    amount_hkd=8500.00,
                    category=TxnCategory.SALARY,
                ),
                BankTransaction(
                    id="seed_groceries",
                    timestamp=seed - timedelta(days=3),
                    label="Groceries · Wellcome",
                    amount_hkd=-412.50,
                    category=TxnCategory.SHOPPING,
                ),
                BankTransaction(
                    id="seed_son",
                    timestamp=seed - timedelta(days=5),
                    label="Son (David Wong)",
                    amount_hkd=-2000.00,
                    category=TxnCategory.TRANSFER,
                ),
                BankTransaction(
                    id="seed_clp",
                    timestamp=seed - timedelta(days=10),
                    label="CLP Power HK Ltd",
                    amount_hkd=-412.00,
                    category=TxnCategory.BILL,
                ),
            ],
        )

    @property
    def state(self) -> BankAccountState:
        return self._state

    def commit_transfer(self, event: TransactionEvent) -> BankTransaction:
        txn = BankTransaction(
            id=f"txn_{event.id}",
            timestamp=event.timestamp,
            label=event.to_name,
            account=event.to_account,
            amount_hkd=-event.amount_hkd,
            category=TxnCategory.TRANSFER,
            new_payee=event.new_recipient,
        )
        self._state = BankAccountState(
            balance_hkd=self._state.balance_hkd - event.amount_hkd,
            history=[txn, *self._state.history],
        )
        return txn

    def pay_bill(self, name: str, amount: float) -> BankTransaction:
        txn = BankTransaction(
            id=f"bill_{datetime.now().timestamp():.0f}",
            timestamp=datetime.now(),
            label=name,
            amount_hkd=-amount,
            category=TxnCategory.BILL,
        )
        self._state = BankAccountState(
            balance_hkd=self._state.balance_hkd - amount,
            history=[txn, *self._state.history],
        )
        return txn

    def reset(self) -> None:
        self.__init__()  # re-seed
