"""Command line entry point.

    python -m app.cli --daily samples/daily --month 2026-07
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from app.calculations import AUTO, REVIEWED, UNRESOLVED
from app.generator import write_workbook
from app.operators import OperatorMapping
from app.parser import discover_daily_files
from app.report import MonthlyReport, build_report
from app.selection import ScopeConfig

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_month(text: str) -> tuple[int, int]:
    cleaned = text.strip().replace("/", "-")
    if "-" in cleaned:
        year, month = cleaned.split("-", 1)
    elif len(cleaned) == 6:
        year, month = cleaned[:4], cleaned[4:]
    else:
        raise argparse.ArgumentTypeError(
            f"cannot read a month from {text!r}; use 2026-07 or 202607"
        )
    try:
        y, m = int(year), int(month)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"cannot read a month from {text!r}") from exc
    if not 1 <= m <= 12:
        raise argparse.ArgumentTypeError(f"{m} is not a month")
    return y, m


def collect_daily_files(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            files.extend(discover_daily_files(item))
        elif item.exists():
            files.append(item)
        else:
            raise SystemExit(f"no such file or folder: {item}")
    if not files:
        raise SystemExit("no Daily workbooks found")
    return sorted(set(files))


def write_review_csv(report: MonthlyReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["TFC", "SVC", "Vessel", "Reason", "Detail"])
        writer.writeheader()
        for item in report.review:
            writer.writerow(item.as_dict())
    return path


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tao-report-generator",
        description="Build a TAO Compare workbook from Daily Berth Report files.",
    )
    ap.add_argument(
        "--daily",
        type=Path,
        nargs="+",
        default=[REPO_ROOT / "samples" / "daily"],
        help="Daily workbooks, or folders containing them",
    )
    ap.add_argument("--month", required=True, help="target month, e.g. 2026-07")
    ap.add_argument("--output-dir", type=Path, default=REPO_ROOT / "output")
    ap.add_argument("--operators", type=Path, default=None, help="operator mapping JSON")
    ap.add_argument("--scope", type=Path, default=None, help="report scope JSON")
    ap.add_argument(
        "--validate-against",
        type=Path,
        default=None,
        help="a known-good TAO Compare workbook to check the result against",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    year, month = parse_month(args.month)
    files = collect_daily_files(args.daily)

    report = build_report(
        files,
        year,
        month,
        mapping=OperatorMapping.load(args.operators),
        scope=ScopeConfig.load(args.scope),
    )

    out_dir = Path(args.output_dir)
    workbook = write_workbook(report, out_dir / f"TAO Compare {report.period}.xlsx")
    review = write_review_csv(report, out_dir / f"review {report.period}.csv")

    print(f"Read {len(files)} Daily files -> {len(report.index.histories)} voyages")
    print(f"{len(report.rows)} voyages in {report.period}")
    print(f"  {len(report.rows_by_resolution(AUTO))} automatic")
    print(f"  {len(report.rows_by_resolution(REVIEWED))} reviewed")
    print(f"  {len(report.rows_by_resolution(UNRESOLVED))} unresolved")

    if report.issues:
        blocking = len(report.blocking_issues)
        print()
        print(f"{len(report.issues)} open questions ({blocking} would leave a field empty):")
        for issue in report.issues:
            recommended = issue.recommended
            mark = "!" if issue.blocking else "-"
            print(f"  {mark} {issue.svc or '?':4} {issue.tfc or issue.voyage_key}")
            print(f"      {issue.question}")
            if recommended:
                print(f"      suggested: {recommended.label}")
        print()
        print("Answer these on the Needs Review screen: streamlit run ui.py")

    print(f"wrote {workbook}")
    print(f"wrote {review}")

    if args.validate_against:
        from app.validation import compare, load_ground_truth

        result = compare(report, load_ground_truth(args.validate_against))
        print()
        print(result.summary())
        (out_dir / f"validation {report.period}.json").write_text(
            result.to_json(), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
