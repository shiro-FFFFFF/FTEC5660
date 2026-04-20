"""Settings screen — account holder, trusted contacts, override PIN."""

from __future__ import annotations

import streamlit as st

from guardian.agents.user_settings import TrustedContact, UserSettingsStore


def render() -> None:
    st.title("⚙️ Settings")
    store: UserSettingsStore = st.session_state["user_settings"]
    settings = store.state

    # -- Account holder -----------------------------------------------------
    with st.container(border=True):
        st.subheader("Account holder")
        new_name = st.text_input("Full name", value=settings.account_holder)
        if new_name.strip() and new_name.strip() != settings.account_holder:
            if st.button("Save name"):
                store.set_account_holder(new_name.strip())
                st.success("Saved.")
                st.rerun()

    st.markdown("")

    # -- Emergency contact --------------------------------------------------
    _render_contact_card(
        title="Emergency contact",
        hint="We will suggest calling this person if Guardian spots a scam.",
        contact=settings.emergency,
        on_save=store.set_emergency,
        on_clear=store.clear_emergency,
        key_prefix="emergency",
    )

    # -- Trusted helper -----------------------------------------------------
    _render_contact_card(
        title="Trusted helper",
        hint="Can help you set the override PIN and review unusual transactions.",
        contact=settings.trusted,
        on_save=store.set_trusted,
        on_clear=store.clear_trusted,
        key_prefix="trusted",
    )

    # -- Override PIN -------------------------------------------------------
    with st.container(border=True):
        st.subheader("Override PIN (optional)")
        st.caption(
            "Ask your trusted helper to set a 4-digit PIN. Guardian will only ask "
            "for it if you want to override a scam warning. Day-to-day transfers "
            "do NOT require this PIN."
        )
        pin_status = "is set" if settings.override_pin else "not set"
        st.markdown(f"**Current:** `{pin_status}`")

        with st.form(key="pin_form", clear_on_submit=True):
            pin = st.text_input(
                "New 4-digit PIN",
                type="password",
                max_chars=4,
            )
            confirm = st.text_input(
                "Confirm PIN",
                type="password",
                max_chars=4,
            )
            cols = st.columns(2)
            submit = cols[0].form_submit_button("Save PIN", type="primary")
            clear = cols[1].form_submit_button("Remove PIN")

        if submit:
            if len(pin) == 4 and pin.isdigit() and pin == confirm:
                store.set_override_pin(pin)
                st.success("PIN saved.")
                st.rerun()
            else:
                st.error("PIN must be 4 digits and match the confirmation.")
        if clear:
            store.clear_override_pin()
            st.success("PIN removed.")
            st.rerun()


def _render_contact_card(
    *,
    title: str,
    hint: str,
    contact: TrustedContact | None,
    on_save,
    on_clear,
    key_prefix: str,
) -> None:
    with st.container(border=True):
        st.subheader(title)
        st.caption(hint)
        with st.form(key=f"{key_prefix}_form", clear_on_submit=False):
            name = st.text_input(
                "Name",
                value=contact.name if contact else "",
                key=f"{key_prefix}_name",
            )
            phone = st.text_input(
                "Phone",
                value=contact.phone if contact else "",
                key=f"{key_prefix}_phone",
            )
            relation = st.text_input(
                "Relation (e.g. Son, Daughter)",
                value=contact.relation or "" if contact else "",
                key=f"{key_prefix}_relation",
            )
            cols = st.columns(2)
            save = cols[0].form_submit_button("Save", type="primary")
            remove = cols[1].form_submit_button("Remove") if contact else False

        if save:
            if not name.strip() or not phone.strip():
                st.error("Name and phone are required.")
            else:
                on_save(
                    TrustedContact(
                        name=name.strip(),
                        phone=phone.strip(),
                        relation=relation.strip() or None,
                    )
                )
                st.success("Saved.")
                st.rerun()
        if remove:
            on_clear()
            st.success("Cleared.")
            st.rerun()
