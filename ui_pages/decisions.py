"""The Saved decisions screen: what has been decided, and how to undo it.

Reusable rules and one-off overrides are shown apart, because that difference
is the whole point: a rule changes every future report, an override changes
one voyage in one month.
"""

from __future__ import annotations

import streamlit as st

from app.decisions import VESSEL_OPERATOR
from ui_pages.shared import rerun_with_decisions, store


def render() -> None:
    st.title("Saved decisions")
    decisions = store()

    st.caption(
        f"Kept in `{decisions.path}` on this computer. "
        f"{decisions.rule_count} reusable rules, {decisions.override_count} one-off "
        "overrides."
    )

    _render_rules(decisions)
    st.divider()
    _render_overrides(decisions)


def _render_rules(decisions) -> None:
    st.subheader("Reusable rules")
    st.caption(
        "Applied automatically to every future month. A vessel belongs to the "
        "same carrier next month as it does this month, so this is safe to reuse."
    )

    operators = decisions.rules.get(VESSEL_OPERATOR, {})
    if not operators:
        st.info("No rules yet. Answering an unknown-operator question creates one.")
        return

    for vessel, decision in sorted(operators.items()):
        col1, col2, col3 = st.columns([3, 2, 1])
        col1.write(f"**{vessel}**")
        col2.write(f"→ {decision.value}")
        if decision.note:
            col1.caption(decision.note)
        if decision.decided_at:
            col2.caption(f"set {decision.decided_at[:10]}")
        if col3.button("Forget", key=f"forget-rule-{vessel}"):
            decisions.forget_rule(VESSEL_OPERATOR, vessel)
            decisions.save()
            rerun_with_decisions()
            st.rerun()


def _render_overrides(decisions) -> None:
    st.subheader("One-off overrides")
    st.caption(
        "Each applies to one voyage in one month and nothing else. An override is "
        "never turned into a rule automatically — the same question about a "
        "different voyage is asked again, because the answer may differ."
    )

    if not decisions.overrides:
        st.info("No overrides yet.")
        return

    for period in sorted(decisions.overrides, reverse=True):
        voyages = decisions.overrides[period]
        if not any(voyages.values()):
            continue
        st.markdown(f"**{period[:4]}-{period[4:]}**")
        for voyage in sorted(voyages):
            for field_name, decision in sorted(voyages[voyage].items()):
                col1, col2, col3 = st.columns([2, 3, 1])
                col1.write(f"`{voyage}`")
                col2.write(f"{field_name} = {decision.value}")
                if decision.note:
                    col2.caption(decision.note)
                elif decision.issue_kind:
                    col2.caption(decision.issue_kind.replace("_", " ").lower())
                if col3.button("Undo", key=f"forget-{period}-{voyage}-{field_name}"):
                    decisions.forget_override(period, voyage, field_name)
                    decisions.save()
                    rerun_with_decisions()
                    st.rerun()
