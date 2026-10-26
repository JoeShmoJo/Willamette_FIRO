"""
Create a compact human-review package from FIRO model outputs.

This script does not move, rename, or delete existing technical outputs.
It creates outputs/review/, which is the recommended location for normal
allocation, redistribution, and QA/QC review.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
REVIEW_DIRECTORY = OUTPUT_DIRECTORY / "review"

TOLERANCE_KAF = 1.0e-6


FILES = {
    "redistribution_summary": (
        OUTPUT_DIRECTORY / "47_redistribution_optimization_summary.csv"
    ),
    "allocation_qaqc": (
        OUTPUT_DIRECTORY / "44_allocation_qaqc_summary.csv"
    ),
    "baseline_control_points": (
        OUTPUT_DIRECTORY / "45_control_point_utilization_baseline.csv"
    ),
    "redistributed_control_points": (
        OUTPUT_DIRECTORY / "46_control_point_utilization_redistributed.csv"
    ),
    "redistributed_physical": (
        OUTPUT_DIRECTORY / "43_redistributed_physical_project_allocations.csv"
    ),
    "static_allocation_quality": (
        OUTPUT_DIRECTORY / "27_static_allocation_quality_report.csv"
    ),
    "component_curve_quality": (
        OUTPUT_DIRECTORY / "34_component_curve_quality_report.csv"
    ),
    "curve_cap_quality": (
        OUTPUT_DIRECTORY / "39_curve_cap_quality_report.csv"
    ),
}


def read_csv_if_present(path: Path) -> pd.DataFrame:
    """Return an empty DataFrame if an optional review source does not exist."""
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path)


def require_file(name: str) -> Path:
    path = FILES[name]

    if not path.exists():
        raise FileNotFoundError(
            f"Required review source file does not exist:\n  {path}"
        )

    return path


def write_csv(dataframe: pd.DataFrame, filename: str) -> Path:
    path = REVIEW_DIRECTORY / filename
    dataframe.to_csv(path, index=False)
    return path


def build_alternative_summary(
    optimization_summary: pd.DataFrame,
    allocation_qaqc: pd.DataFrame,
) -> pd.DataFrame:
    """
    One row per alternative: baseline total, redistributed total, gain,
    and the count of decision units that received additional FIRO space.
    """
    summary = optimization_summary.copy()

    changed_counts = (
        allocation_qaqc.assign(
            received_redistribution=lambda data: (
                data["redistribution_increase_kaf"] > TOLERANCE_KAF
            )
        )
        .groupby("alternative_id", as_index=False)
        .agg(
            decision_units_receiving_redistribution=(
                "received_redistribution",
                "sum",
            ),
            largest_decision_unit_increase_kaf=(
                "redistribution_increase_kaf",
                "max",
            ),
        )
    )

    summary = summary.merge(
        changed_counts,
        on="alternative_id",
        how="left",
    )

    summary["decision_units_receiving_redistribution"] = (
        summary["decision_units_receiving_redistribution"]
        .fillna(0)
        .astype(int)
    )

    return summary.sort_values("alternative_id")


def build_decision_unit_changes(
    allocation_qaqc: pd.DataFrame,
) -> pd.DataFrame:
    """
    Keep only decision units whose allocation changes after redistribution.
    """
    columns = [
        "alternative_id",
        "alternative_name",
        "decision_unit_id",
        "decision_unit_name",
        "active_components",
        "baseline_firo_space_kaf",
        "redistributed_firo_space_kaf",
        "redistribution_increase_kaf",
        "effective_physical_cap_kaf",
        "unused_physical_capacity_kaf_after_redistribution",
        "limiting_control_points",
        "redistributed_limiting_control_points",
        "optimization_status",
    ]

    columns = [
        column
        for column in columns
        if column in allocation_qaqc.columns
    ]

    changes = allocation_qaqc.loc[
        allocation_qaqc["redistribution_increase_kaf"] > TOLERANCE_KAF,
        columns,
    ].copy()

    return changes.sort_values(
        [
            "alternative_id",
            "redistribution_increase_kaf",
            "decision_unit_id",
        ],
        ascending=[True, False, True],
    )


def build_project_changes(
    redistributed_physical: pd.DataFrame,
) -> pd.DataFrame:
    """
    Keep only physical reservoirs receiving redistributed FIRO space.
    """
    required_column = "project_redistribution_increase_kaf"

    if required_column not in redistributed_physical.columns:
        return pd.DataFrame()

    columns = [
        "alternative_id",
        "alternative_name",
        "project_id",
        "project_name",
        "decision_unit_id",
        "active_components",
        "baseline_project_firo_space_kaf",
        "redistributed_project_firo_space_kaf",
        "project_redistribution_increase_kaf",
        "project_physical_cap_kaf",
        "project_physical_cap_exceeded",
    ]

    columns = [
        column
        for column in columns
        if column in redistributed_physical.columns
    ]

    changes = redistributed_physical.loc[
        redistributed_physical[required_column] > TOLERANCE_KAF,
        columns,
    ].copy()

    return changes.sort_values(
        [
            "alternative_id",
            required_column,
            "project_id",
        ],
        ascending=[True, False, True],
    )


def build_control_point_comparison(
    baseline: pd.DataFrame,
    redistributed: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compare baseline and redistributed control-point utilization side by side.
    """
    join_columns = [
        "alternative_id",
        "alternative_name",
        "control_point_id",
        "control_point_name",
        "space_limit_kaf",
    ]

    baseline_columns = join_columns + [
        "allocated_firo_space_kaf",
        "unused_control_point_space_kaf",
        "utilization_fraction",
    ]

    redistributed_columns = join_columns + [
        "allocated_firo_space_kaf",
        "unused_control_point_space_kaf",
        "utilization_fraction",
    ]

    baseline_view = baseline[baseline_columns].rename(
        columns={
            "allocated_firo_space_kaf": (
                "baseline_allocated_firo_space_kaf"
            ),
            "unused_control_point_space_kaf": (
                "baseline_unused_control_point_space_kaf"
            ),
            "utilization_fraction": (
                "baseline_utilization_fraction"
            ),
        }
    )

    redistributed_view = redistributed[redistributed_columns].rename(
        columns={
            "allocated_firo_space_kaf": (
                "redistributed_allocated_firo_space_kaf"
            ),
            "unused_control_point_space_kaf": (
                "redistributed_unused_control_point_space_kaf"
            ),
            "utilization_fraction": (
                "redistributed_utilization_fraction"
            ),
        }
    )

    comparison = baseline_view.merge(
        redistributed_view,
        on=join_columns,
        how="outer",
        validate="one_to_one",
    )

    comparison["allocation_change_kaf"] = (
        comparison["redistributed_allocated_firo_space_kaf"]
        - comparison["baseline_allocated_firo_space_kaf"]
    )

    comparison["newly_binding_after_redistribution"] = (
        comparison["redistributed_unused_control_point_space_kaf"]
        <= TOLERANCE_KAF
    )

    return comparison.sort_values(
        [
            "alternative_id",
            "allocation_change_kaf",
            "control_point_id",
        ],
        ascending=[True, False, True],
    )


