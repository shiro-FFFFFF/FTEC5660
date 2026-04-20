"""Session-state bootstrap + shared chrome.

Every page calls :func:`bootstrap` at the top. It:

1. Ensures the session has singleton instances of the scam database,
   event log, agents, LLM runtime, scenario engine, user settings.
2. Runs ``engine.poll()`` to fire due scenario events.
3. Triggers ``streamlit-autorefresh`` so long as a scenario is playing.
4. Renders the sidebar footer (runtime badge, stop / reset buttons).
5. Renders the intervention dialog + ambient banner shared chrome.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import streamlit as st

from guardian.agents.bank_account import BankAccount
from guardian.agents.context_agent import ContextAgent
from guardian.agents.intervention_agent import InterventionAgent
from guardian.agents.risk_agent import RiskAgent
from guardian.agents.user_settings import default_user_settings
from guardian.data.event_log import EventLog
from guardian.data.scam_db import ScamDatabase
from guardian.llm.runtime import SmartLlmRuntime
from guardian.paths import SCAM_DB_CSV
from guardian.scenarios.engine import ScenarioEngine
from guardian.ui.live_trace import LiveTraceStore

log = logging.getLogger(__name__)

_INIT_KEY = "guardian_initialized"
_AUTOPLAY_KEY = "guardian_autoplay_fired"


def bootstrap() -> None:
    """Initialize singletons once, then run the per-rerun ambient loop."""
    if not st.session_state.get(_INIT_KEY):
        _initialize()

    _run_ambient_loop()


def _initialize() -> None:
    scam_db = _load_scam_db()
    event_log = EventLog()
    intervention = InterventionAgent()
    llm = SmartLlmRuntime()
    llm.probe()
    risk = RiskAgent(
        scam_db=scam_db,
        llm=llm,
        intervention=intervention,
        event_log=event_log,
    )
    context = ContextAgent(event_log=event_log, risk_agent=risk)
    bank = BankAccount()
    engine = ScenarioEngine(context=context)
    settings = default_user_settings()
    live_trace_store = LiveTraceStore()

    st.session_state["scam_db"] = scam_db
    st.session_state["event_log"] = event_log
    st.session_state["intervention"] = intervention
    st.session_state["llm"] = llm
    st.session_state["risk"] = risk
    st.session_state["context"] = context
    st.session_state["bank"] = bank
    st.session_state["engine"] = engine
    st.session_state["user_settings"] = settings
    st.session_state["live_trace_store"] = live_trace_store
    st.session_state[_INIT_KEY] = True


@st.cache_resource
def _load_scam_db() -> ScamDatabase:
    return ScamDatabase.from_csv(SCAM_DB_CSV.read_text(encoding="utf-8"))


def _run_ambient_loop() -> None:
    engine: ScenarioEngine = st.session_state["engine"]
    context: ContextAgent = st.session_state["context"]
    live_trace_store: LiveTraceStore = st.session_state["live_trace_store"]

    context.trace_callback_factory = lambda event: live_trace_store.make_callback(event.id)

    # Honour optional GUARDIAN_AUTOPLAY env var so `just play <id>` works.
    autoplay = os.environ.get("GUARDIAN_AUTOPLAY", "").strip()
    if autoplay and not st.session_state.get(_AUTOPLAY_KEY):
        engine.play(autoplay)
        st.session_state[_AUTOPLAY_KEY] = True

    # Drive periodic reruns while a scenario is playing OR an intervention
    # modal is waiting for its cool-off timer to tick down.
    intervention: InterventionAgent = st.session_state["intervention"]
    if (
        engine.is_playing()
        or intervention.state.pending is not None
        or live_trace_store.has_running()
    ):
        try:
            from streamlit_autorefresh import st_autorefresh

            st_autorefresh(interval=400, limit=None, key="guardian_autorefresh")
        except Exception as e:  # pragma: no cover - dep missing
            log.warning("streamlit-autorefresh unavailable: %s", e)

    engine.poll()

    _render_sidebar_footer()

    # Render shared chrome (ambient banner + intervention dialog).
    from guardian.ui import intervention as ui_intervention

    ui_intervention.render_shared_chrome()


def _render_sidebar_footer() -> None:
    engine: ScenarioEngine = st.session_state["engine"]
    llm: SmartLlmRuntime = st.session_state["llm"]
    intervention: InterventionAgent = st.session_state["intervention"]

    with st.sidebar:
        st.markdown("---")
        st.caption("Guardian runtime")
        _render_llm_status(llm)

        if engine.is_playing() and engine.state.playing is not None:
            playing = engine.state.playing
            st.markdown(f"▶ **Playing** `{playing.id}`")
            st.progress(min(1.0, engine.state.progress), text=playing.label)
            if st.button("⏹ Stop scenario", use_container_width=True):
                engine.stop()
                st.rerun()

        pending = intervention.state.pending
        if pending is not None:
            st.warning(
                f"⚠️ Intervention pending · risk {int(pending.risk * 100)}%",
                icon="⚠️",
            )

        if st.button("↺ Reset demo", use_container_width=True):
            _reset_session()
            st.rerun()


def _render_llm_status(llm: SmartLlmRuntime) -> None:
    """Show primary/fallback health with recovery countdown + retry button."""
    from guardian.llm.runtime import PrimaryHealth

    health = llm.health
    primary_name = llm.primary_name
    fallback_name = llm.fallback_name

    if health is PrimaryHealth.HEALTHY:
        st.success(f"🧠 LLM: `{primary_name}`", icon="✅")
    elif health is PrimaryHealth.COOLDOWN:
        remaining = int(llm.cooldown_remaining())
        st.warning(
            f"🧠 LLM: `{fallback_name}` · `{primary_name}` cooling down "
            f"(retry in {remaining}s)",
            icon="⏳",
        )
        if llm.last_error:
            st.caption(f"Last error: {llm.last_error[:120]}")
        if st.button("↻ Retry primary now", use_container_width=True, key="llm_retry"):
            llm.force_retry()
            st.rerun()
    elif health is PrimaryHealth.UNREACHABLE:
        st.info(
            f"🧠 LLM: `{fallback_name}` · `{primary_name}` not reachable",
            icon="ℹ️",
        )
        if st.button("↻ Re-probe primary", use_container_width=True, key="llm_reprobe"):
            # Reset to UNKNOWN by clearing and re-warming.
            llm.force_retry()
            llm._health = PrimaryHealth.UNKNOWN  # type: ignore[attr-defined]
            st.rerun()
    else:
        st.info(f"🧠 LLM: `{llm.name}`", icon="🔍")


def _reset_session() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def session(key: str) -> Any:
    """Shorthand for ``st.session_state[key]`` with a helpful error."""
    if key not in st.session_state:
        raise RuntimeError(
            f"Session key '{key}' missing — did you forget to call bootstrap()?"
        )
    return st.session_state[key]
