from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_FILE = (
    PROJECT_ROOT
    / "src"
    / "09_build_no_routing_utilization_review.py"
)

BACKUP_FILE = (
    PROJECT_ROOT
    / "src"
    / "09_build_no_routing_utilization_review.pre_small_multiples.py"
)


NEW_FUNCTION = r'''
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
'''


def main() -> None:
    if not TARGET_FILE.exists():
        raise FileNotFoundError(
            f"Missing target script:\n{TARGET_FILE}"
        )

    text = TARGET_FILE.read_text(encoding="utf-8")

    start_marker = "def build_reservoir_figure("
    end_marker = "def build_control_point_figure("

    start = text.find(start_marker)
    end = text.find(end_marker, start)

    if start < 0 or end < 0 or end <= start:
        raise ValueError(
            "Could not locate the reservoir-figure function boundaries."
        )

    BACKUP_FILE.write_text(
        text,
        encoding="utf-8",
    )

    updated_text = (
        text[:start]
        + NEW_FUNCTION.strip()
        + "\n\n\n"
        + text[end:]
    )

    TARGET_FILE.write_text(
        updated_text,
        encoding="utf-8",
    )

    print()
    print("Reservoir small-multiple plot function installed.")
    print(f"Backup created: {BACKUP_FILE}")
    print(f"Updated script: {TARGET_FILE}")


if __name__ == "__main__":
    main()