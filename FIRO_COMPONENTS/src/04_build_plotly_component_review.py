"""
Build interactive Plotly component-review pages.

Each page contains only:
  1. Storage curves (rule curve, individual components, combined envelope)
  2. Storage offsets above the rule curve

Use the standard Plotly legend on the right:
  - Click an item to show/hide that item.
  - Double-click an item to isolate it.
  - Component legend items control both their storage and offset traces.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "diagnostics"
REVIEW_DIRECTORY = OUTPUT_DIRECTORY / "plotly_component_review"

# Prefer capped curves when they are available.
CAPPED_COMPONENT_FILE = OUTPUT_DIRECTORY / "35_component_daily_curves_capped.csv"
RAW_COMPONENT_FILE = OUTPUT_DIRECTORY / "31_component_daily_curves.csv"

# Share the offline Plotly library across pages in this directory.
INCLUDE_PLOTLY_JS = "directory"


COMPONENT_COLORS = {
    "A": "#d62728",  # red
    "C": "#1f77b4",  # blue
    "E": "#7f7f7f",  # gray
    "H": "#2ca02c",  # green
    "I": "#9467bd",  # purple
    "J": "#e377c2",  # pink
    "K": "#ff7f0e",  # orange
}

COMPONENT_NAMES = {
    "A": "A - Flat Winter Pool",
    "C": "C - Early Refill",
    "E": "E - Maximum-Conservation Cutover",
    "H": "H - Two-Segment Refill",
    "I": "I - April 1 Refill",
    "J": "J - Time-Shifted Rule Curve",
    "K": "K - Early Refill Cutover",
}


def choose_component_file() -> Path:
    if CAPPED_COMPONENT_FILE.exists():
        return CAPPED_COMPONENT_FILE
    if RAW_COMPONENT_FILE.exists():
        return RAW_COMPONENT_FILE

    raise FileNotFoundError(
        "Could not find component daily curves. Expected either:\n"
        f"  {CAPPED_COMPONENT_FILE}\n"
        f"  {RAW_COMPONENT_FILE}"
    )


def add_paired_trace(
    figure: go.Figure,
    dates: pd.Series,
    storage: pd.Series,
    offset: pd.Series,
    name: str,
    color: str,
    width: float = 2.0,
    dash: str = "solid",
) -> None:
    """
    Add matching storage and offset traces.

    Both traces share a legend group. The visible legend entry controls
    the matching curve in both panels.
    """
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=storage,
            mode="lines",
            name=name,
            legendgroup=name,
            showlegend=True,
            line=dict(color=color, width=width, dash=dash),
            hovertemplate=(
                "<b>%{fullData.name}</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Storage: %{y:.2f} KAF<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=dates,
            y=offset,
            mode="lines",
            name=name,
            legendgroup=name,
            showlegend=False,
            line=dict(color=color, width=width, dash=dash),
            hovertemplate=(
                "<b>%{fullData.name}</b><br>"
                "Date: %{x|%d %b %Y}<br>"
                "Offset: %{y:.2f} KAF<extra></extra>"
            ),
        ),
        row=2,
        col=1,
    )


def build_review_figure(
    project_data: pd.DataFrame,
    alternative_id: int,
    project_name: str,
) -> go.Figure:
    project_data = project_data.copy()
    project_data["date"] = pd.to_datetime(project_data["date"])
    project_data = project_data.sort_values("date")

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.10,
        subplot_titles=(
            "Storage Curves",
            "Storage Offset Above Rule Curve",
        ),
    )

    # Rule curve: identical across components, so retain one daily record.
    rule = (
        project_data[
            ["date", "rule_storage_kaf"]
        ]
        .drop_duplicates(subset=["date"])
        .sort_values("date")
    )

    rule_offset = pd.Series(0.0, index=rule.index)

    add_paired_trace(
        figure=figure,
        dates=rule["date"],
        storage=rule["rule_storage_kaf"],
        offset=rule_offset,
        name="Rule Curve",
        color="#000000",
        width=3.0,
    )

    # Individual FIRO component curves.
    component_codes = sorted(project_data["component_code"].dropna().unique())

    component_storage_frames = []

    for component_code in component_codes:
        component = (
            project_data.loc[
                project_data["component_code"] == component_code,
                [
                    "date",
                    "component_storage_kaf",
                    "component_offset_kaf",
                ],
            ]
            .dropna(subset=["component_storage_kaf"])
            .sort_values("date")
        )

        if component.empty:
            continue

        component_name = COMPONENT_NAMES.get(
            component_code,
            f"{component_code} Component",
        )
        component_color = COMPONENT_COLORS.get(component_code, "#666666")

        add_paired_trace(
            figure=figure,
            dates=component["date"],
            storage=component["component_storage_kaf"],
            offset=component["component_offset_kaf"].fillna(0.0),
            name=component_name,
            color=component_color,
            width=2.0,
        )

        component_storage_frames.append(
            component[["date", "component_storage_kaf"]].rename(
                columns={
                    "component_storage_kaf": f"component_{component_code}",
                }
            )
        )

    # Combined envelope is the daily maximum of all displayed component curves.
    if component_storage_frames:
        combined = component_storage_frames[0]

        for component_frame in component_storage_frames[1:]:
            combined = combined.merge(component_frame, on="date", how="outer")

        component_columns = [
            column
            for column in combined.columns
            if column.startswith("component_")
        ]

        combined["combined_storage_kaf"] = combined[component_columns].max(axis=1)

        combined = combined.merge(rule, on="date", how="left")

        # The combined FIRO envelope must include the rule curve.
        # It can never be below the rule curve.
        combined["combined_storage_kaf"] = combined[
            ["combined_storage_kaf", "rule_storage_kaf"]
        ].max(axis=1)
        combined["combined_offset_kaf"] = (
            combined["combined_storage_kaf"]
            - combined["rule_storage_kaf"]
        )

        combined = combined.sort_values("date")

        add_paired_trace(
            figure=figure,
            dates=combined["date"],
            storage=combined["combined_storage_kaf"],
            offset=combined["combined_offset_kaf"].fillna(0.0),
            name="Combined FIRO Envelope",
            color="#111111",
            width=3.5,
            dash="dash",
        )

    figure.update_layout(
        title=(
            f"Alternative {alternative_id} - {project_name}"
            "<br><sup>Click legend items to show/hide curves; "
            "double-click an item to isolate it.</sup>"
        ),
        template="plotly_white",
        height=850,
        hovermode="x unified",
        margin=dict(l=80, r=290, t=100, b=70),
        legend=dict(
            title=dict(text="Curves"),
            x=1.02,
            xanchor="left",
            y=1.0,
            yanchor="top",
            bgcolor="rgba(255,255,255,0.90)",
            bordercolor="#B0B0B0",
            borderwidth=1,
            groupclick="togglegroup",
        ),
    )

    figure.update_yaxes(
        title_text="Storage (KAF)",
        row=1,
        col=1,
        rangemode="tozero",
    )
    figure.update_yaxes(
        title_text="Offset (KAF)",
        row=2,
        col=1,
        rangemode="tozero",
    )
    figure.update_xaxes(
        title_text="Date",
        row=2,
        col=1,
    )

    return figure


def write_index(entries: list[tuple[str, str, int, str]]) -> None:
    rows = []

    for filename, label, alternative_id, project_name in entries:
        rows.append(
            "<tr>"
            f"<td>{alternative_id}</td>"
            f"<td>{escape(project_name)}</td>"
            f'<td><a href="{escape(filename)}">{escape(label)}</a></td>'
            "</tr>"
        )

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FIRO Component Review</title>
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 32px;
    color: #222;
}}
table {{
    border-collapse: collapse;
    min-width: 650px;
}}
th, td {{
    border: 1px solid #cccccc;
    padding: 8px 12px;
    text-align: left;
}}
th {{
    background-color: #e9eef5;
}}
tr:nth-child(even) {{
    background-color: #f7f7f7;
}}
a {{
    color: #0645ad;
}}
</style>
</head>
<body>
<h1>FIRO Component Review</h1>
<p>
Each plot has two panels only: storage curves and storage offset.
Use the legend at right to show or hide curves. Double-click a legend
item to isolate it.
</p>
<table>
<thead>
<tr>
<th>Alternative</th>
<th>Project</th>
<th>Open Review Plot</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</body>
</html>
"""

    (REVIEW_DIRECTORY / "index.html").write_text(
        index_html,
        encoding="utf-8",
    )


