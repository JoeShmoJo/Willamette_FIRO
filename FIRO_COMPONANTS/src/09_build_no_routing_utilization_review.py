"""
Build no-routing daily FIRO-space utilization review products.

This is a storage-space screening tool, not a routed-flow model.

Assumptions:
- Same-day aggregation.
- No reach travel time.
- No routing attenuation.
- No local inflows.
- No operational release routing.

Outputs:
    outputs/review/no_routing_utilization/
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# =============================================================================
# PATHS AND SETTINGS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

REVIEW_DIRECTORY = (
    OUTPUT_DIRECTORY
    / "review"
    / "no_routing_utilization"
)

CAPPED_DAILY_FILE = (
    OUTPUT_DIRECTORY
    / "36_project_combined_daily_curves_capped.csv"
)

RAW_DAILY_FILE = (
    OUTPUT_DIRECTORY
    / "32_project_combined_daily_curves.csv"
)

ALLOCATION_FILE = (
    OUTPUT_DIRECTORY
    / "24_alternative_decision_unit_allocations.csv"
)

RELATIONSHIP_FILE = (
    OUTPUT_DIRECTORY
    / "21_static_control_point_relationships.csv"
)

INCLUDE_PLOTLY_JS = "directory"
TOLERANCE_KAF = 1.0e-6


# =============================================================================
# HELPERS
# =============================================================================

def choose_daily_file() -> Path:
    """Prefer capped combined curves; otherwise use raw combined curves."""
    if CAPPED_DAILY_FILE.exists():
        return CAPPED_DAILY_FILE

    if RAW_DAILY_FILE.exists():
        return RAW_DAILY_FILE

    raise FileNotFoundError(
        "Could not find either daily combined-curve input:\n"
        f"  {CAPPED_DAILY_FILE}\n"
        f"  {RAW_DAILY_FILE}"
    )


def safe_filename(value: str) -> str:
    """Convert a label to a safe file-name fragment."""
    return (
        str(value)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def write_figure(figure: go.Figure, output_path: Path) -> None:
    """Write a standalone, locally usable Plotly page."""
    figure.write_html(
        output_path,
        include_plotlyjs=INCLUDE_PLOTLY_JS,
        full_html=True,
    )


def add_limit_line(
    figure: go.Figure,
    dates: pd.Series,
    limit_kaf: float,
    row: int,
    name: str,
) -> None:
    """Add a dashed FIRO-space limit line to a Plotly subplot."""
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=[limit_kaf] * len(dates),
            mode="lines",
            name=name,
            line=dict(
                color="#111111",
                width=2.5,
                dash="dash",
            ),
            hovertemplate=(
                "<b>Static Limit</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Limit: %{y:.2f} KAF<extra></extra>"
            ),
        ),
        row=row,
        col=1,
    )


# =============================================================================
# PLOT BUILDERS
# =============================================================================

def build_reservoir_figure(
    alternative_id: int,
    alternative_name: str,
    reservoir_data: pd.DataFrame,
) -> go.Figure:
    """
    Create short individual line plots for each physical reservoir.

    Each reservoir gets:
        - daily combined FIRO-space offset line;
        - y-axis from 0 to its assigned FIRO-space limit;
        - dashed horizontal limit line.
    """
    reservoir_data = reservoir_data.sort_values("date").copy()

    capacity_by_project = (
        reservoir_data[
            [
                "project_id",
                "project_name",
                "allocated_project_firo_space_kaf",
            ]
        ]
        .drop_duplicates()
        .sort_values("project_name")
    )

    project_count = len(capacity_by_project)

    figure = make_subplots(
        rows=project_count,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.018,
        subplot_titles=[
            (
                f"{row.project_name} - Assigned FIRO Space: "
                f"{row.allocated_project_firo_space_kaf:.2f} KAF"
            )
            for row in capacity_by_project.itertuples()
        ],
    )

    for row_number, project_row in enumerate(
        capacity_by_project.itertuples(),
        start=1,
    ):
        project_id = project_row.project_id
        project_name = project_row.project_name
        limit_kaf = float(
            project_row.allocated_project_firo_space_kaf
        )

        project_data = reservoir_data.loc[
            reservoir_data["project_id"] == project_id
        ].sort_values("date")

        figure.add_trace(
            go.Scatter(
                x=project_data["date"],
                y=project_data["combined_offset_kaf"],
                mode="lines",
                name=project_name,
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.5,
                ),
                hovertemplate=(
                    f"<b>{project_name}</b><br>"
                    "Date: %{x|%d %b %Y}<br>"
                    "Daily FIRO space: %{y:.2f} KAF<extra></extra>"
                ),
            ),
            row=row_number,
            col=1,
        )

        figure.add_trace(
            go.Scatter(
                x=project_data["date"],
                y=[limit_kaf] * len(project_data),
                mode="lines",
                name="Assigned FIRO Limit",
                showlegend=False,
                line=dict(
                    color="#111111",
                    width=1.5,
                    dash="dash",
                ),
                hovertemplate=(
                    "<b>Assigned FIRO Limit</b><br>"
                    "Limit: %{y:.2f} KAF<extra></extra>"
                ),
            ),
            row=row_number,
            col=1,
        )

        axis_maximum = max(limit_kaf, 0.1)

        figure.update_yaxes(
            title_text="KAF",
            range=[0.0, axis_maximum],
            row=row_number,
            col=1,
        )

    figure.update_layout(
        title=(
            f"Alternative {alternative_id}: {alternative_name}"
            "<br><sup>Physical Reservoir Daily FIRO-Space Utilization "
            "(no-routing screening)</sup>"
        ),
        template="plotly_white",
        height=max(500, 145 * project_count + 110),
        hovermode="x unified",
        margin=dict(l=85, r=50, t=100, b=70),
    )

    figure.update_xaxes(
        title_text="Date",
        row=project_count,
        col=1,
    )

    return figure


def build_control_point_figure(
    alternative_id: int,
    alternative_name: str,
    control_point_id: str,
    control_point_name: str,
    control_point_data: pd.DataFrame,
    contribution_data: pd.DataFrame,
    is_system_plot: bool = False,
) -> go.Figure:
    """
    Top: stacked no-routing allocation-unit contributions.
    Bottom: daily percent utilization of static control-point limit.
    """
    control_point_data = control_point_data.sort_values("date").copy()
    contribution_data = contribution_data.sort_values("date").copy()

    space_limit_kaf = float(
        control_point_data["space_limit_kaf"].iloc[0]
    )

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.11,
        row_heights=[0.70, 0.30],
        subplot_titles=(
            "Unrouted Upstream FIRO-Space Loading by Allocation Unit",
            "Daily Utilization of Static Control-Point Limit",
        ),
    )

    for allocation_unit_name, unit_data in contribution_data.groupby(
        "decision_unit_name",
        sort=True,
    ):
        unit_data = unit_data.sort_values("date")

        figure.add_trace(
            go.Scatter(
                x=unit_data["date"],
                y=unit_data["allocation_unit_offset_kaf"],
                mode="lines",
                name=allocation_unit_name,
                stackgroup="control_point_firo_space",
                hovertemplate=(
                    f"<b>{allocation_unit_name}</b><br>"
                    "Date: %{x|%d %b %Y}<br>"
                    "Unrouted FIRO contribution: %{y:.2f} KAF"
                    "<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )

    add_limit_line(
        figure=figure,
        dates=control_point_data["date"],
        limit_kaf=space_limit_kaf,
        row=1,
        name=f"{control_point_name} Static Limit",
    )

    figure.add_trace(
        go.Scatter(
            x=control_point_data["date"],
            y=control_point_data[
                "control_point_utilization_percent"
            ],
            mode="lines",
            name="Daily Limit Utilization",
            line=dict(
                color="#1f4e79",
                width=3,
            ),
            hovertemplate=(
                "<b>Daily Utilization</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Static limit used: %{y:.1f}%<extra></extra>"
            ),
        ),
        row=2,
        col=1,
    )

    figure.add_hline(
        y=100.0,
        line_color="#111111",
        line_dash="dash",
        line_width=2,
        row=2,
        col=1,
    )

    if is_system_plot:
        title_middle = "System-Level No-Routing FIRO-Space Screening at Salem"
    else:
        title_middle = (
            f"{control_point_name} ({control_point_id}) "
            "No-Routing FIRO-Space Screening"
        )

    figure.update_layout(
        title=(
            f"Alternative {alternative_id}: {alternative_name}"
            f"<br>{title_middle}"
            "<br><sup>Same-day aggregation only. No reach routing, "
            "local inflow, attenuation, or operational release routing.</sup>"
        ),
        template="plotly_white",
        height=820,
        hovermode="x unified",
        legend=dict(
            title=dict(text="Upstream Allocation Units"),
            x=1.02,
            xanchor="left",
            y=1.0,
            yanchor="top",
        ),
        margin=dict(l=90, r=295, t=125, b=70),
    )

    figure.update_yaxes(
        title_text="Unrouted FIRO Space (KAF)",
        rangemode="tozero",
        row=1,
        col=1,
    )

    max_percent = max(
        110.0,
        float(
            control_point_data[
                "control_point_utilization_percent"
            ].max()
        )
        * 1.10,
    )

    figure.update_yaxes(
        title_text="Static Limit Used (%)",
        range=[0, max_percent],
        row=2,
        col=1,
    )

    figure.update_xaxes(
        title_text="Date",
        row=2,
        col=1,
    )

    return figure


# =============================================================================
# HTML INDEX
# =============================================================================

def write_html_index(entries: list[dict]) -> None:
    rows = []

    for entry in entries:
        control_point_links = "<br>".join(
            (
                f'<a href="{escape(filename)}">'
                f"{escape(label)}</a>"
            )
            for filename, label in entry["control_point_pages"]
        )

        rows.append(
            "<tr>"
            f"<td>{entry['alternative_id']}</td>"
            f"<td>{escape(entry['alternative_name'])}</td>"
            f'<td><a href="{escape(entry["reservoir_page"])}">'
            "Reservoir Dashboard</a></td>"
            f'<td><a href="{escape(entry["system_page"])}">'
            "System / Salem Dashboard</a></td>"
            f"<td>{control_point_links}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FIRO No-Routing Utilization Review</title>
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 32px;
    color: #202a33;
}}
h1, h2 {{
    color: #173a5e;
}}
.note {{
    max-width: 1100px;
    background: #fff7d6;
    border-left: 5px solid #cc9200;
    padding: 14px;
    line-height: 1.4;
}}
table {{
    border-collapse: collapse;
    margin-top: 18px;
    min-width: 1050px;
}}
th, td {{
    border: 1px solid #c8d1dc;
    padding: 8px 12px;
    text-align: left;
    vertical-align: top;
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
</style>
</head>
<body>
<h1>FIRO No-Routing Daily Utilization Review</h1>

<div class="note">
<b>Interpretation:</b> These dashboards screen daily FIRO storage-space
offsets using same-day aggregation. They do not model reach travel time,
Modified Puls routing, local inflows, attenuation, operational releases,
or actual control-point flow. Control-point products are therefore labeled
<b>Unrouted FIRO-Space Loading</b>.
</div>

<h2>Alternative Dashboards</h2>

<table>
<thead>
<tr>
<th>Alternative</th>
<th>Name</th>
<th>Reservoir Review</th>
<th>System Review</th>
<th>Control-Point Reviews</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>

<h2>Supporting CSV Files</h2>
<ul>
<li><a href="01_reservoir_daily_firo_utilization.csv">
01_reservoir_daily_firo_utilization.csv</a></li>
<li><a href="02_control_point_daily_unrouted_loading.csv">
02_control_point_daily_unrouted_loading.csv</a></li>
<li><a href="03_system_daily_salem_loading.csv">
03_system_daily_salem_loading.csv</a></li>
</ul>

<p><a href="../index.html">Return to Primary FIRO Review Package</a></p>

</body>
</html>
"""

    (REVIEW_DIRECTORY / "index.html").write_text(
        html,
        encoding="utf-8",
    )


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    REVIEW_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    daily_file = choose_daily_file()

    daily = pd.read_csv(daily_file)
    allocations = pd.read_csv(ALLOCATION_FILE)
    relationships = pd.read_csv(RELATIONSHIP_FILE)

    required_daily_columns = {
        "alternative_id",
        "project_id",
        "project_name",
        "decision_unit_id",
        "date",
        "combined_offset_kaf",
        "allocated_project_firo_space_kaf",
    }

    missing_daily = required_daily_columns - set(daily.columns)

    if missing_daily:
        raise ValueError(
            "Daily curve file is missing required columns:\n"
            + "\n".join(
                f"  - {column}"
                for column in sorted(missing_daily)
            )
        )

    required_allocation_columns = {
        "alternative_id",
        "alternative_name",
        "decision_unit_id",
        "decision_unit_name",
    }

    missing_allocation = (
        required_allocation_columns
        - set(allocations.columns)
    )

    if missing_allocation:
        raise ValueError(
            "Allocation file is missing required columns:\n"
            + "\n".join(
                f"  - {column}"
                for column in sorted(missing_allocation)
            )
        )

    required_relationship_columns = {
        "decision_unit_id",
        "control_point_id",
        "control_point_name",
        "space_limit_kaf",
    }

    missing_relationship = (
        required_relationship_columns
        - set(relationships.columns)
    )

    if missing_relationship:
        raise ValueError(
            "Control-point relationship file is missing required columns:\n"
            + "\n".join(
                f"  - {column}"
                for column in sorted(missing_relationship)
            )
        )

    daily["date"] = pd.to_datetime(daily["date"])

    daily["combined_offset_kaf"] = (
        pd.to_numeric(
            daily["combined_offset_kaf"],
            errors="coerce",
        )
        .fillna(0.0)
        .clip(lower=0.0)
    )

    daily["allocated_project_firo_space_kaf"] = (
        pd.to_numeric(
            daily["allocated_project_firo_space_kaf"],
            errors="coerce",
        )
        .fillna(0.0)
    )

    # Some daily files already include alternative_name. Remove it before
    # merging the authoritative alternative names from allocation output.
    if "alternative_name" in daily.columns:
        daily = daily.drop(columns=["alternative_name"])

    alternative_lookup = (
        allocations[
            [
                "alternative_id",
                "alternative_name",
            ]
        ]
        .drop_duplicates()
    )

    decision_unit_lookup = (
        allocations[
            [
                "alternative_id",
                "decision_unit_id",
                "decision_unit_name",
            ]
        ]
        .drop_duplicates()
    )

    daily = daily.merge(
        alternative_lookup,
        on="alternative_id",
        how="left",
        validate="many_to_one",
    )

    # -------------------------------------------------------------------------
    # Reservoir daily utilization.
    # -------------------------------------------------------------------------

    reservoir_daily = daily[
        [
            "alternative_id",
            "alternative_name",
            "project_id",
            "project_name",
            "decision_unit_id",
            "date",
            "combined_offset_kaf",
            "allocated_project_firo_space_kaf",
            "controlling_component",
        ]
    ].copy()

    reservoir_daily["reservoir_utilization_percent"] = (
        100.0
        * reservoir_daily["combined_offset_kaf"]
        / reservoir_daily["allocated_project_firo_space_kaf"].where(
            reservoir_daily["allocated_project_firo_space_kaf"]
            > TOLERANCE_KAF
        )
    )

    reservoir_daily["reservoir_utilization_percent"] = (
        reservoir_daily["reservoir_utilization_percent"]
        .fillna(0.0)
    )

    reservoir_daily.to_csv(
        REVIEW_DIRECTORY
        / "01_reservoir_daily_firo_utilization.csv",
        index=False,
    )

    # -------------------------------------------------------------------------
    # Allocation-unit daily offsets.
    #
    # LOP_HCR remains one downstream allocation unit. Its daily screen value
    # is the sum of its member physical-reservoir FIRO offsets.
    # -------------------------------------------------------------------------

    allocation_unit_daily = (
        reservoir_daily.groupby(
            [
                "alternative_id",
                "alternative_name",
                "decision_unit_id",
                "date",
            ],
            as_index=False,
        )["combined_offset_kaf"]
        .sum()
        .rename(
            columns={
                "combined_offset_kaf": "allocation_unit_offset_kaf",
            }
        )
    )

    allocation_unit_daily = allocation_unit_daily.merge(
        decision_unit_lookup,
        on=[
            "alternative_id",
            "decision_unit_id",
        ],
        how="left",
        validate="many_to_one",
    )

    relationship_columns = [
        "decision_unit_id",
        "control_point_id",
        "control_point_name",
        "space_limit_kaf",
    ]

    relationship_map = relationships[
        relationship_columns
    ].drop_duplicates(
        subset=[
            "decision_unit_id",
            "control_point_id",
        ]
    )

    control_point_contributions = allocation_unit_daily.merge(
        relationship_map,
        on="decision_unit_id",
        how="inner",
        validate="many_to_many",
    )

    control_point_daily = (
        control_point_contributions.groupby(
            [
                "alternative_id",
                "alternative_name",
                "control_point_id",
                "control_point_name",
                "space_limit_kaf",
                "date",
            ],
            as_index=False,
        )["allocation_unit_offset_kaf"]
        .sum()
        .rename(
            columns={
                "allocation_unit_offset_kaf": (
                    "unrouted_control_point_loading_kaf"
                ),
            }
        )
    )

    control_point_daily["control_point_utilization_percent"] = (
        100.0
        * control_point_daily[
            "unrouted_control_point_loading_kaf"
        ]
        / control_point_daily["space_limit_kaf"]
    )

    control_point_contributions = control_point_contributions.merge(
        control_point_daily[
            [
                "alternative_id",
                "control_point_id",
                "date",
                "unrouted_control_point_loading_kaf",
                "control_point_utilization_percent",
            ]
        ],
        on=[
            "alternative_id",
            "control_point_id",
            "date",
        ],
        how="left",
        validate="many_to_one",
    )

    control_point_contributions.to_csv(
        REVIEW_DIRECTORY
        / "02_control_point_daily_unrouted_loading.csv",
        index=False,
    )

    # -------------------------------------------------------------------------
    # Salem system summary.
    # -------------------------------------------------------------------------

    salem_daily = control_point_daily.loc[
        control_point_daily["control_point_id"] == "SALEM"
    ].copy()

    salem_daily.to_csv(
        REVIEW_DIRECTORY
        / "03_system_daily_salem_loading.csv",
        index=False,
    )

    # -------------------------------------------------------------------------
    # Build dashboards and index.
    # -------------------------------------------------------------------------

    index_entries = []

    for alternative_id, alternative_data in reservoir_daily.groupby(
        "alternative_id",
        sort=True,
    ):
        alternative_name = str(
            alternative_data["alternative_name"].iloc[0]
        )

        reservoir_filename = (
            f"alternative_{int(alternative_id):02d}_"
            "reservoir_utilization.html"
        )

        reservoir_figure = build_reservoir_figure(
            alternative_id=int(alternative_id),
            alternative_name=alternative_name,
            reservoir_data=alternative_data,
        )

        write_figure(
            reservoir_figure,
            REVIEW_DIRECTORY / reservoir_filename,
        )

        alternative_salem_daily = salem_daily.loc[
            salem_daily["alternative_id"] == alternative_id
        ].copy()

        alternative_salem_contributions = (
            control_point_contributions.loc[
                (
                    control_point_contributions["alternative_id"]
                    == alternative_id
                )
                & (
                    control_point_contributions["control_point_id"]
                    == "SALEM"
                )
            ].copy()
        )

        system_filename = ""

        if not alternative_salem_daily.empty:
            system_filename = (
                f"alternative_{int(alternative_id):02d}_"
                "system_salem_utilization.html"
            )

            system_figure = build_control_point_figure(
                alternative_id=int(alternative_id),
                alternative_name=alternative_name,
                control_point_id="SALEM",
                control_point_name="System / Salem",
                control_point_data=alternative_salem_daily,
                contribution_data=alternative_salem_contributions,
                is_system_plot=True,
            )

            write_figure(
                system_figure,
                REVIEW_DIRECTORY / system_filename,
            )

        control_point_pages = []

        alternative_control_points = control_point_daily.loc[
            control_point_daily["alternative_id"] == alternative_id
        ]

        for control_point_id, cp_data in alternative_control_points.groupby(
            "control_point_id",
            sort=True,
        ):
            control_point_name = str(
                cp_data["control_point_name"].iloc[0]
            )

            contribution_data = control_point_contributions.loc[
                (
                    control_point_contributions["alternative_id"]
                    == alternative_id
                )
                & (
                    control_point_contributions["control_point_id"]
                    == control_point_id
                )
            ].copy()

            control_point_filename = (
                f"alternative_{int(alternative_id):02d}_"
                f"control_point_{safe_filename(control_point_id)}_"
                "utilization.html"
            )

            control_point_figure = build_control_point_figure(
                alternative_id=int(alternative_id),
                alternative_name=alternative_name,
                control_point_id=str(control_point_id),
                control_point_name=control_point_name,
                control_point_data=cp_data,
                contribution_data=contribution_data,
                is_system_plot=False,
            )

            write_figure(
                control_point_figure,
                REVIEW_DIRECTORY / control_point_filename,
            )

            control_point_pages.append(
                (
                    control_point_filename,
                    f"{control_point_name} ({control_point_id})",
                )
            )

        index_entries.append(
            {
                "alternative_id": int(alternative_id),
                "alternative_name": alternative_name,
                "reservoir_page": reservoir_filename,
                "system_page": system_filename,
                "control_point_pages": control_point_pages,
            }
        )

    write_html_index(index_entries)

    print()
    print("=" * 74)
    print("NO-ROUTING FIRO UTILIZATION REVIEW COMPLETE")
    print("=" * 74)
    print(f"Daily curve input: {daily_file.name}")
    print(f"Review directory:  {REVIEW_DIRECTORY}")
    print(f"Alternatives:      {len(index_entries)}")
    print()
    print("Created supporting CSVs:")
    print("  01_reservoir_daily_firo_utilization.csv")
    print("  02_control_point_daily_unrouted_loading.csv")
    print("  03_system_daily_salem_loading.csv")
    print()
    print("Open this file first:")
    print(REVIEW_DIRECTORY / "index.html")


if __name__ == "__main__":
    main()