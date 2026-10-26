"""
Build FIRO capacity-constraint review pages.

This is a no-routing storage-space screening product.

Reservoir pages:
- Daily FIRO offset plotted from zero to physical FIRO capacity.
- Purple line: assigned FIRO allocation.
- Black dashed line: physical FIRO / evacuation-room capacity.
- Bottom ribbon: reservoir constraint status.

Control-point pages:
- Daily unrouted FIRO-space loading plotted from zero to the static
  control-point FIRO-space limit.
- Bottom ribbon: control-point constraint status.

No reach routing, local inflows, attenuation, or operational releases
are represented.
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
    / "capacity_constraint_review"
)

CAPPED_DAILY_FILE = (
    OUTPUT_DIRECTORY
    / "36_project_combined_daily_curves_capped.csv"
)

RAW_DAILY_FILE = (
    OUTPUT_DIRECTORY
    / "32_project_combined_daily_curves.csv"
)

PHYSICAL_ALLOCATION_FILE = (
    OUTPUT_DIRECTORY
    / "25_alternative_physical_project_allocations.csv"
)

DECISION_UNIT_ALLOCATION_FILE = (
    OUTPUT_DIRECTORY
    / "24_alternative_decision_unit_allocations.csv"
)

CONTROL_POINT_RELATIONSHIP_FILE = (
    OUTPUT_DIRECTORY
    / "21_static_control_point_relationships.csv"
)

INCLUDE_PLOTLY_JS = "directory"
TOLERANCE_KAF = 1.0e-6


# =============================================================================
# HELPERS
# =============================================================================

def choose_daily_file() -> Path:
    """Prefer capped daily combined curves."""
    if CAPPED_DAILY_FILE.exists():
        return CAPPED_DAILY_FILE

    if RAW_DAILY_FILE.exists():
        return RAW_DAILY_FILE

    raise FileNotFoundError(
        "Could not find a daily combined-curve file."
    )


def write_figure(figure: go.Figure, path: Path) -> None:
    figure.write_html(
        path,
        include_plotlyjs=INCLUDE_PLOTLY_JS,
        full_html=True,
    )


def safe_filename(value: str) -> str:
    return (
        str(value)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def reservoir_status(
    daily_offset_kaf: float,
    assigned_allocation_kaf: float,
    physical_capacity_kaf: float,
) -> tuple[int, str]:
    """
    Return a discrete reservoir constraint-status code and label.

    Codes:
        0 = no active FIRO space
        1 = geometry/timing limited
        2 = near assigned allocation
        3 = assigned allocation binding / downstream-limited
        4 = near physical capacity
        5 = physical capacity binding
    """
    if daily_offset_kaf <= TOLERANCE_KAF:
        return 0, "No active FIRO space"

    physical_equals_assigned = (
        abs(physical_capacity_kaf - assigned_allocation_kaf)
        <= TOLERANCE_KAF
    )

    if physical_equals_assigned:
        utilization = (
            daily_offset_kaf / physical_capacity_kaf
            if physical_capacity_kaf > TOLERANCE_KAF
            else 0.0
        )

        if utilization >= 0.995:
            return 5, "Physical capacity binding"

        if utilization >= 0.95:
            return 4, "Near physical capacity"

        return 1, "Geometry or seasonal timing limited"

    assigned_utilization = (
        daily_offset_kaf / assigned_allocation_kaf
        if assigned_allocation_kaf > TOLERANCE_KAF
        else 0.0
    )

    if assigned_utilization >= 0.995:
        return 3, "Assigned allocation binding (downstream-limited)"

    if assigned_utilization >= 0.95:
        return 2, "Near assigned allocation"

    return 1, "Geometry or seasonal timing limited"


def control_point_status(
    utilization_percent: float,
    daily_loading_kaf: float,
) -> tuple[int, str]:
    """
    Return a discrete control-point constraint-status code and label.

    Codes:
        0 = no active FIRO loading
        1 = control-point headroom remains
        2 = near control-point limit
        3 = control-point binding
    """
    if daily_loading_kaf <= TOLERANCE_KAF:
        return 0, "No active FIRO loading"

    if utilization_percent >= 99.5:
        return 3, "Control-point limit binding"

    if utilization_percent >= 95.0:
        return 2, "Near control-point limit"

    return 1, "Control-point headroom remains"


# =============================================================================
# FIGURE BUILDERS
# =============================================================================

def build_reservoir_page(
    alternative_id: int,
    alternative_name: str,
    reservoir_data: pd.DataFrame,
) -> go.Figure:
    """
    Create reservoir small multiples plus a categorical status ribbon.
    """
    reservoir_data = reservoir_data.sort_values("date").copy()

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

    project_count = len(reservoir_limits)
    total_rows = project_count + 1

    subplot_titles = []

    for row in reservoir_limits.itertuples():
        subplot_titles.append(
            (
                f"{row.project_name} - Assigned: "
                f"{row.assigned_firo_allocation_kaf:.2f} KAF; "
                f"Physical: {row.physical_firo_capacity_kaf:.2f} KAF"
            )
        )

    subplot_titles.append(
        "Reservoir Constraint Status Ribbon"
    )

    figure = make_subplots(
        rows=total_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.012,
        subplot_titles=subplot_titles,
    )

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
                name=limit_row.project_name,
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.3,
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
                name="Assigned FIRO Allocation",
                showlegend=False,
                line=dict(
                    color="#7b4fa3",
                    width=1.8,
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
                name="Physical FIRO Capacity",
                showlegend=False,
                line=dict(
                    color="#111111",
                    width=1.8,
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

    ribbon_row = total_rows

    status_matrix = reservoir_data.pivot(
        index="project_name",
        columns="date",
        values="reservoir_status_code",
    ).sort_index()

    label_matrix = reservoir_data.pivot(
        index="project_name",
        columns="date",
        values="reservoir_status_label",
    ).reindex(
        index=status_matrix.index,
        columns=status_matrix.columns,
    )

    discrete_colors = [
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

    figure.add_trace(
        go.Heatmap(
            x=status_matrix.columns,
            y=status_matrix.index,
            z=status_matrix.values,
            customdata=label_matrix.values,
            colorscale=discrete_colors,
            zmin=-0.5,
            zmax=5.5,
            colorbar=dict(
                title="Status",
                tickmode="array",
                tickvals=[0, 1, 2, 3, 4, 5],
                ticktext=[
                    "No FIRO",
                    "Geometry",
                    "Near Allocation",
                    "Allocation Binding",
                    "Near Physical",
                    "Physical Binding",
                ],
            ),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Status: %{customdata}<extra></extra>"
            ),
        ),
        row=ribbon_row,
        col=1,
    )

    figure.update_layout(
        title=(
            f"Alternative {alternative_id}: {alternative_name}"
            "<br><sup>Reservoir physical capacity, assigned FIRO allocation, "
            "and daily constraint status. No-routing screening.</sup>"
        ),
        template="plotly_white",
        height=max(950, 135 * total_rows + 180),
        hovermode="x unified",
        margin=dict(l=95, r=240, t=105, b=75),
    )

    figure.update_yaxes(
        title_text="Reservoir",
        row=ribbon_row,
        col=1,
    )

    figure.update_xaxes(
        title_text="Date",
        row=ribbon_row,
        col=1,
    )

    return figure


def build_control_point_page(
    alternative_id: int,
    alternative_name: str,
    control_point_data: pd.DataFrame,
) -> go.Figure:
    """
    Create control-point small multiples plus a categorical status ribbon.
    """
    control_point_data = control_point_data.sort_values("date").copy()

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

    control_point_count = len(control_point_limits)
    total_rows = control_point_count + 1

    subplot_titles = []

    for row in control_point_limits.itertuples():
        subplot_titles.append(
            (
                f"{row.control_point_name} ({row.control_point_id}) - "
                f"Static FIRO Limit: {row.space_limit_kaf:.2f} KAF"
            )
        )

    subplot_titles.append(
        "Control-Point Constraint Status Ribbon"
    )

    figure = make_subplots(
        rows=total_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.012,
        subplot_titles=subplot_titles,
    )

    for row_number, limit_row in enumerate(
        control_point_limits.itertuples(),
        start=1,
    ):
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
                name=limit_row.control_point_name,
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.3,
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
                name="Static FIRO Limit",
                showlegend=False,
                line=dict(
                    color="#111111",
                    width=1.8,
                    dash="dot",
                ),
                hovertemplate=(
                    "<b>Static FIRO Limit</b><br>"
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

    ribbon_row = total_rows

    status_matrix = control_point_data.pivot(
        index="control_point_name",
        columns="date",
        values="control_point_status_code",
    ).sort_index()

    label_matrix = control_point_data.pivot(
        index="control_point_name",
        columns="date",
        values="control_point_status_label",
    ).reindex(
        index=status_matrix.index,
        columns=status_matrix.columns,
    )

    discrete_colors = [
        [0.00, "#d9d9d9"],
        [0.24, "#d9d9d9"],
        [0.25, "#ffffff"],
        [0.49, "#ffffff"],
        [0.50, "#f4c542"],
        [0.74, "#f4c542"],
        [0.75, "#c00000"],
        [1.00, "#c00000"],
    ]

    figure.add_trace(
        go.Heatmap(
            x=status_matrix.columns,
            y=status_matrix.index,
            z=status_matrix.values,
            customdata=label_matrix.values,
            colorscale=discrete_colors,
            zmin=-0.5,
            zmax=3.5,
            colorbar=dict(
                title="Status",
                tickmode="array",
                tickvals=[0, 1, 2, 3],
                ticktext=[
                    "No Loading",
                    "Headroom",
                    "Near Limit",
                    "Binding",
                ],
            ),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Status: %{customdata}<extra></extra>"
            ),
        ),
        row=ribbon_row,
        col=1,
    )

    figure.update_layout(
        title=(
            f"Alternative {alternative_id}: {alternative_name}"
            "<br><sup>Daily unrouted control-point FIRO-space loading and "
            "static constraint status. No reach routing or local inflow.</sup>"
        ),
        template="plotly_white",
        height=max(950, 135 * total_rows + 180),
        hovermode="x unified",
        margin=dict(l=95, r=210, t=105, b=75),
    )

    figure.update_yaxes(
        title_text="Control Point",
        row=ribbon_row,
        col=1,
    )

    figure.update_xaxes(
        title_text="Date",
        row=ribbon_row,
        col=1,
    )

    return figure


# =============================================================================
# HTML INDEX
# =============================================================================

def write_html_index(entries: list[dict]) -> None:
    rows = []

    for entry in entries:
        rows.append(
            "<tr>"
            f"<td>{entry['alternative_id']}</td>"
            f"<td>{escape(entry['alternative_name'])}</td>"
            f'<td><a href="{escape(entry["reservoir_filename"])}">'
            "Reservoir Capacity Page</a></td>"
            f'<td><a href="{escape(entry["control_point_filename"])}">'
            "Control-Point Capacity Page</a></td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FIRO Capacity Constraint Review</title>
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
    min-width: 900px;
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
<h1>FIRO Capacity Constraint Review</h1>

<div class="note">
<b>Interpretation:</b> Reservoir pages distinguish physical FIRO capacity
from assigned FIRO allocation. Control-point pages compare daily unrouted
FIRO-space loading with each static control-point FIRO-space limit.
These are no-routing screening products, not routed-flow validation.
</div>

<table>
<thead>
<tr>
<th>Alternative</th>
<th>Name</th>
<th>Reservoirs</th>
<th>Control Points</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>

<h2>Supporting CSV Files</h2>
<ul>
<li><a href="01_reservoir_daily_capacity_status.csv">
01_reservoir_daily_capacity_status.csv</a></li>
<li><a href="02_control_point_daily_capacity_status.csv">
02_control_point_daily_capacity_status.csv</a></li>
<li><a href="03_control_point_daily_contributions.csv">
03_control_point_daily_contributions.csv</a></li>
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
    physical_allocations = pd.read_csv(PHYSICAL_ALLOCATION_FILE)
    decision_allocations = pd.read_csv(
        DECISION_UNIT_ALLOCATION_FILE
    )
    relationships = pd.read_csv(
        CONTROL_POINT_RELATIONSHIP_FILE
    )

    required_daily = {
        "alternative_id",
        "project_id",
        "project_name",
        "decision_unit_id",
        "date",
        "combined_offset_kaf",
        "allocated_project_firo_space_kaf",
    }

    missing_daily = required_daily - set(daily.columns)

    if missing_daily:
        raise ValueError(
            "Daily curve file is missing required columns:\n"
            + "\n".join(
                f"  - {column}"
                for column in sorted(missing_daily)
            )
        )

    required_physical = {
        "alternative_id",
        "project_id",
        "project_physical_cap_kaf",
    }

    missing_physical = (
        required_physical
        - set(physical_allocations.columns)
    )

    if missing_physical:
        raise ValueError(
            "Physical allocation file is missing required columns:\n"
            + "\n".join(
                f"  - {column}"
                for column in sorted(missing_physical)
            )
        )

    required_decision = {
        "alternative_id",
        "alternative_name",
        "decision_unit_id",
        "decision_unit_name",
    }

    missing_decision = (
        required_decision
        - set(decision_allocations.columns)
    )

    if missing_decision:
        raise ValueError(
            "Decision-unit allocation file is missing required columns:\n"
            + "\n".join(
                f"  - {column}"
                for column in sorted(missing_decision)
            )
        )

    required_relationship = {
        "decision_unit_id",
        "control_point_id",
        "control_point_name",
        "space_limit_kaf",
    }

    missing_relationship = (
        required_relationship
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

    if "alternative_name" in daily.columns:
        daily = daily.drop(columns=["alternative_name"])

    alternative_lookup = (
        decision_allocations[
            [
                "alternative_id",
                "alternative_name",
            ]
        ]
        .drop_duplicates()
    )

    decision_unit_lookup = (
        decision_allocations[
            [
                "alternative_id",
                "decision_unit_id",
                "decision_unit_name",
            ]
        ]
        .drop_duplicates()
    )

    physical_cap_lookup = (
        physical_allocations[
            [
                "alternative_id",
                "project_id",
                "project_physical_cap_kaf",
            ]
        ]
        .drop_duplicates()
        .rename(
            columns={
                "project_physical_cap_kaf": (
                    "physical_firo_capacity_kaf"
                ),
            }
        )
    )

    daily = daily.merge(
        alternative_lookup,
        on="alternative_id",
        how="left",
        validate="many_to_one",
    )

    daily = daily.merge(
        physical_cap_lookup,
        on=[
            "alternative_id",
            "project_id",
        ],
        how="left",
        validate="many_to_one",
    )

    daily["physical_firo_capacity_kaf"] = (
        pd.to_numeric(
            daily["physical_firo_capacity_kaf"],
            errors="coerce",
        )
        .fillna(
            daily["allocated_project_firo_space_kaf"]
        )
    )

    # -------------------------------------------------------------------------
    # Reservoir daily capacity status.
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
            "physical_firo_capacity_kaf",
            "controlling_component",
        ]
    ].copy()

    reservoir_daily = reservoir_daily.rename(
        columns={
            "allocated_project_firo_space_kaf": (
                "assigned_firo_allocation_kaf"
            ),
        }
    )

    status_values = reservoir_daily.apply(
        lambda row: reservoir_status(
            daily_offset_kaf=row["combined_offset_kaf"],
            assigned_allocation_kaf=(
                row["assigned_firo_allocation_kaf"]
            ),
            physical_capacity_kaf=(
                row["physical_firo_capacity_kaf"]
            ),
        ),
        axis=1,
    )

    reservoir_daily[
        "reservoir_status_code"
    ] = status_values.apply(lambda value: value[0])

    reservoir_daily[
        "reservoir_status_label"
    ] = status_values.apply(lambda value: value[1])

    reservoir_daily["physical_capacity_utilization_percent"] = (
        100.0
        * reservoir_daily["combined_offset_kaf"]
        / reservoir_daily["physical_firo_capacity_kaf"].where(
            reservoir_daily["physical_firo_capacity_kaf"]
            > TOLERANCE_KAF
        )
    )

    reservoir_daily["assigned_allocation_utilization_percent"] = (
        100.0
        * reservoir_daily["combined_offset_kaf"]
        / reservoir_daily["assigned_firo_allocation_kaf"].where(
            reservoir_daily["assigned_firo_allocation_kaf"]
            > TOLERANCE_KAF
        )
    )

    reservoir_daily[
        "physical_capacity_utilization_percent"
    ] = reservoir_daily[
        "physical_capacity_utilization_percent"
    ].fillna(0.0)

    reservoir_daily[
        "assigned_allocation_utilization_percent"
    ] = reservoir_daily[
        "assigned_allocation_utilization_percent"
    ].fillna(0.0)

    reservoir_daily.to_csv(
        REVIEW_DIRECTORY
        / "01_reservoir_daily_capacity_status.csv",
        index=False,
    )

    # -------------------------------------------------------------------------
    # Allocation-unit and control-point daily no-routing loading.
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

    relationship_map = relationships[
        [
            "decision_unit_id",
            "control_point_id",
            "control_point_name",
            "space_limit_kaf",
        ]
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

    cp_status_values = control_point_daily.apply(
        lambda row: control_point_status(
            utilization_percent=(
                row["control_point_utilization_percent"]
            ),
            daily_loading_kaf=(
                row["unrouted_control_point_loading_kaf"]
            ),
        ),
        axis=1,
    )

    control_point_daily[
        "control_point_status_code"
    ] = cp_status_values.apply(lambda value: value[0])

    control_point_daily[
        "control_point_status_label"
    ] = cp_status_values.apply(lambda value: value[1])

    control_point_daily.to_csv(
        REVIEW_DIRECTORY
        / "02_control_point_daily_capacity_status.csv",
        index=False,
    )

    control_point_contributions = control_point_contributions.merge(
        control_point_daily[
            [
                "alternative_id",
                "control_point_id",
                "date",
                "unrouted_control_point_loading_kaf",
                "control_point_utilization_percent",
                "control_point_status_code",
                "control_point_status_label",
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
        / "03_control_point_daily_contributions.csv",
        index=False,
    )

    # -------------------------------------------------------------------------
    # Build one reservoir page and one control-point page per alternative.
    # -------------------------------------------------------------------------

    index_entries = []

    for alternative_id, alternative_reservoir_data in reservoir_daily.groupby(
        "alternative_id",
        sort=True,
    ):
        alternative_name = str(
            alternative_reservoir_data[
                "alternative_name"
            ].iloc[0]
        )

        alternative_control_point_data = control_point_daily.loc[
            control_point_daily["alternative_id"] == alternative_id
        ].copy()

        reservoir_filename = (
            f"alternative_{int(alternative_id):02d}_"
            "reservoir_capacity_review.html"
        )

        control_point_filename = (
            f"alternative_{int(alternative_id):02d}_"
            "control_point_capacity_review.html"
        )

        reservoir_figure = build_reservoir_page(
            alternative_id=int(alternative_id),
            alternative_name=alternative_name,
            reservoir_data=alternative_reservoir_data,
        )

        write_figure(
            reservoir_figure,
            REVIEW_DIRECTORY / reservoir_filename,
        )

        control_point_figure = build_control_point_page(
            alternative_id=int(alternative_id),
            alternative_name=alternative_name,
            control_point_data=alternative_control_point_data,
        )

        write_figure(
            control_point_figure,
            REVIEW_DIRECTORY / control_point_filename,
        )

        index_entries.append(
            {
                "alternative_id": int(alternative_id),
                "alternative_name": alternative_name,
                "reservoir_filename": reservoir_filename,
                "control_point_filename": control_point_filename,
            }
        )

    write_html_index(index_entries)

    print()
    print("=" * 74)
    print("FIRO CAPACITY CONSTRAINT REVIEW COMPLETE")
    print("=" * 74)
    print(f"Daily input used: {daily_file.name}")
    print(f"Review directory: {REVIEW_DIRECTORY}")
    print(f"Alternatives: {len(index_entries)}")
    print()
    print("Created:")
    print("  01_reservoir_daily_capacity_status.csv")
    print("  02_control_point_daily_capacity_status.csv")
    print("  03_control_point_daily_contributions.csv")
    print()
    print("Open this file first:")
    print(REVIEW_DIRECTORY / "index.html")


if __name__ == "__main__":
    main()