"""
Build one combined reservoir-and-control-point constraint overview page
per alternative.

Inputs:
    outputs/review/capacity_constraint_review/
        01_reservoir_daily_capacity_status.csv
        02_control_point_daily_capacity_status.csv

Outputs:
    outputs/review/combined_constraint_overview/

Each Alternative Overview page contains, in order:
1. Short physical-reservoir FIRO-space plots.
2. Reservoir constraint-status ribbon.
3. Short control-point FIRO-space loading plots.
4. Control-point constraint-status ribbon.

All panels share the same date axis.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "review"
    / "capacity_constraint_review"
)

RESERVOIR_FILE = (
    INPUT_DIRECTORY
    / "01_reservoir_daily_capacity_status.csv"
)

CONTROL_POINT_FILE = (
    INPUT_DIRECTORY
    / "02_control_point_daily_capacity_status.csv"
)

OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "review"
    / "combined_constraint_overview"
)

INCLUDE_PLOTLY_JS = "directory"


def write_figure(figure: go.Figure, path: Path) -> None:
    figure.write_html(
        path,
        include_plotlyjs=INCLUDE_PLOTLY_JS,
        full_html=True,
    )


def reservoir_ribbon_colors() -> list[list[object]]:
    """
    Reservoir status codes:
      0 No active FIRO space
      1 Geometry / seasonal timing limited
      2 Near assigned allocation
      3 Assigned allocation binding
      4 Near physical capacity
      5 Physical capacity binding
    """
    return [
        [0.00, "#d9d9d9"],
        [0.16, "#d9d9d9"],
        [0.17, "#ffffff"],
        [0.33, "#ffffff"],
        [0.34, "#f4c542"],
        [0.50, "#f4c542"],
        [0.51, "#7b4fa3"],
        [0.67, "#7b4fa3"],
        [0.68, "#f28e2b"],
        [0.84, "#f28e2b"],
        [0.85, "#c00000"],
        [1.00, "#c00000"],
    ]


def control_point_ribbon_colors() -> list[list[object]]:
    """
    Control-point status codes:
      0 No active FIRO loading
      1 Control-point headroom remains
      2 Near control-point limit
      3 Control-point limit binding
    """
    return [
        [0.00, "#d9d9d9"],
        [0.24, "#d9d9d9"],
        [0.25, "#ffffff"],
        [0.49, "#ffffff"],
        [0.50, "#f4c542"],
        [0.74, "#f4c542"],
        [0.75, "#c00000"],
        [1.00, "#c00000"],
    ]


def build_overview(
    alternative_id: int,
    alternative_name: str,
    reservoir_data: pd.DataFrame,
    control_point_data: pd.DataFrame,
) -> go.Figure:
    reservoir_data = reservoir_data.sort_values("date").copy()
    control_point_data = control_point_data.sort_values("date").copy()

    reservoir_limits = (
        reservoir_data[
            [
                "project_id",
                "project_name",
                "assigned_firo_allocation_kaf",
                "physical_firo_capacity_kaf",
            ]
        ]
        .drop_duplicates()
        .sort_values("project_name")
    )

    control_point_limits = (
        control_point_data[
            [
                "control_point_id",
                "control_point_name",
                "space_limit_kaf",
            ]
        ]
        .drop_duplicates()
        .sort_values("control_point_name")
    )

    reservoir_count = len(reservoir_limits)
    control_point_count = len(control_point_limits)

    reservoir_ribbon_row = reservoir_count + 1
    first_control_point_row = reservoir_count + 2
    control_point_ribbon_row = reservoir_count + control_point_count + 2

    total_rows = control_point_ribbon_row

    subplot_titles = []

    for row in reservoir_limits.itertuples():
        subplot_titles.append(
            (
                f"Reservoir: {row.project_name} | "
                f"Assigned {row.assigned_firo_allocation_kaf:.2f} KAF | "
                f"Physical {row.physical_firo_capacity_kaf:.2f} KAF"
            )
        )

    subplot_titles.append("Reservoir Constraint Status Ribbon")

    for row in control_point_limits.itertuples():
        subplot_titles.append(
            (
                f"Control Point: {row.control_point_name} "
                f"({row.control_point_id}) | "
                f"Limit {row.space_limit_kaf:.2f} KAF"
            )
        )

    subplot_titles.append(
        "Control-Point Constraint Status Ribbon"
    )

    row_heights = (
        [1.0] * reservoir_count
        + [0.65]
        + [1.0] * control_point_count
        + [0.65]
    )

    figure = make_subplots(
        rows=total_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.006,
        subplot_titles=subplot_titles,
        row_heights=row_heights,
    )

    # -------------------------------------------------------------------------
    # Reservoir line plots.
    # -------------------------------------------------------------------------

    for row_number, limit_row in enumerate(
        reservoir_limits.itertuples(),
        start=1,
    ):
        project_data = reservoir_data.loc[
            reservoir_data["project_id"] == limit_row.project_id
        ].sort_values("date")

        assigned_kaf = float(
            limit_row.assigned_firo_allocation_kaf
        )

        physical_kaf = float(
            limit_row.physical_firo_capacity_kaf
        )

        figure.add_trace(
            go.Scatter(
                x=project_data["date"],
                y=project_data["combined_offset_kaf"],
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.2,
                ),
                hovertemplate=(
                    f"<b>{limit_row.project_name}</b><br>"
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
                y=[assigned_kaf] * len(project_data),
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#7b4fa3",
                    width=1.5,
                    dash="dash",
                ),
                hovertemplate=(
                    "<b>Assigned FIRO Allocation</b><br>"
                    "Allocation: %{y:.2f} KAF<extra></extra>"
                ),
            ),
            row=row_number,
            col=1,
        )

        figure.add_trace(
            go.Scatter(
                x=project_data["date"],
                y=[physical_kaf] * len(project_data),
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#111111",
                    width=1.5,
                    dash="dot",
                ),
                hovertemplate=(
                    "<b>Physical FIRO Capacity</b><br>"
                    "Physical capacity: %{y:.2f} KAF<extra></extra>"
                ),
            ),
            row=row_number,
            col=1,
        )

        figure.update_yaxes(
            title_text="KAF",
            range=[0.0, max(physical_kaf, 0.1)],
            row=row_number,
            col=1,
        )

    # -------------------------------------------------------------------------
    # Reservoir status ribbon.
    # -------------------------------------------------------------------------

    reservoir_status_matrix = reservoir_data.pivot(
        index="project_name",
        columns="date",
        values="reservoir_status_code",
    ).sort_index()

    reservoir_label_matrix = reservoir_data.pivot(
        index="project_name",
        columns="date",
        values="reservoir_status_label",
    ).reindex(
        index=reservoir_status_matrix.index,
        columns=reservoir_status_matrix.columns,
    )

    figure.add_trace(
        go.Heatmap(
            x=reservoir_status_matrix.columns,
            y=reservoir_status_matrix.index,
            z=reservoir_status_matrix.values,
            customdata=reservoir_label_matrix.values,
            colorscale=reservoir_ribbon_colors(),
            zmin=-0.5,
            zmax=5.5,
            showscale=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Status: %{customdata}<extra></extra>"
            ),
        ),
        row=reservoir_ribbon_row,
        col=1,
    )

    figure.update_yaxes(
        title_text="Reservoir",
        row=reservoir_ribbon_row,
        col=1,
    )

    # -------------------------------------------------------------------------
    # Control-point line plots.
    # -------------------------------------------------------------------------

    for position, limit_row in enumerate(
        control_point_limits.itertuples(),
        start=0,
    ):
        row_number = first_control_point_row + position

        cp_data = control_point_data.loc[
            control_point_data["control_point_id"]
            == limit_row.control_point_id
        ].sort_values("date")

        limit_kaf = float(limit_row.space_limit_kaf)

        figure.add_trace(
            go.Scatter(
                x=cp_data["date"],
                y=cp_data["unrouted_control_point_loading_kaf"],
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.2,
                ),
                hovertemplate=(
                    f"<b>{limit_row.control_point_name}</b><br>"
                    "Date: %{x|%d %b %Y}<br>"
                    "Unrouted FIRO loading: %{y:.2f} KAF"
                    "<extra></extra>"
                ),
            ),
            row=row_number,
            col=1,
        )

        figure.add_trace(
            go.Scatter(
                x=cp_data["date"],
                y=[limit_kaf] * len(cp_data),
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#111111",
                    width=1.5,
                    dash="dot",
                ),
                hovertemplate=(
                    "<b>Static Control-Point Limit</b><br>"
                    "Limit: %{y:.2f} KAF<extra></extra>"
                ),
            ),
            row=row_number,
            col=1,
        )

        figure.update_yaxes(
            title_text="KAF",
            range=[0.0, max(limit_kaf, 0.1)],
            row=row_number,
            col=1,
        )

    # -------------------------------------------------------------------------
    # Control-point status ribbon.
    # -------------------------------------------------------------------------

    cp_status_matrix = control_point_data.pivot(
        index="control_point_name",
        columns="date",
        values="control_point_status_code",
    ).sort_index()

    cp_label_matrix = control_point_data.pivot(
        index="control_point_name",
        columns="date",
        values="control_point_status_label",
    ).reindex(
        index=cp_status_matrix.index,
        columns=cp_status_matrix.columns,
    )

    figure.add_trace(
        go.Heatmap(
            x=cp_status_matrix.columns,
            y=cp_status_matrix.index,
            z=cp_status_matrix.values,
            customdata=cp_label_matrix.values,
            colorscale=control_point_ribbon_colors(),
            zmin=-0.5,
            zmax=3.5,
            showscale=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Status: %{customdata}<extra></extra>"
            ),
        ),
        row=control_point_ribbon_row,
        col=1,
    )

    figure.update_yaxes(
        title_text="Control Point",
        row=control_point_ribbon_row,
        col=1,
    )

    figure.update_xaxes(
        title_text="Date",
        row=control_point_ribbon_row,
        col=1,
    )

    figure.update_layout(
        title=(
            f"Alternative {alternative_id}: {alternative_name}"
            "<br><sup>"
            "Line colors: blue = daily FIRO space/loading; "
            "purple dashed = assigned reservoir allocation; "
            "black dotted = physical reservoir capacity or "
            "static control-point limit."
            "<br>"
            "Ribbon colors: gray = no active FIRO; white = geometry/headroom; "
            "amber = near limit; purple = assigned allocation binding; "
            "red = physical or control-point limit binding."
            "</sup>"
        ),
        template="plotly_white",
        height=max(2200, 120 * total_rows + 250),
        hovermode="x unified",
        margin=dict(l=105, r=55, t=145, b=75),
    )

    return figure


def write_index(entries: list[dict]) -> None:
    rows = []

    for entry in entries:
        rows.append(
            "<tr>"
            f"<td>{entry['alternative_id']}</td>"
            f"<td>{escape(entry['alternative_name'])}</td>"
            f'<td><a href="{escape(entry["filename"])}">'
            "Open Combined Constraint Overview</a></td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FIRO Combined Constraint Overview</title>
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 32px;
    color: #202a33;
}}
h1 {{
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
    min-width: 750px;
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
</style>
</head>
<body>
<h1>FIRO Combined Constraint Overview</h1>

<div class="note">
Each page places reservoir and control-point capacity plots on one
scrollable page. All panels use the same date axis. This is a
no-routing FIRO-space screening product; it does not model routed
flow, local inflow, attenuation, or operational release routing.
</div>

<table>
<thead>
<tr>
<th>Alternative</th>
<th>Name</th>
<th>Overview</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>

<p><a href="../index.html">Return to Primary FIRO Review Package</a></p>
</body>
</html>
"""

    (OUTPUT_DIRECTORY / "index.html").write_text(
        html,
        encoding="utf-8",
    )


