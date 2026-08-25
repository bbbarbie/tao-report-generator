"""The Needs Review screen.

One card per open question: the voyage, its timestamps, which Daily files it
came from, what is uncertain, the candidate answers, and the recommendation
with its reasoning. Nothing is applied until the user chooses.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.decisions import VESSEL_OPERATOR
from app.review import MISSING_ATD, UNKNOWN_OPERATOR, ReviewIssue

KIND_TITLE = {
    "UNKNOWN_OPERATOR": "不確定是哪一家船公司  Unknown operator",
    "AMBIGUOUS_VOYAGE": "兩筆紀錄可能是同一航次  Possibly one voyage",
    "MISSING_ATD": "沒有離港時間  No departure time",
    "CONFLICTING_SNAPSHOTS": "每日表前後不一致  Daily files disagree",
    "VALUE_DISAGREEMENT": "計算結果與每日表不同  Differs from the Daily",
    "UNCERTAIN_WINDOW": "靠泊窗口不確定  Uncertain berthing window",
    "BERTHED_BEFORE_WINDOW": "比窗口更早靠泊  Berthed before the window",
}
MANUAL_KEYS = {"manual"}


class ReviewView(QWidget):
    back_requested = Signal()

    def __init__(self, store, on_decision) -> None:
        super().__init__()
        self.store = store
        self.on_decision = on_decision
        self.period = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        header = QHBoxLayout()
        back = QPushButton("←  回到報表  Back")
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addStretch(1)
        layout.addLayout(header)

        self.heading = QLabel()
        font = self.heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self.heading.setFont(font)
        layout.addWidget(self.heading)

        self.explainer = QLabel(
            "以下是程式不敢自己決定的項目。可以直接採用建議的選項。\n"
            "「這條船屬於哪家公司」回答一次之後，以後每個月都會自動記得；"
            "其他的只會用在這一個航次、這一個月。"
        )
        self.explainer.setWordWrap(True)
        layout.addWidget(self.explainer)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, stretch=1)

    def show_issues(self, report) -> None:
        self.period = report.period
        self.heading.setText(f"需要確認 Needs Review — {len(report.issues)}")

        container = QWidget()
        column = QVBoxLayout(container)
        column.setSpacing(14)

        if not report.issues:
            done = QLabel("全部確認完畢，沒有待處理的項目。\nNothing left to review.")
            done.setWordWrap(True)
            column.addWidget(done)
        else:
            for issue in report.issues:
                column.addWidget(IssueCard(issue, self.period, self._save))
        column.addStretch(1)
        self.scroll.setWidget(container)

    def _save(self, issue: ReviewIssue, choice: str, note: str, manual) -> None:
        option = issue.option(choice)
        if option is None:
            return
        value, field = option.value, issue.field

        if choice in MANUAL_KEYS:
            if issue.kind == MISSING_ATD:
                try:
                    parsed = datetime.fromisoformat(str(manual).strip())
                except (TypeError, ValueError):
                    QMessageBox.warning(
                        self,
                        "TAO Report Generator",
                        "離港時間請照這個格式輸入：\n2026-07-31 18:47",
                    )
                    return
                self.store.record_override(
                    self.period, issue.voyage_key, "atd", parsed.isoformat(),
                    issue.kind, choice, note,
                )
                value, field = True, "include"
            else:
                value = float(manual)

        if issue.reusable and issue.kind == UNKNOWN_OPERATOR:
            self.store.record_rule(
                VESSEL_OPERATOR, issue.target, field, value, choice, note
            )
        else:
            self.store.record_override(
                self.period, issue.voyage_key, field, value, issue.kind, choice, note
            )
        self.on_decision()


class IssueCard(QFrame):
    """One question, with everything needed to answer it."""

    def __init__(self, issue: ReviewIssue, period: str, save) -> None:
        super().__init__()
        self.issue = issue
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: #fbfbfb; border: 1px solid #dcdcdc; "
            "border-radius: 6px; padding: 6px; }"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        mark = "🚩 " if issue.blocking else ""
        title = QLabel(
            f"{mark}{KIND_TITLE.get(issue.kind, issue.kind)}　—　"
            f"{issue.svc or '?'} {issue.tfc or issue.voyage_key}"
        )
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        question = QLabel(issue.question)
        question.setWordWrap(True)
        layout.addWidget(question)

        layout.addWidget(self._evidence())

        if issue.recommended:
            advice = QLabel(
                f"建議 Recommended：{issue.recommended.label}\n{issue.why_recommended}"
            )
            advice.setWordWrap(True)
            advice.setStyleSheet(
                "QFrame, QLabel { background: #eef4fb; border: none; padding: 6px; }"
            )
            layout.addWidget(advice)
        else:
            advice = QLabel(
                "沒有建議選項 — 這一項需要您對船舶的了解。\n"
                "No recommendation: the evidence does not favour one answer."
            )
            advice.setWordWrap(True)
            layout.addWidget(advice)

        self.group = QButtonGroup(self)
        for index, option in enumerate(issue.options):
            button = QRadioButton(
                f"{option.label}" + (f"　（{option.rationale}）" if option.rationale else "")
            )
            button.setChecked(bool(option.recommended) or (index == 0 and not issue.recommended))
            self.group.addButton(button, index)
            layout.addWidget(button)

        self.manual: QWidget | None = None
        if any(o.key in MANUAL_KEYS for o in issue.options):
            if issue.kind == MISSING_ATD:
                self.manual = QLineEdit()
                self.manual.setPlaceholderText("2026-07-31 18:47")
            else:
                self.manual = QDoubleSpinBox()
                self.manual.setRange(-100000, 100000)
                self.manual.setDecimals(1)
            layout.addWidget(self.manual)

        self.note = QLineEdit()
        self.note.setPlaceholderText("備註（可不填）  Note (optional)")
        layout.addWidget(self.note)

        confirm = QPushButton("確認  Save decision")
        confirm.clicked.connect(lambda: save(issue, self._choice(), self.note.text(), self._manual()))
        layout.addWidget(confirm, alignment=Qt.AlignLeft)

    def _evidence(self) -> QLabel:
        lines = [f"船名 Vessel：{self.issue.vessel or '—'}"]
        lines += [
            f"{name}：{value:%m/%d %H:%M}" if value else f"{name}：—"
            for name, value in self.issue.timestamps.items()
        ]
        files = self.issue.source_files
        lines.append(
            f"資料來源 Source：{len(files)} 個檔案 — "
            + ", ".join(files[:3])
            + (" …" if len(files) > 3 else "")
        )
        lines += list(self.issue.evidence)
        label = QLabel("\n".join(lines))
        label.setWordWrap(True)
        label.setStyleSheet("QLabel { color: #555; border: none; }")
        return label

    def _choice(self) -> str:
        index = self.group.checkedId()
        return self.issue.options[index].key if index >= 0 else self.issue.options[0].key

    def _manual(self):
        if self.manual is None:
            return None
        if isinstance(self.manual, QLineEdit):
            return self.manual.text()
        return self.manual.value()