def extract_quality_exceptions(
    source_name: str,
    quality_data: pd.DataFrame,
) -> pd.DataFrame:
    """
    Extract review-relevant rows from a quality report without assuming
    every report has the same schema.
    """
    if quality_data.empty:
        return pd.DataFrame()

    data = quality_data.copy()
    data.insert(0, "source_report", source_name)

    if "severity" in data.columns:
        severity = data["severity"].fillna("").astype(str).str.upper()

        # Keep warnings/errors and any other non-INFO severity.
        return data.loc[severity != "INFO"].copy()

    if "status" in data.columns:
        status = data["status"].fillna("").astype(str).str.upper()

        passing_values = {
            "PASS",
            "OK",
            "SUCCESS",
            "INFO",
            "VALID",
        }

        return data.loc[~status.isin(passing_values)].copy()

    # If the report has no recognizable severity/status field, retain it
    # in the review package because it is probably already exception-focused.
    return data


def write_readme(
    alternative_summary: pd.DataFrame,
    decision_changes: pd.DataFrame,
    project_changes: pd.DataFrame,
    control_point_comparison: pd.DataFrame,
    quality_exceptions: pd.DataFrame,
) -> None:
    text = f"""FIRO REVIEW PACKAGE
===================

Purpose
-------
This folder is the normal human-review location for the FIRO model.
The numbered files in the parent outputs folder remain technical
traceability and model-working files.

Open these files first
----------------------
1. index.html
   One-page index linking to every targeted review output.

2. 01_alternative_summary.csv
   One row per alternative. Shows total baseline FIRO space, total
   redistributed FIRO space, the system increase, and the number of
   decision units receiving redistributed space.

3. 02_decision_unit_changes.csv
   Only decision units whose allocations increased after redistribution.

4. 03_project_changes.csv
   Only physical reservoirs whose allocated FIRO space increased after
   redistribution. This is the key input for reviewing changed component
   curves later.

5. 04_control_point_comparison.csv
   Baseline and redistributed control-point utilization side by side.

6. 05_quality_exceptions.csv
   Warnings, errors, or non-passing rows gathered from existing QA/QC reports.

Current review counts
---------------------
Alternatives:                         {len(alternative_summary):,}
Decision units receiving space:       {len(decision_changes):,}
Physical projects receiving space:    {len(project_changes):,}
Control-point comparison rows:        {len(control_point_comparison):,}
Quality/QA exceptions:                {len(quality_exceptions):,}

Important
---------
- No source, model, or existing output file was moved or deleted.
- Baseline means no redistribution after a project/decision unit reaches
  its physical cap.
- Redistributed means the constrained optimization case.
- Plotly geometry review remains in:
      ../plotly_component_review/index.html
"""

    (REVIEW_DIRECTORY / "README_review_package.txt").write_text(
        text,
        encoding="utf-8",
    )


