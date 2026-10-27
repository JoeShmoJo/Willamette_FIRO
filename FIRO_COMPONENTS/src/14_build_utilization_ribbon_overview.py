"""
Build combined reservoir and control-point FIRO utilization overview pages.

Each alternative page includes:
- one short reservoir plot per physical reservoir;
- one short control-point plot per control point;
- one combined utilization ribbon at the bottom.

Ribbon utilization:
    Green  = 0 to 25 percent of capacity
    Blue   = greater than 25 to 50 percent
    Orange = greater than 50 to 90 percent
    Red    = greater than 90 percent

Reservoir denominator:
    physical FIRO / evacuation-room capacity.

Control-point denominator:
    static control-point FIRO-space limit.

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


def utilization_category(
    utilization_percent: float,
) -> tuple[int, str]:
    """
    Return categorical utilization code and readable label.

    0 = green
    1 = blue
    2 = orange
    3 = red
    """
    if utilization_percent <= 25.0:
        return 0, "0-25 percent of capacity"

    if utilization_percent <= 50.0:
        return 1, "26-50 percent of capacity"

    if utilization_percent <= 90.0:
        return 2, "51-90 percent of capacity"

    return 3, "91-100+ percent of capacity"


def ribbon_colors() -> list[list[object]]:
    return [
        [0.00, "#2ca02c"],
        [0.24, "#2ca02c"],
        [0.25, "#1f77b4"],
        [0.49, "#1f77b4"],
        [0.50, "#ff7f0e"],
        [0.74, "#ff7f0e"],
        [0.75, "#d62728"],
        [1.00, "#d62728"],
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

    ribbon_row = reservoir_count + control_point_count + 1
    total_rows = ribbon_row

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

    subplot_titles.append(
        "Combined Reservoir and Control-Point Utilization Ribbon"
    )

    row_heights = (
        [1.0] * reservoir_count
        + [1.0] * control_point_count
        + [0.80]
    )

    figure = make_subplots(
        rows=total_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.005,
        subplot_titles=subplot_titles,
        row_heights=row_heights,
    )

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
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.2,
                ),
                hovertemplate=(
                    f"<b>{limit_row.project_name}</b><br>"
                    "Date: %{x|%d %b %Y}<br>"
                    "Daily FIRO space: %{y:.2f} KAF"
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
            range=[0.0, max(physical_capacity_kaf, 0.1)],
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
                mode="lines",
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.2,
                ),
                hovertemplate=(
                    f"<b>{limit_row.control_point_name}</b><br>"
                    "Date: %{x|%d %b %Y}<br>"
                    "Daily unrouted FIRO loading: %{y:.2f} KAF"
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
            range=[0.0, max(capacity_kaf, 0.1)],
            row=row_number,
            col=1,
        )

    # -------------------------------------------------------------------------
    # Combined utilization ribbon.
    # -------------------------------------------------------------------------

    reservoir_ribbon = reservoir_data[
        [
            "project_name",
            "date",
            "physical_capacity_utilization_percent",
        ]
    ].copy()

    reservoir_ribbon["location_label"] = (
        "Reservoir | "
        + reservoir_ribbon["project_name"]
    )

    reservoir_ribbon[
        ["ribbon_code", "ribbon_label"]
    ] = reservoir_ribbon.apply(
        lambda row: pd.Series(
            utilization_category(
                float(
                    row[
                        "physical_capacity_utilization_percent"
                    ]
                )
            )
        ),
        axis=1,
    )

    control_point_ribbon = control_point_data[
        [
            "control_point_name",
            "date",
            "control_point_utilization_percent",
        ]
    ].copy()

    control_point_ribbon["location_label"] = (
        "Control Point | "
        + control_point_ribbon["control_point_name"]
    )

    control_point_ribbon[
        ["ribbon_code", "ribbon_label"]
    ] = control_point_ribbon.apply(
        lambda row: pd.Series(
            utilization_category(
                float(
                    row[
                        "control_point_utilization_percent"
                    ]
                )
            )
        ),
        axis=1,
    )

    combined_ribbon = pd.concat(
        [
            reservoir_ribbon[
                [
                    "location_label",
                    "date",
                    "ribbon_code",
                    "ribbon_label",
                ]
            ],
            control_point_ribbon[
                [
                    "location_label",
                    "date",
                    "ribbon_code",
                    "ribbon_label",
                ]
            ],
        ],
        ignore_index=True,
    )

    location_order = (
        [
            f"Reservoir | {name}"
            for name in reservoir_limits["project_name"]
        ]
        + [
            f"Control Point | {name}"
            for name in control_point_limits[
                "control_point_name"
            ]
        ]
    )

    ribbon_matrix = combined_ribbon.pivot(
        index="location_label",
        columns="date",
        values="ribbon_code",
    ).reindex(
        index=location_order
    )

    label_matrix = combined_ribbon.pivot(
        index="location_label",
        columns="date",
        values="ribbon_label",
    ).reindex(
        index=location_order,
        columns=ribbon_matrix.columns,
    )

    figure.add_trace(
        go.Heatmap(
            x=ribbon_matrix.columns,
            y=ribbon_matrix.index,
            z=ribbon_matrix.values,
            customdata=label_matrix.values,
            colorscale=ribbon_colors(),
            zmin=-0.5,
            zmax=3.5,
            showscale=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Utilization: %{customdata}<extra></extra>"
            ),
        ),
        row=ribbon_row,
        col=1,
    )

    figure.update_yaxes(
        title_text="Location",
        row=ribbon_row,
        col=1,
    )

    figure.update_xaxes(
        title_text="Date",
        row=ribbon_row,
        col=1,
    )

    figure.update_layout(
        title=(
            f"Alternative {alternative_id}: {alternative_name}"
            "<br><sup>"
            "Blue line = daily FIRO space/loading. "
            "Purple dashed = assigned reservoir FIRO allocation. "
            "Black dotted = physical reservoir capacity or "
            "static control-point capacity."
            "<br>"
            "Ribbon: green = 0-25%; blue = 26-50%; "
            "orange = 51-90%; red = 91-100+% of capacity."
            "</sup>"
        ),
        template="plotly_white",
        height=max(2400, 110 * total_rows + 220),
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
<title>FIRO Utilization Ribbon Overview</title>
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
scrollable page. The bottom ribbon uses the same percentage scale for every
reservoir and control point: green 0-25%, blue 26-50%, orange 51-90%, and
red 91-100+% of its modeled capacity. This is a no-routing FIRO-space screen.
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