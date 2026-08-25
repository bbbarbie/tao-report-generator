"""Local UI for the TAO monthly report.

Runs entirely on this machine — no workbook content, and no decision made here,
leaves the computer. Start it by double-clicking "TAO Report Generator" on
Windows or ``run.command`` on macOS, or with ``streamlit run ui.py``.
"""

from __future__ import annotations

import streamlit as st

from ui_pages import decisions as decisions_page
from ui_pages import generate as generate_page
from ui_pages import review as review_page
from ui_pages.shared import DECISIONS, GENERATE, REVIEW, report, store

st.set_page_config(page_title="TAO Report Generator", page_icon="🚢", layout="wide")

PAGES = {
    GENERATE: generate_page.render,
    REVIEW: review_page.render,
    DECISIONS: decisions_page.render,
}


st.session_state.setdefault("page", GENERATE)

with st.sidebar:
    st.markdown("### TAO Report Generator")
    # The screen names stay fixed. Outstanding counts go underneath rather than
    # into the labels, so the navigation does not shift as items are resolved.
    st.radio("Screen", list(PAGES), key="page", label_visibility="collapsed")

    current = report()
    if current is not None and current.issues:
        st.caption(f"⚠ {len(current.issues)} items need review")
    saved = store()
    if saved.rule_count or saved.override_count:
        st.caption(
            f"{saved.rule_count} saved rules · {saved.override_count} overrides"
        )

    st.divider()
    st.caption(
        "Runs locally. Excel files and saved decisions stay on this computer; "
        "nothing is uploaded."
    )

PAGES[st.session_state["page"]]()