def main() -> None:
    if not RESERVOIR_FILE.exists():
        raise FileNotFoundError(
            "Missing reservoir capacity-status file:\n"
            f"  {RESERVOIR_FILE}\n\n"
            "Run 11_build_capacity_constraint_review.py first."
        )

    if not CONTROL_POINT_FILE.exists():
        raise FileNotFoundError(
            "Missing control-point capacity-status file:\n"
            f"  {CONTROL_POINT_FILE}\n\n"
            "Run 11_build_capacity_constraint_review.py first."
        )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    reservoir_data = pd.read_csv(RESERVOIR_FILE)
    control_point_data = pd.read_csv(CONTROL_POINT_FILE)

    reservoir_data["date"] = pd.to_datetime(
        reservoir_data["date"]
    )

    control_point_data["date"] = pd.to_datetime(
        control_point_data["date"]
    )

    entries = []

    for alternative_id, alternative_reservoir_data in reservoir_data.groupby(
        "alternative_id",
        sort=True,
    ):
        alternative_name = str(
            alternative_reservoir_data[
                "alternative_name"
            ].iloc[0]
        )

        alternative_cp_data = control_point_data.loc[
            control_point_data["alternative_id"] == alternative_id
        ].copy()

        if alternative_cp_data.empty:
            continue

        figure = build_overview(
            alternative_id=int(alternative_id),
            alternative_name=alternative_name,
            reservoir_data=alternative_reservoir_data,
            control_point_data=alternative_cp_data,
        )

        filename = (
            f"alternative_{int(alternative_id):02d}_"
            "combined_constraint_overview.html"
        )

        write_figure(
            figure,
            OUTPUT_DIRECTORY / filename,
        )

        entries.append(
            {
                "alternative_id": int(alternative_id),
                "alternative_name": alternative_name,
                "filename": filename,
            }
        )

    write_index(entries)

    print()
    print("=" * 72)
    print("COMBINED FIRO CONSTRAINT OVERVIEW COMPLETE")
    print("=" * 72)
    print(f"Created overview pages: {len(entries)}")
    print(f"Open: {OUTPUT_DIRECTORY / 'index.html'}")


if __name__ == "__main__":
    main()