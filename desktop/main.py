"""TAO Report Generator — Windows desktop application.

Three steps, in order: choose where the Daily files live, choose a month,
process. Anything the engine is unsure about is asked before the report is
written, never guessed at.

This module is views and wiring only. Every figure comes from ``app/``.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.calculations import AUTO, REVIEWED, UNRESOLVED
from app.decisions import DecisionStore
from app.generator import write_workbook
from app.operators import OperatorMapping
from app.parser import discover_daily_files
from app.report import MonthlyReport, build_report
from app.selection import ScopeConfig
from app.settings import Settings
from desktop.review_view import ReviewView

APP_NAME = "TAO Report Generator"

STATUS_COLOUR = {
    AUTO: None,
    REVIEWED: QColor("#e8f3e8"),
    UNRESOLVED: QColor("#fdf0dc"),
}
STATUS_TEXT = {
    AUTO: "自動 Automatic",
    REVIEWED: "已確認 Reviewed",
    UNRESOLVED: "待確認 Unresolved",
}

COLUMNS = [
    ("狀態 Status", lambda r: STATUS_TEXT.get(r.resolution, r.resolution)),
    ("SVC", lambda r: r.svc),
    ("TFC Code", lambda r: r.tfc),
    ("OPR", lambda r: r.opr),
    ("靠泊碼頭", lambda r: r.terminal),
    ("ATA", lambda r: _moment(r.ata)),
    ("ATB", lambda r: _moment(r.atb)),
    ("Arr Delay (hr)", lambda r: _number(r.arr_delay.value)),
    ("Dep Delay (Hr)", lambda r: _number(r.dep_delay.value)),
    ("W/B (hr)", lambda r: _number(r.waiting.value)),
    ("平均侯泊時間", lambda r: _number(r.average_waiting)),
]


def _moment(value) -> str:
    return value.strftime("%m/%d %H:%M") if value else ""


def _number(value) -> str:
    return "" if value is None else f"{value:g}"


class ProcessWorker(QThread):
    """Reading two dozen workbooks takes seconds; keep the window responsive."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, files, year, month, store, parent=None):
        # Parented to the window so Qt owns it: an unparented QThread that
        # outlives the Python reference is destroyed while still running,
        # which takes the process down with it.
        super().__init__(parent)
        self._files, self._year, self._month, self._store = files, year, month, store

    def run(self) -> None:
        try:
            report = build_report(
                self._files,
                self._year,
                self._month,
                OperatorMapping.load(),
                ScopeConfig.load(),
                self._store,
            )
            self.finished_ok.emit(report)
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(
        self, settings: Settings | None = None, store: DecisionStore | None = None
    ) -> None:
        # Both are injectable so a test can point them at scratch files rather
        # than the real ones sitting next to the application.
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)

        self.settings = settings if settings is not None else Settings.load()
        self.store = store if store is not None else DecisionStore.load()
        self.report: MonthlyReport | None = None
        self.files: list[Path] = []
        self.worker: ProcessWorker | None = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.stack.addWidget(self._build_main_page())
        self.review = ReviewView(self.store, self._after_decision)
        self.stack.addWidget(self.review)

        self._restore_settings()

    # --- layout ------------------------------------------------------------

    def _build_main_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(APP_NAME)
        font = title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        layout.addWidget(
            QLabel("所有資料都留在這台電腦上。All data stays on this computer.")
        )

        layout.addWidget(self._build_step1())
        layout.addWidget(self._build_step2())

        self.process_button = QPushButton("開始處理  Process")
        self.process_button.setMinimumHeight(38)
        # Nothing to process until a folder with Daily files has been chosen.
        self.process_button.setEnabled(False)
        self.process_button.clicked.connect(self.process)
        layout.addWidget(self.process_button)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.review_button = QPushButton("")
        self.review_button.clicked.connect(self._open_review)
        self.review_button.hide()
        layout.addWidget(self.review_button)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([name for name, _ in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        layout.addWidget(self.table, stretch=1)

        self.save_button = QPushButton("產生報表  Generate TAO Compare.xlsx")
        self.save_button.setMinimumHeight(38)
        self.save_button.clicked.connect(self.save_report)
        self.save_button.setEnabled(False)
        layout.addWidget(self.save_button)

        return page

    def _build_step1(self) -> QGroupBox:
        box = QGroupBox("1. 每日船舶動態表資料夾  Daily files folder")
        row = QHBoxLayout(box)
        self.folder_label = QLabel("尚未選擇  Not chosen yet")
        self.folder_label.setWordWrap(True)
        row.addWidget(self.folder_label, stretch=1)
        choose = QPushButton("選擇資料夾  Choose…")
        choose.clicked.connect(self.choose_folder)
        row.addWidget(choose)
        return box

    def _build_step2(self) -> QGroupBox:
        box = QGroupBox("2. 選擇月份  Month")
        row = QHBoxLayout(box)
        self.year_input = QSpinBox()
        self.year_input.setRange(2000, 2100)
        self.month_input = QComboBox()
        for m in range(1, 13):
            self.month_input.addItem(f"{m:02d}", m)
        row.addWidget(QLabel("年 Year"))
        row.addWidget(self.year_input)
        row.addSpacing(16)
        row.addWidget(QLabel("月 Month"))
        row.addWidget(self.month_input)
        row.addStretch(1)
        return box

    # --- settings ----------------------------------------------------------

    def _restore_settings(self) -> None:
        year, month = self.settings.suggested_period()
        self.year_input.setValue(year)
        self.month_input.setCurrentIndex(month - 1)
        if self.settings.daily_path:
            self._set_folder(self.settings.daily_path)

    def _set_folder(self, folder: Path) -> None:
        self.files = discover_daily_files(folder)
        self.settings.daily_folder = str(folder)
        self.settings.save()
        if self.files:
            self.folder_label.setText(
                f"{folder}\n找到 {len(self.files)} 個檔案 — "
                f"{self.files[0].name} … {self.files[-1].name}"
            )
        else:
            self.folder_label.setText(
                f"{folder}\n這個資料夾裡沒有找到每日船舶動態表。"
            )
        self.process_button.setEnabled(bool(self.files))

    def choose_folder(self) -> None:
        start = self.settings.daily_folder or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "選擇每日船舶動態表資料夾", start
        )
        if chosen:
            self._set_folder(Path(chosen))

    # --- processing --------------------------------------------------------

    def process(self) -> None:
        if not self.files:
            return
        year = self.year_input.value()
        month = self.month_input.currentData()

        self.process_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.review_button.hide()
        self.status.setText("處理中，請稍候…  Reading Daily files…")

        self.worker = ProcessWorker(self.files, year, month, self.store, parent=self)
        self.worker.finished_ok.connect(self._processed)
        self.worker.failed.connect(self._process_failed)
        self.worker.start()

    def closeEvent(self, event) -> None:
        """Let a run in progress finish before the window goes away."""
        worker = self.worker
        if worker is not None and worker.isRunning():
            worker.wait(30_000)
        super().closeEvent(event)

    def _process_failed(self, detail: str) -> None:
        self.process_button.setEnabled(True)
        self.status.setText("處理時發生問題。")
        QMessageBox.critical(
            self,
            APP_NAME,
            "處理時發生問題，報表沒有產生。\n\n"
            "請確認選擇的資料夾裡是每日船舶動態表。\n\n"
            f"技術細節：\n{detail.strip().splitlines()[-1]}",
        )

    def _processed(self, report: MonthlyReport) -> None:
        self.report = report
        self.process_button.setEnabled(True)
        self.settings.remember_period(report.year, report.month)
        self.settings.save()
        self._refresh()

    def _after_decision(self) -> None:
        """Re-run with the new decision applied, then come back to the report."""
        if self.report is None:
            return
        self.store.save()
        self.report = build_report(
            self.files,
            self.report.year,
            self.report.month,
            OperatorMapping.load(),
            ScopeConfig.load(),
            self.store,
        )
        self.review.show_issues(self.report)
        self._refresh()

    def _refresh(self) -> None:
        report = self.report
        if report is None:
            return

        counts = {s: len(report.rows_by_resolution(s)) for s in STATUS_TEXT}
        self.status.setText(
            f"{report.period[:4]}-{report.period[4:]}：共 {len(report.rows)} 航次　"
            f"自動 {counts[AUTO]}　已確認 {counts[REVIEWED]}　"
            f"待確認 {counts[UNRESOLVED]}"
        )

        if report.issues:
            self.review_button.setText(
                f"有 {len(report.issues)} 筆需要您確認  →  Review {len(report.issues)} items"
            )
            self.review_button.show()
        else:
            self.review_button.hide()

        self.table.setRowCount(len(report.rows))
        for r, row in enumerate(report.rows):
            colour = STATUS_COLOUR.get(row.resolution)
            for c, (_, extract) in enumerate(COLUMNS):
                item = QTableWidgetItem(str(extract(row) or ""))
                item.setTextAlignment(Qt.AlignCenter)
                if colour is not None:
                    item.setBackground(colour)
                if c == 0 and row.resolution != AUTO:
                    bold = QFont()
                    bold.setBold(True)
                    item.setFont(bold)
                self.table.setItem(r, c, item)

        self.save_button.setEnabled(bool(report.rows))
        if not report.rows:
            QMessageBox.information(
                self,
                APP_NAME,
                "這個月份沒有找到任何離港的航次。\n\n"
                "請確認月份是否正確，或資料夾裡是否有該月份的每日船舶動態表。",
            )

    def _open_review(self) -> None:
        if self.report is None:
            return
        self.review.show_issues(self.report)
        self.stack.setCurrentIndex(1)

    def show_main(self) -> None:
        self.stack.setCurrentIndex(0)

    # --- output ------------------------------------------------------------

    def save_report(self) -> None:
        report = self.report
        if report is None:
            return
        default_dir = self.settings.output_folder or str(Path.home())
        target, _ = QFileDialog.getSaveFileName(
            self,
            "儲存報表",
            str(Path(default_dir) / f"TAO Compare {report.period}.xlsx"),
            "Excel (*.xlsx)",
        )
        if not target:
            return
        try:
            written = write_workbook(report, Path(target))
        except OSError as exc:
            QMessageBox.critical(
                self,
                APP_NAME,
                "報表沒有存成功。\n\n"
                "可能是檔案正在 Excel 中開啟，請先關閉再試一次。\n\n"
                f"技術細節：{exc}",
            )
            return

        self.settings.output_folder = str(written.parent)
        self.settings.save()

        note = ""
        if report.issues:
            note = (
                f"\n\n還有 {len(report.issues)} 筆沒有確認，"
                "在報表中以淡橘色標示。"
            )
        QMessageBox.information(
            self, APP_NAME, f"報表已儲存：\n{written}{note}"
        )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        from desktop.selftest import main as selftest

        return selftest()

    application = QApplication(sys.argv[:1])
    application.setApplicationName(APP_NAME)
    window = MainWindow()
    window.review.back_requested.connect(window.show_main)
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
