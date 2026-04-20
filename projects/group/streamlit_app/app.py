"""Streamlit entry point for Guardian.

Run with::

    streamlit run streamlit_app/app.py

The sidebar's multi-page nav is auto-populated from ``pages/`` (siblings
of this file). The landing screen is Home, rendered from the same module
as ``pages/1_🏠_Home.py`` so both entry paths show the same content.
"""

from __future__ import annotations

import streamlit as st

from guardian.state import bootstrap
from guardian.ui import home

st.set_page_config(
    page_title="Guardian — Anti-Scam Decision Security",
    page_icon="🛡️",
    layout="centered",
    initial_sidebar_state="expanded",
)
bootstrap()
home.render()
