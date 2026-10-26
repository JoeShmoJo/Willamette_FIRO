"""
Create one scrollable Alternative Overview page per alternative.

Each page contains:
- One compact daily FIRO-space line plot for every physical reservoir.
- A stacked no-routing Salem/system FIRO-space loading plot.
- A Salem percent-of-static-limit utilization plot.

All panels share the same date axis.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REVIEW_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "review"
    / "no_routing_utilization"
)

RESERVOIR_FILE = (
    REVIEW_DIRECTORY
    / "01_reservoir_daily_firo_utilization.csv"
)

CONTROL_POINT_FILE = (
    REVIEW_DIRECTORY
    / "02_control_point_daily_unrouted_loading.csv"
)

OUTPUT_DIRECTORY = (
    REVIEW_DIRECTORY
    / "alternative_overviews"
)

INCLUDE_PLOTLY_JS = "directory"


def write_figure(figure: go.Figure, path: Path) -> None:
    figure.write_html(
        path,
        include_plotlyjs=INCLUDE_PLOTLY_JS,
        full_html=True,
    )


def build_overview(
    alternative_id: int,
    alternative_name: str,
    reservoir_data: pd.DataFrame,
    salem_data: pd.DataFrame,
) -> go.Figure:
    reservoir_data = reservoir_data.sort_values("date").copy()
    salem_data = salem_data.sort_values("date").copy()

    reservoir_limits = (
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

    project_count = len(reservoir_limits)

    total_rows = project_count + 2

    subplot_titles = []

    for row in reservoir_limits.itertuples():
        subplot_titles.append(
            (
                f"{row.project_name} - Assigned FIRO Space: "
                f"{row.allocated_project_firo_space_kaf:.2f} KAF"
            )
        )

    subplot_titles.append(
        "System / Salem Unrouted FIRO-Space Loading"
    )

    subplot_titles.append(
        "System / Salem Static Limit Utilization"
    )

    figure = make_subplots(
        rows=total_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.012,
        subplot_titles=subplot_titles,
    )

    # -------------------------------------------------------------------------
    # One small line chart per physical reservoir.
    # -------------------------------------------------------------------------

    for row_number, project_row in enumerate(
        reservoir_limits.itertuples(),
        start=1,
    ):
        project_data = reservoir_data.loc[
            reservoir_data["project_id"] == project_row.project_id
        ].sort_values("date")

        limit_kaf = float(
            project_row.allocated_project_firo_space_kaf
        )

        figure.add_trace(
            go.Scatter(
                x=project_data["date"],
                y=project_data["combined_offset_kaf"],
                mode="lines",
                name=project_row.project_name,
                showlegend=False,
                line=dict(
                    color="#1f4e79",
                    width=2.3,
                ),
                hovertemplate=(
                    f"<b>{project_row.project_name}</b><br>"
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

        figure.update_yaxes(
            title_text="KAF",
            range=[0.0, max(limit_kaf, 0.1)],
            row=row_number,
            col=1,
        )

    # -------------------------------------------------------------------------
    # Salem stacked no-routing FIRO-space loading.
    # -------------------------------------------------------------------------

    salem_row = project_count + 1
    utilization_row = project_count + 2

    salem_limit_kaf = float(
        salem_data["space_limit_kaf"].iloc[0]
    )

    for allocation_unit_name, unit_data in salem_data.groupby(
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
                stackgroup="salem_loading",
                hovertemplate=(
                    f"<b>{allocation_unit_name}</b><br>"
                    "Date: %{x|%d %b %Y}<br>"
                    "Unrouted FIRO contribution: %{y:.2f} KAF"
                    "<extra></extra>"
                ),
            ),
            row=salem_row,
            col=1,
        )

    salem_total = (
        salem_data[
            [
                "date",
                "unrouted_control_point_loading_kaf",
                "control_point_utilization_percent",
            ]
        ]
        .drop_duplicates()
        .sort_values("date")
    )

    figure.add_trace(
        go.Scatter(
            x=salem_total["date"],
            y=[salem_limit_kaf] * len(salem_total),
            mode="lines",
            name="Salem Static Limit",
            line=dict(
                color="#111111",
                width=2.5,
                dash="dash",
            ),
            hovertemplate=(
                "<b>Salem Static Limit</b><br>"
                "Limit: %{y:.2f} KAF<extra></extra>"
            ),
        ),
        row=salem_row,
        col=1,
    )

    figure.update_yaxes(
        title_text="KAF",
        rangemode="tozero",
        row=salem_row,
        col=1,
    )

    # -------------------------------------------------------------------------
    # Salem percent utilization.
    # -------------------------------------------------------------------------

    figure.add_trace(
        go.Scatter(
            x=salem_total["date"],
            y=salem_total[
                "control_point_utilization_percent"
            ],
            mode="lines",
            name="Salem Limit Used",
            line=dict(
                color="#7f0000",
                width=3,
            ),
            hovertemplate=(
                "<b>Salem Limit Used</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Static limit used: %{y:.1f}%<extra></extra>"
            ),
        ),
        row=utilization_row,
        col=1,
    )

    figure.add_hline(
        y=100.0,
        line_color="#111111",
        line_dash="dash",
        line_width=2,
        row=utilization_row,
        col=1,
    )

    figure.update_yaxes(
        title_text="Percent",
        range=[
            0.0,
            max(
                110.0,
                float(
                    salem_total[
                        "control_point_utilization_percent"
                    ].max()
                )
                * 1.10,
            ),
        ],
        row=utilization_row,
        col=1,
    )

    figure.update_layout(
        title=(
            f"Alternative {alternative_id}: {alternative_name}"
            "<br><sup>Reservoir and Salem no-routing FIRO-space review. "
            "All panels use the same date axis.</sup>"
        ),
        template="plotly_white",
        height=max(900, 145 * total_rows + 150),
        hovermode="x unified",
        legend=dict(
            title=dict(text="Salem Contributors"),
            x=1.02,
            xanchor="left",
            y=1.0,
            yanchor="top",
        ),
        margin=dict(l=90, r=290, t=105, b=75),
    )

    figure.update_xaxes(
        title_text="Date",
        row=total_rows,
        col=1,
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
            "Open Alternative Overview</a></td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FIRO Alternative Overview Pages</title>
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
    max-width: 950px;
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
<h1>FIRO Alternative Overview Pages</h1>

<div class="note">
Each overview page places physical reservoir FIRO-space use and the
system-level Salem FIRO-space screen on one vertically scrollable page.
All panels share the same date axis. These are no-routing storage-space
screening plots; they do not represent routed flow, local inflow, or
operational release routing.
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

<p><a href="../index.html">Return to No-Routing Review Index</a></p>
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
            "Missing reservoir daily utilization file:\n"
            f"  {RESERVOIR_FILE}\n\n"
            "Run 09_build_no_routing_utilization_review.py first."
        )

    if not CONTROL_POINT_FILE.exists():
        raise FileNotFoundError(
            "Missing control-point daily utilization file:\n"
            f"  {CONTROL_POINT_FILE}\n\n"
            "Run 09_build_no_routing_utilization_review.py first."
        )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    reservoir_daily = pd.read_csv(RESERVOIR_FILE)
    control_point_daily = pd.read_csv(CONTROL_POINT_FILE)

    reservoir_daily["date"] = pd.to_datetime(
        reservoir_daily["date"]
    )

    control_point_daily["date"] = pd.to_datetime(
        control_point_daily["date"]
    )

    salem_contributions = control_point_daily.loc[
        control_point_daily["control_point_id"] == "SALEM"
    ].copy()

    entries = []

    for alternative_id, reservoir_data in reservoir_daily.groupby(
        "alternative_id",
        sort=True,
    ):
        alternative_name = str(
            reservoir_data["alternative_name"].iloc[0]
        )

        salem_data = salem_contributions.loc[
            salem_contributions["alternative_id"] == alternative_id
        ].copy()

        if salem_data.empty:
            continue

        figure = build_overview(
            alternative_id=int(alternative_id),
            alternative_name=alternative_name,
            reservoir_data=reservoir_data,
            salem_data=salem_data,
        )

        filename = (
            f"alternative_{int(alternative_id):02d}_"
            "overview.html"
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
    print("FIRO ALTERNATIVE OVERVIEW PAGES COMPLETE")
    print("=" * 72)
    print(f"Created overview pages: {len(entries)}")
    print(f"Open: {OUTPUT_DIRECTORY / 'index.html'}")


if __name__ == "__main__":
    main()