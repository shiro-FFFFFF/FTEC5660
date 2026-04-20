"""Bank screen — balance, transfer form, pay-bill form, transaction history."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from guardian.agents.bank_account import BankAccount, TxnCategory
from guardian.agents.context_agent import ContextAgent
from guardian.agents.intervention_agent import InterventionAgent
from guardian.scenarios.engine import ScenarioEngine
from guardian.scenarios.events import TransactionEvent
from guardian.ui.widgets import fmt_hkd, relative_time


def render() -> None:
    bank: BankAccount = st.session_state["bank"]
    st.title("HSBC Hong Kong")
    _render_balance(bank)

    tabs = st.tabs(["🔄 Transfer", "🧾 Pay bill", "📜 History"])
    with tabs[0]:
        _render_transfer_form()
    with tabs[1]:
        _render_pay_bill_form()
    with tabs[2]:
        _render_history(bank)


def _render_balance(bank: BankAccount) -> None:
    with st.container(border=True):
        st.caption("Savings · 012-345678-000")
        st.markdown(f"# {fmt_hkd(bank.state.balance_hkd)}")
        st.caption("Available balance")


def _render_transfer_form() -> None:
    bank: BankAccount = st.session_state["bank"]
    engine: ScenarioEngine = st.session_state["engine"]
    context: ContextAgent = st.session_state["context"]
    intervention: InterventionAgent = st.session_state["intervention"]

    pending_txn = engine.state.pending_user_transaction
    if pending_txn is not None:
        st.info(
            "Pre-filled from the scripted request on the call. "
            "Review carefully before sending.",
            icon="⚠️",
        )

    with st.form(key="transfer_form", clear_on_submit=False):
        name = st.text_input(
            "Recipient name",
            value=pending_txn.to_name if pending_txn else "",
        )
        account = st.text_input(
            "Account number",
            value=pending_txn.to_account if pending_txn else "",
        )
        amount = st.number_input(
            "Amount (HKD)",
            min_value=0.0,
            step=100.0,
            value=float(pending_txn.amount_hkd) if pending_txn else 0.0,
        )
        new_payee = st.toggle(
            "First-time recipient",
            value=bool(pending_txn.new_recipient) if pending_txn else True,
            help="Guardian scrutinises new payees more carefully.",
        )
        submitted = st.form_submit_button(
            "Review and send",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        _submit_transfer(
            name=name,
            account=account,
            amount=amount,
            new_payee=new_payee,
            bank=bank,
            engine=engine,
            context=context,
            intervention=intervention,
        )


def _submit_transfer(
    *,
    name: str,
    account: str,
    amount: float,
    new_payee: bool,
    bank: BankAccount,
    engine: ScenarioEngine,
    context: ContextAgent,
    intervention: InterventionAgent,
) -> None:
    if amount <= 0:
        st.error("Enter an amount greater than zero.")
        return
    event = TransactionEvent(
        id=f"manual_txn_{int(datetime.now().timestamp() * 1000)}",
        timestamp=datetime.now(),
        amount_hkd=float(amount),
        to_name=name.strip() or "Unknown recipient",
        to_account=account.strip() or "000-000000-000",
        new_recipient=new_payee,
    )
    with st.spinner("Guardian reviewing…"):
        context.ingest(event)

    pending = intervention.state.pending
    if pending is None:
        bank.commit_transfer(event)
        engine.resolve_pending_transaction()
        st.success(f"Transferred {fmt_hkd(event.amount_hkd)} to {event.to_name}.")
        st.rerun()
    else:
        # Intervention is blocking; the dialog will pop on the next rerun.
        st.rerun()


def _render_pay_bill_form() -> None:
    bank: BankAccount = st.session_state["bank"]
    with st.form(key="pay_bill_form", clear_on_submit=True):
        biller = st.selectbox(
            "Biller",
            options=["CLP Power HK Ltd", "HK Electric", "Towngas", "Water Supplies"],
        )
        amount = st.number_input("Amount (HKD)", min_value=0.0, step=10.0, value=412.00)
        submitted = st.form_submit_button("Pay bill", type="primary")
    if submitted and amount > 0:
        bank.pay_bill(biller, amount)
        st.success(f"Paid {fmt_hkd(amount)} to {biller}.")
        st.rerun()


def _render_history(bank: BankAccount) -> None:
    st.caption("Newest first")
    for txn in bank.state.history:
        sign = "−" if txn.amount_hkd < 0 else "+"
        color = "red" if txn.amount_hkd < 0 else "green"
        icon = _category_icon(txn.category)
        cols = st.columns([1, 5, 3])
        cols[0].markdown(f"### {icon}")
        with cols[1]:
            st.markdown(f"**{txn.label}**")
            meta = relative_time(txn.timestamp)
            if txn.account:
                meta = f"{txn.account} · {meta}"
            st.caption(meta)
        cols[2].markdown(
            f":{color}[**{sign} {fmt_hkd(abs(txn.amount_hkd))}**]"
        )


def _category_icon(category: TxnCategory) -> str:
    return {
        TxnCategory.TRANSFER: "💸",
        TxnCategory.BILL: "🧾",
        TxnCategory.SALARY: "💰",
        TxnCategory.SHOPPING: "🛒",
        TxnCategory.OTHER: "🔁",
    }.get(category, "•")