def main() -> None:
    component_file = choose_component_file()
    REVIEW_DIRECTORY.mkdir(parents=True, exist_ok=True)

    component_data = pd.read_csv(component_file)
    component_data["date"] = pd.to_datetime(component_data["date"])

    required_columns = {
        "alternative_id",
        "project_id",
        "project_name",
        "component_code",
        "date",
        "rule_storage_kaf",
        "component_storage_kaf",
        "component_offset_kaf",
    }

    missing_columns = required_columns - set(component_data.columns)
    if missing_columns:
        raise ValueError(
            "The component curve file is missing required columns:\n"
            + ", ".join(sorted(missing_columns))
        )

    entries = []

    group_columns = [
        "alternative_id",
        "project_id",
        "project_name",
    ]

    for group_values, project_data in component_data.groupby(
        group_columns,
        sort=True,
    ):
        alternative_id, project_id, project_name = group_values

        figure = build_review_figure(
            project_data=project_data,
            alternative_id=int(alternative_id),
            project_name=str(project_name),
        )

        safe_project_id = str(project_id).replace(" ", "_")
        filename = (
            f"alternative_{int(alternative_id):02d}_"
            f"{safe_project_id}_component_review.html"
        )

        figure.write_html(
            REVIEW_DIRECTORY / filename,
            include_plotlyjs=INCLUDE_PLOTLY_JS,
            full_html=True,
        )

        entries.append(
            (
                filename,
                f"Alternative {int(alternative_id)} - {project_name}",
                int(alternative_id),
                str(project_name),
            )
        )

    write_index(entries)

    print(f"Component input used: {component_file}")
    print(f"Created {len(entries)} Plotly review pages.")
    print(f"Open this file: {REVIEW_DIRECTORY / 'index.html'}")


if __name__ == "__main__":
    main()


