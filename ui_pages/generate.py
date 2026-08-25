"""The Generate screen: pick files, pick a month, process, download."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from app.calculations import AUTO, REVIEWED, UNRESOLVED
from app.cli import write_review_csv
from app.generator import write_workbook
from app.parser import discover_daily_files
from ui_pages.shared import (
    DEFAULT_DAILY_DIR,
    OUTPUT_DIR,
    REVIEW,
    go,
    report,
    run_report,
    stage_uploads,
)


def render() -> None:
    st.title("TAO Monthly Report Generator")
    st.caption(
        "Builds TAO Compare from your Daily Berth Report files. Everything stays "
        "on this computer."
    )

    files = _choose_files()
    year, month = _choose_month()

    st.subheader("3. Process")
    if st.button(
        "Process Daily files", type="primary", disabled=not files, key="process"
    ):
        with st.spinner("Reading Daily files and rebuilding voyage histories…"):
            run_report(files, year, month)

    current = report()
    if current is not None:
        _render_result(current)


def _choose_files() -> list[Path]:
    st.subheader("1. Daily files")
    source = st.radio(
        "Where are the Daily files?",
        ["Upload files", "Use a folder on this computer"],
        horizontal=True,
        label_visibility="collapsed",
        key="source",
    )

    files: list[Path] = []
    if source == "Upload files":
        uploaded = st.file_uploader(
            "Select Daily workbooks",
            type=["xlsx"],
            accept_multiple_files=True,
            help="Filenames must contain the snapshot date, e.g. 'Daily 20260731.xlsx'.",
            key="uploads",
        )
        if uploaded:
            files = stage_uploads(uploaded)
    else:
        folder = st.text_input("Folder", value=str(DEFAULT_DAILY_DIR), key="folder")
        if folder and Path(folder).is_dir():
            files = discover_daily_files(folder)
        elif folder:
            st.error("That folder does not exist.")

    if files:
        st.success(
            f"{len(files)} Daily files ready — {files[0].name} to {files[-1].name}"
        )
    return files


def _choose_month() -> tuple[int, int]:
    st.subheader("2. Month")
    # Reports are written after the month closes, so default to the one just gone.
    today = date.today()
    previous = date(today.year, today.month, 1) - timedelta(days=1)
    col1, col2 = st.columns(2)
    year = col1.number_input(
        "Year", min_value=2000, max_value=2100, value=previous.year, step=1, key="year"
    )
    month = col2.selectbox(
        "Month",
        list(range(1, 13)),
        index=previous.month - 1,
        format_func=lambda m: f"{m:02d}",
        key="month",
    )
    return int(year), int(month)


def _render_result(current) -> None:
    st.divider()

    a, b, c, d = st.columns(4)
    a.metric("Voyages", len(current.rows))
    b.metric("Automatic", len(current.rows_by_resolution(AUTO)))
    c.metric("Reviewed", len(current.rows_by_resolution(REVIEWED)))
    d.metric("Unresolved", len(current.rows_by_resolution(UNRESOLVED)))

    if not current.rows:
        st.warning(
            "No voyages departed in that month in these files. Check the month, "
            "or add Daily files covering it."
        )
        return

    if current.issues:
        blocking = len(current.blocking_issues)
        note = (
            f" {blocking} of them would leave a required field empty."
            if blocking
            else " None of them blocks the report — each already has a defensible "
            "value you can accept or change."
        )
        st.warning(f"**{len(current.issues)} items need review.**{note}")
        if st.button(
            f"Review {len(current.issues)} items", type="primary", key="to_review"
        ):
            go(REVIEW)
            st.rerun()
    else:
        st.success("No open questions — every row was produced from complete data.")

    st.subheader("Report")
    st.caption(
        "Row status: automatic · reviewed (a decision was applied) · unresolved "
        "(an open question remains). The workbook tints the last two."
    )
    st.dataframe(
        [
            {
                "Status": r.resolution,
                "SVC": r.svc,
                "TFC Code": r.tfc,
                "OPR": r.opr,
                "靠泊碼頭": r.terminal,
                "ATA": r.ata,
                "ATB": r.atb,
                "Arr Delay (hr)": r.arr_delay.value,
                "Dep Delay (Hr)": r.dep_delay.value,
                "W/B (hr)": r.waiting.value,
                "平均侯泊時間": r.average_waiting,
            }
            for r in current.rows
        ],
        hide_index=True,
        width="stretch",
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    workbook = write_workbook(
        current, OUTPUT_DIR / f"TAO Compare {current.period}.xlsx"
    )
    review_csv = write_review_csv(
        current, OUTPUT_DIR / f"review {current.period}.csv"
    )

    st.subheader("4. Download")
    if current.issues:
        st.caption(
            "You can download now — unresolved rows are tinted and listed on the "
            "Review sheet — or answer the questions first."
        )
    col1, col2 = st.columns(2)
    col1.download_button(
        "Download TAO Compare workbook",
        data=workbook.read_bytes(),
        file_name=workbook.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
    col2.download_button(
        "Download review.csv",
        data=review_csv.read_bytes(),
        file_name=review_csv.name,
        mime="text/csv",
    )

    with st.expander("Which services were included"):
        st.dataframe(
            [
                {
                    "SVC": svc,
                    "In report": verdict == "in",
                    "Reason": "" if verdict == "in" else verdict,
                }
                for svc, verdict in sorted(current.selection.service_scope.items())
            ],
            hide_index=True,
            width="stretch",
        )
        st.caption("Edit config/report_scope.json to force a service in or out.")
