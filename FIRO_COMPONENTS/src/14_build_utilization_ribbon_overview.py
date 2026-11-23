"""
Build combined reservoir and control-point FIRO utilization overview pages.

Each alternative page shows daily reservoir FIRO space and downstream
control-point loading alongside their limits.

This is a no-routing storage-space screen.
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
    / "outputs" / "diagnostics"
    / "scenarios"
    / "after"
    / "capacity_status"
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
    / "outputs" / "diagnostics"
    / "review"
    / "utilization_ribbon_overview"
)

INCLUDE_PLOTLY_JS = "directory"


def write_figure(figure: go.Figure, output_path: Path) -> None:
    figure.write_html(
        output_path,
        include_plotlyjs=INCLUDE_PLOTLY_JS,
        full_html=True,
    )


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

    total_rows = reservoir_count + control_point_count

    subplot_titles = []

    for row in reservoir_limits.itertuples():
        subplot_titles.append(
            (
                f"Reservoir: {row.project_name} | "
                f"Physical Capacity: "
                f"{row.physical_firo_capacity_kaf:.2f} KAF"
            )
        )

    for row in control_point_limits.itertuples():
        subplot_titles.append(
            (
                f"Control Point: {row.control_point_name} "
                f"({row.control_point_id}) | "
                f"Capacity: {row.space_limit_kaf:.2f} KAF"
            )
        )

    figure = make_subplots(
        rows=total_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=54 / (190 * total_rows),
        subplot_titles=subplot_titles,
    )
    figure.update_annotations(x=0, xanchor="left", yshift=8, font_size=15)

    # -------------------------------------------------------------------------
    # Reservoir plots: daily FIRO space versus physical capacity.
    # -------------------------------------------------------------------------

    for row_number, limit_row in enumerate(
        reservoir_limits.itertuples(),
        start=1,
    ):
        project_data = reservoir_data.loc[
            reservoir_data["project_id"] == limit_row.project_id
        ].sort_values("date")

        physical_capacity_kaf = float(
            limit_row.physical_firo_capacity_kaf
        )

        assigned_allocation_kaf = float(
            limit_row.assigned_firo_allocation_kaf
        )

        figure.add_trace(
            go.Scatter(
                x=project_data["date"],
                y=project_data["combined_offset_kaf"],
                customdata=project_data[[
                    "assigned_allocation_utilization_percent", "physical_capacity_utilization_percent"
                ]].to_numpy(),
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.2,
                ),
                hovertemplate=(
                    f"<b>{limit_row.project_name}</b><br>"
                    "Date: %{x|%d %b %Y}<br>"
                    "Daily FIRO space: %{y:.2f} KAF<br>"
                    "Assigned allocation used: %{customdata[0]:.1f}%<br>"
                    "Physical draft capacity used: %{customdata[1]:.1f}%"
                    "<extra></extra>"
                ),
            ),
            row=row_number,
            col=1,
        )

        figure.add_trace(
            go.Scatter(
                x=project_data["date"],
                y=[assigned_allocation_kaf] * len(project_data),
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#7b4fa3",
                    width=1.4,
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
                y=[physical_capacity_kaf] * len(project_data),
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
            range=[0.0, 1.05 * max(physical_capacity_kaf, project_data["combined_offset_kaf"].max(), 0.1)],
            row=row_number,
            col=1,
        )

    # -------------------------------------------------------------------------
    # Control-point plots: daily loading versus control-point capacity.
    # -------------------------------------------------------------------------

    first_cp_row = reservoir_count + 1

    for position, limit_row in enumerate(
        control_point_limits.itertuples(),
        start=0,
    ):
        row_number = first_cp_row + position

        cp_data = control_point_data.loc[
            control_point_data["control_point_id"]
            == limit_row.control_point_id
        ].sort_values("date")

        capacity_kaf = float(limit_row.space_limit_kaf)

        figure.add_trace(
            go.Scatter(
                x=cp_data["date"],
                y=cp_data[
                    "unrouted_control_point_loading_kaf"
                ],
                customdata=cp_data["control_point_utilization_percent"],
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.2,
                ),
                hovertemplate=(
                    f"<b>{limit_row.control_point_name}</b><br>"
                    "Date: %{x|%d %b %Y}<br>"
                    "Daily unrouted FIRO loading: %{y:.2f} KAF<br>"
                    "Downstream space used: %{customdata:.1f}%"
                    "<extra></extra>"
                ),
            ),
            row=row_number,
            col=1,
        )

        figure.add_trace(
            go.Scatter(
                x=cp_data["date"],
                y=[capacity_kaf] * len(cp_data),
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#111111",
                    width=1.5,
                    dash="dot",
                ),
                hovertemplate=(
                    "<b>Static Control-Point Capacity</b><br>"
                    "Capacity: %{y:.2f} KAF<extra></extra>"
                ),
            ),
            row=row_number,
            col=1,
        )

        figure.update_yaxes(
            title_text="KAF",
            range=[0.0, 1.05 * max(capacity_kaf, cp_data["unrouted_control_point_loading_kaf"].max(), 0.1)],
            row=row_number,
            col=1,
        )

    figure.update_xaxes(title_text="Date", row=total_rows, col=1)

    figure.update_layout(
        title=(
            f"Alternative {alternative_id}: {alternative_name}"
            "<br><sup>"
            "Blue line = daily FIRO space/loading. "
            "Purple dashed = assigned reservoir FIRO allocation. "
            "Black dotted = physical reservoir capacity or "
            "static control-point capacity."
            "</sup>"
        ),
        template="plotly_white",
        height=190 * total_rows + 200,
        hovermode="x unified",
        margin=dict(l=125, r=55, t=145, b=75),
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
            "Open Utilization Overview</a></td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FIRO Utilization Overview</title>
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
    max-width: 1050px;
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
<h1>FIRO Reservoir and Control-Point Utilization Review</h1>

<div class="note">
Each page places reservoir and control-point KAF plots on one vertically
scrollable page. Hover over a daily curve to see how much of its limit is
used. Downstream loading is an unrouted FIRO-space screen.
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

        alternative_control_point_data = control_point_data.loc[
            control_point_data["alternative_id"] == alternative_id
        ].copy()

        if alternative_control_point_data.empty:
            continue

        figure = build_overview(
            alternative_id=int(alternative_id),
            alternative_name=alternative_name,
            reservoir_data=alternative_reservoir_data,
            control_point_data=alternative_control_point_data,
        )

        filename = (
            f"alternative_{int(alternative_id):02d}_"
            "utilization_ribbon_overview.html"
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
    print("FIRO UTILIZATION RIBBON OVERVIEW COMPLETE")
    print("=" * 72)
    print(f"Created overview pages: {len(entries)}")
    print(f"Open: {OUTPUT_DIRECTORY / 'index.html'}")


if __name__ == "__main__":
    main()