"""User / account-holder preferences, trusted contacts, override PIN.

1:1 port of ``app/lib/agents/user_settings.dart``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class TrustedContact:
    name: str
    phone: str
    relation: str | None = None


@dataclass(frozen=True)
class UserSettings:
    account_holder: str = "Mrs. Wong"
    override_pin: str | None = None
    emergency: TrustedContact | None = None
    trusted: TrustedContact | None = None


class UserSettingsStore:
    """Session-state wrapper around a :class:`UserSettings` value."""

    def __init__(self, initial: UserSettings | None = None) -> None:
        self._state: UserSettings = initial or _default_settings()

    @property
    def state(self) -> UserSettings:
        return self._state

    def set_account_holder(self, name: str) -> None:
        self._state = replace(self._state, account_holder=name)

    def set_emergency(self, contact: TrustedContact) -> None:
        self._state = replace(self._state, emergency=contact)

    def clear_emergency(self) -> None:
        self._state = replace(self._state, emergency=None)

    def set_trusted(self, contact: TrustedContact) -> None:
        self._state = replace(self._state, trusted=contact)

    def clear_trusted(self) -> None:
        self._state = replace(self._state, trusted=None)

    def set_override_pin(self, pin: str) -> None:
        self._state = replace(self._state, override_pin=pin)

    def clear_override_pin(self) -> None:
        self._state = replace(self._state, override_pin=None)


def _default_settings() -> UserSettings:
    return UserSettings(
        account_holder="Mrs. Wong",
        emergency=TrustedContact(
            name="David Wong", phone="+852 9234 5678", relation="Son"
        ),
        trusted=TrustedContact(
            name="Emily Chan", phone="+852 9111 2222", relation="Daughter"
        ),
    )


def default_user_settings() -> UserSettingsStore:
    return UserSettingsStore(_default_settings())
