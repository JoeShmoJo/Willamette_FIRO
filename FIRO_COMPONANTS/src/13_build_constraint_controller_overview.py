"""
Build combined FIRO capacity-constraint and envelope-controller overview pages.

Each alternative page contains:
1. One short plot per reservoir:
   - daily FIRO space;
   - assigned FIRO allocation;
   - physical FIRO capacity.

2. One short plot per control point:
   - daily unrouted FIRO-space loading;
   - static control-point limit.

3. One unified capacity-constraint ribbon:
   - reservoir and control-point rows together.

4. One envelope-controller ribbon:
   - one row per reservoir;
   - identifies Rule Curve, A, C, E, H, I, J, or K as the
     curve controlling the combined FIRO envelope on each day.

This is a no-routing storage-space screening product.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# =============================================================================
# PATHS
# =============================================================================

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
    / "constraint_controller_overview"
)

INCLUDE_PLOTLY_JS = "directory"


# =============================================================================
# STATUS MAPPING
# =============================================================================

def map_reservoir_status(
    status_code: int,
    status_label: str,
) -> tuple[int, str]:
    """
    Convert reservoir status to common capacity-ribbon code.

    Common ribbon codes:
        0 = no active FIRO space
        1 = geometry / headroom remains
        2 = near a capacity limit
        3 = assigned allocation binding
        4 = physical or control-point limit binding
    """
    if status_code == 0:
        return 0, "No active FIRO space"

    if status_code == 1:
        return 1, status_label

    if status_code in {2, 4}:
        return 2, status_label

    if status_code == 3:
        return 3, status_label

    if status_code == 5:
        return 4, status_label

    return 1, status_label


def map_control_point_status(
    status_code: int,
    status_label: str,
) -> tuple[int, str]:
    """
    Convert control-point status to common capacity-ribbon code.
    """
    if status_code == 0:
        return 0, "No active FIRO loading"

    if status_code == 1:
        return 1, status_label

    if status_code == 2:
        return 2, status_label

    if status_code == 3:
        return 4, status_label

    return 1, status_label


def capacity_ribbon_colors() -> list[list[object]]:
    """
    Common capacity ribbon:
        gray   = no FIRO/loading
        white  = geometry/headroom
        amber  = near limit
        purple = assigned allocation binding
        red    = physical/control-point binding
    """
    return [
        [0.00, "#d9d9d9"],
        [0.19, "#d9d9d9"],
        [0.20, "#ffffff"],
        [0.39, "#ffffff"],
        [0.40, "#f4c542"],
        [0.59, "#f4c542"],
        [0.60, "#7b4fa3"],
        [0.79, "#7b4fa3"],
        [0.80, "#c00000"],
        [1.00, "#c00000"],
    ]


CONTROLLER_CODE = {
    "RULE_CURVE": 0,
    "A": 1,
    "C": 2,
    "E": 3,
    "H": 4,
    "I": 5,
    "J": 6,
    "K": 7,
    "UNKNOWN": 8,
}

CONTROLLER_LABEL = {
    0: "Rule Curve",
    1: "A - Flat Winter Pool",
    2: "C - Early Refill",
    3: "E - MaxCon Transition",
    4: "H - Two Segment Refill",
    5: "I - April 1 Refill",
    6: "J - Drawdown Time Shift",
    7: "K - Refill Time Shift",
    8: "Unknown / No Data",
}


def controller_ribbon_colors() -> list[list[object]]:
    """
    Component controller ribbon:
        gray   = Rule Curve
        red    = A
        blue   = C
        dark gray = E
        green  = H
        purple = I
        pink   = J
        orange = K
        white  = Unknown
    """
    return [
        [0.00, "#bdbdbd"],
        [0.11, "#bdbdbd"],
        [0.12, "#d62728"],
        [0.23, "#d62728"],
        [0.24, "#1f77b4"],
        [0.35, "#1f77b4"],
        [0.36, "#666666"],
        [0.47, "#666666"],
        [0.48, "#2ca02c"],
        [0.59, "#2ca02c"],
        [0.60, "#9467bd"],
        [0.71, "#9467bd"],
        [0.72, "#e377c2"],
        [0.83, "#e377c2"],
        [0.84, "#ff7f0e"],
        [0.95, "#ff7f0e"],
        [0.96, "#ffffff"],
        [1.00, "#ffffff"],
    ]


# =============================================================================
# FIGURE HELPERS
# =============================================================================

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

    reservoir_ribbon_row = reservoir_count + control_point_count + 1
    controller_ribbon_row = reservoir_count + control_point_count + 2
    total_rows = controller_ribbon_row

    subplot_titles = []

    # Reservoir and control-point plots appear together before both ribbons.
    for row in reservoir_limits.itertuples():
        subplot_titles.append(
            (
                f"Reservoir: {row.project_name} | "
                f"Assigned {row.assigned_firo_allocation_kaf:.2f} KAF | "
                f"Physical {row.physical_firo_capacity_kaf:.2f} KAF"
            )
        )

    for row in control_point_limits.itertuples():
        subplot_titles.append(
            (
                f"Control Point: {row.control_point_name} "
                f"({row.control_point_id}) | "
                f"Limit {row.space_limit_kaf:.2f} KAF"
            )
        )

    subplot_titles.append(
        "Unified Reservoir and Control-Point Capacity Ribbon"
    )

    subplot_titles.append(
        "Reservoir Combined-Envelope Controller Ribbon"
    )

    row_heights = (
        [1.0] * reservoir_count
        + [1.0] * control_point_count
        + [0.75, 0.75]
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
    # Reservoir plots.
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
                    "Daily FIRO space: %{y:.2f} KAF<br>"
                    "Envelope controller: "
                    "%{customdata}<extra></extra>"
                ),
                customdata=project_data[
                    "controlling_component"
                ],
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
    # Control-point plots.
    # -------------------------------------------------------------------------

    first_control_point_row = reservoir_count + 1

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
                    "Unrouted FIRO loading: %{y:.2f} KAF<br>"
                    "Status: %{customdata}<extra></extra>"
                ),
                customdata=cp_data[
                    "control_point_status_label"
                ],
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
    # Unified reservoir + control-point capacity ribbon.
    # -------------------------------------------------------------------------

    reservoir_ribbon = reservoir_data[
        [
            "project_name",
            "date",
            "reservoir_status_code",
            "reservoir_status_label",
        ]
    ].copy()

    reservoir_ribbon[
        "location_label"
    ] = "Reservoir | " + reservoir_ribbon["project_name"]

    reservoir_ribbon[
        ["common_status_code", "common_status_label"]
    ] = reservoir_ribbon.apply(
        lambda row: pd.Series(
            map_reservoir_status(
                int(row["reservoir_status_code"]),
                str(row["reservoir_status_label"]),
            )
        ),
        axis=1,
    )

    control_point_ribbon = control_point_data[
        [
            "control_point_name",
            "date",
            "control_point_status_code",
            "control_point_status_label",
        ]
    ].copy()

    control_point_ribbon[
        "location_label"
    ] = (
        "Control Point | "
        + control_point_ribbon["control_point_name"]
    )

    control_point_ribbon[
        ["common_status_code", "common_status_label"]
    ] = control_point_ribbon.apply(
        lambda row: pd.Series(
            map_control_point_status(
                int(row["control_point_status_code"]),
                str(row["control_point_status_label"]),
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
                    "common_status_code",
                    "common_status_label",
                ]
            ],
            control_point_ribbon[
                [
                    "location_label",
                    "date",
                    "common_status_code",
                    "common_status_label",
                ]
            ],
        ],
        ignore_index=True,
    )

    reservoir_location_order = [
        f"Reservoir | {name}"
        for name in reservoir_limits["project_name"]
    ]

    control_point_location_order = [
        f"Control Point | {name}"
        for name in control_point_limits["control_point_name"]
    ]

    combined_location_order = (
        reservoir_location_order
        + control_point_location_order
    )

    capacity_status_matrix = combined_ribbon.pivot(
        index="location_label",
        columns="date",
        values="common_status_code",
    ).reindex(
        index=combined_location_order
    )

    capacity_label_matrix = combined_ribbon.pivot(
        index="location_label",
        columns="date",
        values="common_status_label",
    ).reindex(
        index=combined_location_order,
        columns=capacity_status_matrix.columns,
    )

    figure.add_trace(
        go.Heatmap(
            x=capacity_status_matrix.columns,
            y=capacity_status_matrix.index,
            z=capacity_status_matrix.values,
            customdata=capacity_label_matrix.values,
            colorscale=capacity_ribbon_colors(),
            zmin=-0.5,
            zmax=4.5,
            showscale=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Capacity status: %{customdata}<extra></extra>"
            ),
        ),
        row=reservoir_ribbon_row,
        col=1,
    )

    figure.update_yaxes(
        title_text="Location",
        row=reservoir_ribbon_row,
        col=1,
    )

    # -------------------------------------------------------------------------
    # Reservoir envelope-controller ribbon.
    # -------------------------------------------------------------------------

    controller_data = reservoir_data[
        [
            "project_name",
            "date",
            "controlling_component",
        ]
    ].copy()

    controller_data["controlling_component"] = (
        controller_data["controlling_component"]
        .fillna("UNKNOWN")
        .astype(str)
        .str.upper()
    )

    controller_data["controller_code"] = (
        controller_data["controlling_component"]
        .map(CONTROLLER_CODE)
        .fillna(CONTROLLER_CODE["UNKNOWN"])
    )

    controller_data["controller_label"] = (
        controller_data["controller_code"]
        .map(CONTROLLER_LABEL)
    )

    controller_matrix = controller_data.pivot(
        index="project_name",
        columns="date",
        values="controller_code",
    ).reindex(
        index=reservoir_limits["project_name"]
    )

    controller_label_matrix = controller_data.pivot(
        index="project_name",
        columns="date",
        values="controller_label",
    ).reindex(
        index=reservoir_limits["project_name"],
        columns=controller_matrix.columns,
    )

    figure.add_trace(
        go.Heatmap(
            x=controller_matrix.columns,
            y=controller_matrix.index,
            z=controller_matrix.values,
            customdata=controller_label_matrix.values,
            colorscale=controller_ribbon_colors(),
            zmin=-0.5,
            zmax=8.5,
            showscale=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Combined-envelope controller: %{customdata}"
                "<extra></extra>"
            ),
        ),
        row=controller_ribbon_row,
        col=1,
    )

    figure.update_yaxes(
        title_text="Reservoir",
        row=controller_ribbon_row,
        col=1,
    )

    figure.update_xaxes(
        title_text="Date",
        row=controller_ribbon_row,
        col=1,
    )

    figure.update_layout(
        title=(
            f"Alternative {alternative_id}: {alternative_name}"
            "<br><sup>"
            "Lines: blue = daily FIRO space/loading; "
            "purple dashed = assigned reservoir allocation; "
            "black dotted = physical reservoir capacity or static "
            "control-point limit."
            "<br>"
            "Capacity ribbon: gray = no FIRO/loading; "
            "white = geometry/headroom; amber = near; "
            "purple = assigned allocation binding; "
            "red = physical or control-point binding."
            "<br>"
            "Controller ribbon: gray = Rule Curve; "
            "red = A; blue = C; dark gray = E; green = H; "
            "purple = I; pink = J; orange = K."
            "</sup>"
        ),
        template="plotly_white",
        height=max(2500, 115 * total_rows + 275),
        hovermode="x unified",
        margin=dict(l=125, r=55, t=170, b=75),
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
            "Open Constraint and Controller Overview</a></td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FIRO Constraint and Controller Review</title>
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
    min-width: 850px;
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
<h1>FIRO Constraint and Envelope-Controller Review</h1>

<div class="note">
Each alternative page places physical reservoirs, control points, a unified
capacity-constraint ribbon, and a combined-envelope controller ribbon on
one vertically scrollable page. If no reservoir or control-point row is
purple or red on a date, the selected component geometry and seasonal timing
are limiting FIRO space rather than a static capacity constraint.
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
            "Missing reservoir status input:\n"
            f"  {RESERVOIR_FILE}\n\n"
            "Run 11_build_capacity_constraint_review.py first."
        )

    if not CONTROL_POINT_FILE.exists():
        raise FileNotFoundError(
            "Missing control-point status input:\n"
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
            "constraint_controller_overview.html"
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
    print("=" * 74)
    print("FIRO CONSTRAINT AND CONTROLLER OVERVIEW COMPLETE")
    print("=" * 74)
    print(f"Created alternative overview pages: {len(entries)}")
    print(f"Open: {OUTPUT_DIRECTORY / 'index.html'}")


if __name__ == "__main__":
    main()