def write_html_index(
    alternative_summary: pd.DataFrame,
    decision_changes: pd.DataFrame,
    project_changes: pd.DataFrame,
    quality_exceptions: pd.DataFrame,
) -> None:
    alternative_rows = []

    for row in alternative_summary.itertuples():
        alternative_rows.append(
            "<tr>"
            f"<td>{row.alternative_id}</td>"
            f"<td>{escape(str(row.alternative_name))}</td>"
            f"<td>{row.baseline_total_firo_space_kaf:,.3f}</td>"
            f"<td>{row.redistributed_total_firo_space_kaf:,.3f}</td>"
            f"<td>{row.total_redistribution_increase_kaf:,.3f}</td>"
            f"<td>{row.decision_units_receiving_redistribution}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FIRO Targeted Review Package</title>
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 32px;
    color: #1f2933;
}}
h1, h2 {{
    color: #12355b;
}}
table {{
    border-collapse: collapse;
    min-width: 950px;
}}
th, td {{
    border: 1px solid #c8d1dc;
    padding: 8px 12px;
    text-align: left;
}}
th {{
    background: #dce9f6;
}}
tr:nth-child(even) {{
    background: #f7f9fb;
}}
a {{
    color: #0645ad;
    font-weight: 600;
}}
.note {{
    background: #fff7d6;
    border-left: 5px solid #d59f00;
    padding: 12px;
    max-width: 950px;
}}
</style>
</head>
<body>
<h1>FIRO Targeted Review Package</h1>

<div class="note">
Use this folder for normal model review. The numbered files in the parent
<code>outputs</code> folder remain technical traceability files and do not
need to be opened routinely. Daily charts below use baseline allocations; the summary tables also show the separate redistribution case. All daily loading is unrouted storage-space screening.
</div>

<h2>Review Files</h2>
<ul>
<li><a href="utilization_ribbon_overview/index.html">Start here: FIRO utilization overview</a> — baseline daily space, relative to physical/control-point capacities.</li>
<li><a href="constraint_controller_overview/index.html">Constraint and component-controller diagnostics</a> — what limits or controls the daily envelope.</li>

<li><a href="01_alternative_summary.csv">01_alternative_summary.csv</a>
— alternative-level baseline versus redistribution results.</li>
<li><a href="02_decision_unit_changes.csv">02_decision_unit_changes.csv</a>
— only decision units receiving additional FIRO space.</li>
<li><a href="03_project_changes.csv">03_project_changes.csv</a>
— only physical projects receiving additional FIRO space.</li>
<li><a href="04_control_point_comparison.csv">04_control_point_comparison.csv</a>
— baseline and redistributed control-point use side by side.</li>
<li><a href="05_quality_exceptions.csv">05_quality_exceptions.csv</a>
— warnings, errors, and non-passing QA/QC rows.</li>
<li><a href="README_review_package.txt">README_review_package.txt</a>
— plain-text explanation of the review package.</li>
<li><a href="../plotly_component_review/index.html">Plotly Component Review</a>
— interactive component geometry pages.</li>
</ul>

