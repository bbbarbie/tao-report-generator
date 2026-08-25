"""The Needs Review screen: every open question, and a way to answer it.

Each question shows the voyage, its timestamps, which Daily files it came from,
what exactly is uncertain, the candidate answers, and — where the evidence
supports one — a recommendation with the reasoning behind it. Nothing is
applied until the user picks.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from app.decisions import VESSEL_OPERATOR
from app.review import MISSING_ATD, UNKNOWN_OPERATOR, ReviewIssue
from ui_pages.shared import GENERATE, go, moment, report, rerun_with_decisions, store

KIND_TITLE = {
    "UNKNOWN_OPERATOR": "Unknown operator",
    "AMBIGUOUS_VOYAGE": "Two records might be one voyage",
    "MISSING_ATD": "No departure time",
    "CONFLICTING_SNAPSHOTS": "Daily files disagree",
    "VALUE_DISAGREEMENT": "Calculated value differs from the Daily",
    "UNCERTAIN_WINDOW": "Uncertain berthing window",
    "BERTHED_BEFORE_WINDOW": "Berthed before the window opened",
}

MANUAL_KEYS = {"manual"}


def render() -> None:
    st.title("Needs Review")
    current = report()

    if current is None:
        st.info("Process a month on the Generate screen first.")
        if st.button("Go to Generate"):
            go(GENERATE)
            st.rerun()
        return

    if not current.issues:
        st.success(
            "Nothing to review. Every row in this month was produced from complete "
            "source data by rules that hold across the whole period."
        )
        if st.button("Back to Generate", type="primary"):
            go(GENERATE)
            st.rerun()
        return

    blocking = len(current.blocking_issues)
    st.caption(
        f"{len(current.issues)} open — {blocking} would leave a required field "
        "empty; the rest already have a defensible value you can disagree with."
    )
    st.caption(
        "Answers about a vessel's operator are remembered for future months. "
        "Everything else applies to this voyage in this month only."
    )

    for issue in current.issues:
        _render_issue(issue, current.period)


def _render_issue(issue: ReviewIssue, period: str) -> None:
    title = KIND_TITLE.get(issue.kind, issue.kind)
    mark = "🚩" if issue.blocking else "•"
    label = f"{mark}  {title} — {issue.svc or '?'} {issue.tfc or issue.voyage_key}"

    with st.expander(label, expanded=issue.blocking):
        left, right = st.columns([3, 2])

        with left:
            st.markdown(f"**{issue.question}**")
            if issue.evidence:
                for line in issue.evidence:
                    st.caption(line)

            recommended = issue.recommended
            if recommended:
                st.info(
                    f"**Recommended: {recommended.label}**\n\n{issue.why_recommended}"
                )
            else:
                st.warning(
                    "No recommendation — the evidence does not favour one answer. "
                    "This one needs your knowledge of the vessel."
                )

        with right:
            st.markdown("**This voyage**")
            st.caption(f"Vessel: {issue.vessel or '—'}")
            st.caption(f"Service: {issue.svc or '—'}   TFC: {issue.tfc or '—'}")
            for name, value in issue.timestamps.items():
                st.caption(f"{name}: {moment(value)}")
            st.caption(
                f"Seen in {len(issue.source_files)} Daily files: "
                + ", ".join(issue.source_files[:4])
                + (" …" if len(issue.source_files) > 4 else "")
            )

        _render_choices(issue, period)


def _render_choices(issue: ReviewIssue, period: str) -> None:
    keys = [o.key for o in issue.options]
    labels = {
        o.key: (f"{o.label} ★" if o.recommended else o.label) for o in issue.options
    }
    default = next((i for i, o in enumerate(issue.options) if o.recommended), 0)

    with st.form(f"issue-{issue.id}"):
        choice = st.radio(
            "Your decision",
            keys,
            index=default,
            format_func=lambda k: labels[k],
            key=f"choice-{issue.id}",
        )
        for option in issue.options:
            if option.rationale:
                st.caption(f"{labels[option.key]} — {option.rationale}")

        manual_number = None
        manual_moment = None
        if any(k in MANUAL_KEYS for k in keys):
            if issue.kind == MISSING_ATD:
                manual_moment = st.text_input(
                    "Departure time (YYYY-MM-DD HH:MM), if entering one",
                    key=f"manual-{issue.id}",
                )
            else:
                manual_number = st.number_input(
                    "Value, if entering one",
                    value=0.0,
                    step=0.1,
                    format="%.1f",
                    key=f"manual-{issue.id}",
                )

        note = st.text_input("Note (optional)", key=f"note-{issue.id}")

        if st.form_submit_button("Save decision", type="primary"):
            _save(issue, choice, period, note, manual_number, manual_moment)


def _save(
    issue: ReviewIssue,
    choice: str,
    period: str,
    note: str,
    manual_number,
    manual_moment,
) -> None:
    decisions = store()
    option = issue.option(choice)
    if option is None:
        st.error("That option is no longer available — reprocess the month.")
        return

    value = option.value
    field = issue.field

    if choice in MANUAL_KEYS:
        if issue.kind == MISSING_ATD:
            try:
                parsed = datetime.fromisoformat((manual_moment or "").strip())
            except ValueError:
                st.error("Enter the departure time as YYYY-MM-DD HH:MM.")
                return
            # Supplying a departure time both includes the voyage and sets it.
            decisions.record_override(
                period, issue.voyage_key, "atd", parsed.isoformat(),
                issue.kind, choice, note,
            )
            value, field = True, "include"
        else:
            value = float(manual_number or 0.0)

    if issue.reusable and issue.kind == UNKNOWN_OPERATOR:
        decisions.record_rule(
            VESSEL_OPERATOR, issue.target, field, value, choice, note
        )
        message = (
            f"Saved as a rule: {issue.vessel} → {value}. "
            "It will apply automatically in future months."
        )
    else:
        decisions.record_override(
            period, issue.voyage_key, field, value, issue.kind, choice, note
        )
        message = (
            f"Saved for {issue.tfc or issue.voyage_key} in {period} only. "
            "No other voyage is affected."
        )

    decisions.save()
    rerun_with_decisions()
    st.success(message)
    st.rerun()
