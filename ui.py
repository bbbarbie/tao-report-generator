"""Local UI for the TAO monthly report.

Runs entirely on this machine — nothing is uploaded anywhere. Start it with
``./run.command`` (macOS), ``run.bat`` (Windows), or ``streamlit run ui.py``.
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from app.cli import REPO_ROOT, write_review_csv
from app.generator import write_workbook
from app.operators import UNKNOWN, OperatorMapping
from app.parser import discover_daily_files
from app.report import build_report
from app.selection import ScopeConfig

st.set_page_config(page_title="TAO Monthly Report Generator", page_icon="🚢")

DEFAULT_DAILY_DIR = REPO_ROOT / "samples" / "daily"
OUTPUT_DIR = REPO_ROOT / "output"


def _staged_uploads(uploaded) -> list[Path]:
    """Write uploaded workbooks to a temp folder, keeping their filenames.

    The filename carries the snapshot date, so it has to survive the upload.
    """
    folder = Path(tempfile.mkdtemp(prefix="tao-daily-"))
    paths = []
    for item in uploaded:
        target = folder / item.name
        target.write_bytes(item.getbuffer())
        paths.append(target)
    return paths


st.title("TAO Monthly Report Generator")
st.caption("Builds TAO Compare from your Daily Berth Report files. Runs locally.")

st.subheader("1. Daily files")
source = st.radio(
    "Where are the Daily files?",
    ["Upload files", "Use a folder on this computer"],
    horizontal=True,
    label_visibility="collapsed",
)

files: list[Path] = []
if source == "Upload files":
    uploaded = st.file_uploader(
        "Select Daily workbooks",
        type=["xlsx"],
        accept_multiple_files=True,
        help="Filenames must contain the snapshot date, e.g. 'Daily 20260731.xlsx'.",
    )
    if uploaded:
        files = _staged_uploads(uploaded)
else:
    folder = st.text_input("Folder", value=str(DEFAULT_DAILY_DIR))
    if folder and Path(folder).is_dir():
        files = discover_daily_files(folder)
    elif folder:
        st.error("That folder does not exist.")

if files:
    st.success(f"{len(files)} Daily files ready — {files[0].name} to {files[-1].name}")

st.subheader("2. Month")
# Reports are written after the month closes, so default to the one just gone.
today = date.today()
last_month = date(today.year, today.month, 1) - timedelta(days=1)
col1, col2 = st.columns(2)
year = col1.number_input(
    "Year", min_value=2000, max_value=2100, value=last_month.year, step=1
)
month = col2.selectbox(
    "Month",
    list(range(1, 13)),
    index=last_month.month - 1,
    format_func=lambda m: f"{m:02d}",
)

st.subheader("3. Generate")
if st.button("Generate TAO Compare", type="primary", disabled=not files):
    with st.spinner("Reading Daily files and rebuilding voyage histories…"):
        report = build_report(
            files, int(year), int(month), OperatorMapping.load(), ScopeConfig.load()
        )
    st.session_state["report"] = report

report = st.session_state.get("report")
if report:
    st.divider()
    needs_review = len(report.rows) - report.clean_row_count
    a, b, c = st.columns(3)
    a.metric("Voyages in report", len(report.rows))
    b.metric("Complete", report.clean_row_count)
    c.metric("Need review", needs_review)

    if not report.rows:
        st.warning(
            "No voyages departed in that month in these files. Check the month, "
            "or add Daily files covering it."
        )

    OUTPUT_DIR.mkdir(exist_ok=True)
    workbook_path = write_workbook(report, OUTPUT_DIR / f"TAO Compare {report.period}.xlsx")
    review_path = write_review_csv(report, OUTPUT_DIR / f"review {report.period}.csv")

    st.download_button(
        "Download TAO Compare workbook",
        data=workbook_path.read_bytes(),
        file_name=workbook_path.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

    st.subheader("Report")
    st.dataframe(
        [
            {
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
            for r in report.rows
        ],
        hide_index=True,
        use_container_width=True,
    )

    unknown = [r for r in report.rows if r.opr == UNKNOWN]
    if unknown:
        st.subheader("Unrecognised operators")
        st.write(
            "These vessels are not in the operator mapping yet. Set each one once "
            "and it will be remembered for future reports."
        )
        mapping = OperatorMapping.load()
        with st.form("operators"):
            choices = {}
            for row in unknown:
                choices[row.vessel_voyage] = st.text_input(
                    f"{row.vessel_voyage} ({row.svc})", key=f"opr-{row.tfc}"
                )
            if st.form_submit_button("Save operators"):
                for vessel, opr in choices.items():
                    if opr.strip():
                        mapping.learn(vessel, opr.strip().upper())
                mapping.save()
                st.success("Saved. Generate the report again to apply them.")

    with st.expander(f"Exceptions ({len(report.review)})"):
        if report.review:
            st.dataframe(
                [item.as_dict() for item in report.review],
                hide_index=True,
                use_container_width=True,
            )
            st.download_button(
                "Download review.csv",
                data=review_path.read_bytes(),
                file_name=review_path.name,
                mime="text/csv",
            )
        else:
            st.write("Nothing to review — every row came from complete source data.")

    with st.expander("Which services were included"):
        st.dataframe(
            [
                {"SVC": svc, "In report": verdict == "in", "Reason": "" if verdict == "in" else verdict}
                for svc, verdict in sorted(report.selection.service_scope.items())
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Edit config/report_scope.json to force a service in or out."
        )