<h2>Alternative Summary</h2>
<table>
<thead>
<tr>
<th>Alternative</th>
<th>Name</th>
<th>Baseline FIRO (KAF)</th>
<th>Redistributed FIRO (KAF)</th>
<th>Increase (KAF)</th>
<th>Decision Units Receiving Space</th>
</tr>
</thead>
<tbody>
{''.join(alternative_rows)}
</tbody>
</table>

<h2>Review Counts</h2>
<ul>
<li>Decision-unit allocation changes: {len(decision_changes):,}</li>
<li>Physical-project allocation changes: {len(project_changes):,}</li>
<li>Quality/QA exceptions: {len(quality_exceptions):,}</li>
</ul>

</body>
</html>
"""

    (REVIEW_DIRECTORY / "index.html").write_text(
        html,
        encoding="utf-8",
    )


def main() -> None:
    REVIEW_DIRECTORY.mkdir(parents=True, exist_ok=True)

    optimization_summary = pd.read_csv(
        require_file("redistribution_summary")
    )
    allocation_qaqc = pd.read_csv(
        require_file("allocation_qaqc")
    )
    baseline_control_points = pd.read_csv(
        require_file("baseline_control_points")
    )
    redistributed_control_points = pd.read_csv(
        require_file("redistributed_control_points")
    )
    redistributed_physical = pd.read_csv(
        require_file("redistributed_physical")
    )

    alternative_summary = build_alternative_summary(
        optimization_summary=optimization_summary,
        allocation_qaqc=allocation_qaqc,
    )

    decision_changes = build_decision_unit_changes(
        allocation_qaqc=allocation_qaqc,
    )

    project_changes = build_project_changes(
        redistributed_physical=redistributed_physical,
    )

    control_point_comparison = build_control_point_comparison(
        baseline=baseline_control_points,
        redistributed=redistributed_control_points,
    )

    quality_parts = []

    for source_name, file_key in [
        (
            "27_static_allocation_quality_report.csv",
            "static_allocation_quality",
        ),
        (
            "34_component_curve_quality_report.csv",
            "component_curve_quality",
        ),
        (
            "39_curve_cap_quality_report.csv",
            "curve_cap_quality",
        ),
    ]:
        quality_data = read_csv_if_present(FILES[file_key])

        exceptions = extract_quality_exceptions(
            source_name=source_name,
            quality_data=quality_data,
        )

        if not exceptions.empty:
            quality_parts.append(exceptions)

    quality_exceptions = (
        pd.concat(quality_parts, ignore_index=True, sort=False)
        if quality_parts
        else pd.DataFrame(
            columns=[
                "source_report",
                "message",
            ]
        )
    )

    write_csv(
        alternative_summary,
        "01_alternative_summary.csv",
    )
    write_csv(
        decision_changes,
        "02_decision_unit_changes.csv",
    )
    write_csv(
        project_changes,
        "03_project_changes.csv",
    )
    write_csv(
        control_point_comparison,
        "04_control_point_comparison.csv",
    )
    write_csv(
        quality_exceptions,
        "05_quality_exceptions.csv",
    )

    write_readme(
        alternative_summary=alternative_summary,
        decision_changes=decision_changes,
        project_changes=project_changes,
        control_point_comparison=control_point_comparison,
        quality_exceptions=quality_exceptions,
    )

    write_html_index(
        alternative_summary=alternative_summary,
        decision_changes=decision_changes,
        project_changes=project_changes,
        quality_exceptions=quality_exceptions,
    )

    print()
    print("=" * 72)
    print("FIRO TARGETED REVIEW PACKAGE COMPLETE")
    print("=" * 72)
    print(f"Review folder: {REVIEW_DIRECTORY}")
    print(f"Alternatives summarized: {len(alternative_summary):,}")
    print(f"Decision-unit changes:   {len(decision_changes):,}")
    print(f"Physical-project changes:{len(project_changes):,}")
    print(f"QA/QC exceptions:        {len(quality_exceptions):,}")
    print()
    print("Open this file first:")
    print(f"  {REVIEW_DIRECTORY / 'index.html'}")


if __name__ == "__main__":
    main()