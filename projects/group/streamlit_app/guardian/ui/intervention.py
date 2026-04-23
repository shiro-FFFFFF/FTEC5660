"""Intervention UI chrome — sticky ambient banner + full-screen dialog.

Rendered by ``state.bootstrap()`` on every page so the modal can pop on
any screen (exactly like the Flutter overlay that pushed over whichever
route was active).
"""

from __future__ import annotations

import time
import streamlit as st

from guardian.agents.intervention_agent import InterventionAction, InterventionLevel
from guardian.agents.risk_agent import RiskAgent, RuleScoreContribution
from guardian.agents.user_settings import UserSettingsStore
from guardian.ui.widgets import risk_chip


def render_shared_chrome() -> None:
    """Top-of-page banner + modal dialog if a pending intervention exists."""
    intervention = st.session_state.get("intervention")
    if intervention is None:
        return

    ambient = intervention.state.ambient
    if ambient is not None and not ambient.dismissed:
        _render_ambient_banner(ambient)

    pending = intervention.state.pending
    if pending is not None:
        # Keyed on the id so a new intervention reopens a fresh dialog.
        _open_intervention_dialog(pending.id)


def _render_ambient_banner(action: InterventionAction) -> None:
    st.warning(
        f"**{action.headline}** — {risk_chip(action.risk)}\n\n{action.body}",
        icon="⚠️",
    )
    cols = st.columns([1, 1, 6])
    if cols[0].button("Open audit", key=f"ambient_open_{action.id}"):
        st.switch_page("pages/5_🛡️_Audit.py")
    if cols[1].button("Dismiss", key=f"ambient_dismiss_{action.id}"):
        st.session_state["intervention"].dismiss_ambient()
        st.rerun()


def _open_intervention_dialog(pending_id: str) -> None:
    """Open (or re-open) the intervention modal for the pending action."""

    # Streamlit re-invokes the dialog body on every rerun *if* its
    # function is called. We key the dialog by ``pending_id`` so moving
    # to a new intervention resets the cool-off timer.
    state_key = f"intervention_opened_{pending_id}"
    started_key = f"intervention_started_{pending_id}"

    if not st.session_state.get(state_key):
        st.session_state[state_key] = True
        st.session_state[started_key] = time.monotonic()

    _intervention_dialog(pending_id=pending_id, started_key=started_key)


@st.dialog("🛑 Guardian paused this action", width="large")
def _intervention_dialog(*, pending_id: str, started_key: str) -> None:
    intervention = st.session_state["intervention"]
    action: InterventionAction | None = intervention.state.pending
    if action is None or action.id != pending_id:
        # Stale dialog; nothing to show.
        st.caption("No active intervention.")
        return

    is_delay = action.level == InterventionLevel.DELAY
    is_manual_review = action.level == InterventionLevel.MANUAL_REVIEW

    # Headline + risk chip.
    st.subheader(action.headline)
    st.markdown(risk_chip(action.risk))
    st.markdown(action.body)
    if is_manual_review:
        _render_manual_review_details(action.event_id)

    # Cool-off countdown.
    started_at = st.session_state.get(started_key, time.monotonic())
    cooldown = 60 if is_delay else action.cooldown_seconds
    elapsed = int(time.monotonic() - started_at)
    remaining = max(0, cooldown - elapsed)
    if cooldown > 0:
        st.progress(
            min(1.0, elapsed / cooldown),
            text=(
                f"Cool-off ends in {remaining}s — use this time to verify."
                if remaining > 0
                else "Cool-off complete."
            ),
        )

    # Trusted-contact callout for delay-level.
    settings_store: UserSettingsStore = st.session_state["user_settings"]
    settings = settings_store.state
    if is_delay:
        emergency = settings.emergency
        contact_line = (
            f"{emergency.name} ({emergency.relation or 'Trusted'}) — {emergency.phone}"
            if emergency is not None
            else "No emergency contact set — add one under Settings."
        )
        st.info(
            f"**Trusted contact will be notified**\n\n{contact_line}. "
            "You can continue this transfer in 24 hours after a family check-in.",
            icon="👥",
        )

    st.divider()

    cols = st.columns([1, 1])
    if is_manual_review:
        if cols[0].button(
            "Cancel transfer",
            key=f"intv_cancel_{action.id}",
            use_container_width=True,
        ):
            st.session_state["bank_transfer_cancelled_event_id"] = action.event_id
            intervention.resolve_pending()
            st.rerun()

        if cols[1].button(
            "Proceed after review",
            key=f"intv_proceed_{action.id}",
            type="primary",
            use_container_width=True,
        ):
            if remaining > 0:
                st.warning(f"Please wait {remaining}s before proceeding.")
                return
            intervention.override_pending()
            st.rerun()
        return

    if cols[0].button(
        "📞 Call my son",
        key=f"intv_call_{action.id}",
        type="primary",
        use_container_width=True,
    ):
        st.session_state["bank_transfer_cancelled_event_id"] = action.event_id
        intervention.resolve_pending()
        st.rerun()

    override_disabled = is_delay
    override_label = "Locked for 24h" if is_delay else "I am sure, proceed (PIN)"
    if cols[1].button(
        override_label,
        key=f"intv_override_{action.id}",
        disabled=override_disabled,
        use_container_width=True,
    ):
        if remaining > 0:
            st.warning(f"Please wait {remaining}s before proceeding.")
            return
        intervention.override_pending()
        st.rerun()


def _render_manual_review_details(event_id: str) -> None:
    risk_agent: RiskAgent = st.session_state["risk"]
    assessment = next(
        (assessment for assessment in reversed(risk_agent.assessments) if assessment.event_id == event_id),
        None,
    )
    if assessment is None:
        return

    st.caption("Review the current transfer risk before proceeding.")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Fast rule", f"{assessment.fast_risk:.2f}")
    metric_cols[1].metric(
        "LLM",
        f"{assessment.llm_risk:.2f}" if assessment.llm_risk is not None else "—",
    )
    metric_cols[2].metric(
        "Reviewer",
        f"{assessment.reviewer_risk:.2f}" if assessment.reviewer_risk is not None else "—",
    )
    metric_cols[3].metric("Final", f"{assessment.final_risk:.2f}")

    info_cols = st.columns(2)
    info_cols[0].markdown(f"**Consensus:** `{assessment.consensus}`")
    info_cols[1].markdown(f"**Source:** `{assessment.source}`")

    if assessment.reasons:
        with st.expander("Analysis", expanded=True):
            for reason in assessment.reasons:
                st.markdown(f"- {reason}")

    if assessment.contributions:
        with st.expander("Rule contributions", expanded=False):
            _render_contributions(assessment.contributions)


def _render_contributions(contribs: list[RuleScoreContribution]) -> None:
    for contribution in contribs:
        cols = st.columns([2, 5, 1])
        cols[0].markdown(f"`{contribution.feature}`")
        cols[1].progress(min(1.0, max(0.0, contribution.value)))
        cols[2].markdown(f"**+{contribution.value:.2f}**")
        st.caption(contribution.detail)
