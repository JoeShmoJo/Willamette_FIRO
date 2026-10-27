"""
03_cap_validate_and_plot_curves.py

Purpose
-------
Cap individual FIRO component curves at each physical project's allocated
FIRO storage space, recompute combined daily envelopes, validate the caps,
and create review plots.

This script preserves the original outputs:
    31_component_daily_curves.csv
    32_project_combined_daily_curves.csv
    33_alternative_daily_storage_summary.csv

It creates new capped outputs:
    35_component_daily_curves_capped.csv
    36_project_combined_daily_curves_capped.csv
    37_alternative_daily_storage_summary_capped.csv
    38_curve_cap_validation.csv
    39_curve_cap_quality_report.csv
    plots/

Dependencies
------------
    pip install pandas numpy matplotlib
"""

from pathlib import Path
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# =============================================================================
# PATHS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "diagnostics"
PLOT_DIRECTORY = OUTPUT_DIRECTORY / "plots"

COMPONENT_CURVES_FILE = (
    OUTPUT_DIRECTORY / "31_component_daily_curves.csv"
)

PHYSICAL_ALLOCATIONS_FILE = (
    OUTPUT_DIRECTORY
    / "25_alternative_physical_project_allocations.csv"
)


# =============================================================================
# PLOT SETTINGS
# =============================================================================
#
# Start with a manageable set of representative alternatives.
#
# To plot all alternatives, use:
#     PLOT_ALTERNATIVES = None
#

PLOT_ALTERNATIVES = {
    1,  # Optimize Cat 1 Spill
    3,  # Max Con Storage
    6,  # Flow Delivery + Storage Reliability
}

if os.environ.get('FIRO_EXTRA_DIAGNOSTICS') != '1':
    PLOT_ALTERNATIVES = set()

# To plot only named projects, use a set such as:
#
# PLOT_PROJECTS = {
#     "DETROIT",
#     "GREEN_PETER",
#     "FOSTER",
#     "HILLS_CREEK",
#     "LOOKOUT_POINT",
# }
#
# None means plot every active project in selected alternatives.
PLOT_PROJECTS = None

COMPONENT_COLORS = {
    "A": "#d62728",  # red
    "C": "#1f77b4",  # blue
    "E": "#7f7f7f",  # gray
    "H": "#2ca02c",  # green
    "I": "#9467bd",  # purple
    "J": "#e377c2",  # pink
    "K": "#ff7f0e",  # orange
}

TOLERANCE_KAF = 0.000001


# =============================================================================
# HELPERS
# =============================================================================

def require_file(path):
    """Raise a clear error for missing required input."""
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found:\n{path}"
        )


def write_csv(dataframe, filename):
    """Write UTF-8 CSV to outputs/diagnostics/."""
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = OUTPUT_DIRECTORY / filename

    dataframe.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    print(f"Created: {output_path}")


def add_issue(issues, severity, dataset, issue, details=""):
    """Add one quality-report row."""
    issues.append({
        "severity": severity,
        "dataset": dataset,
        "issue": issue,
        "details": details,
    })


def join_unique(values):
    """Join unique nonblank values."""
    result = []

    for value in values:
        if pd.isna(value):
            continue

        text = str(value).strip()

        if text and text not in result:
            result.append(text)

    return "|".join(sorted(result))


def should_plot(alternative_id, project_id):
    """Apply plot filters."""
    if (
        PLOT_ALTERNATIVES is not None
        and int(alternative_id)
        not in PLOT_ALTERNATIVES
    ):
        return False

    if (
        PLOT_PROJECTS is not None
        and project_id not in PLOT_PROJECTS
    ):
        return False

    return True


def safe_filename(text):
    """Create a safe file-name segment."""
    return (
        str(text)
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


# =============================================================================
# PLOTTING
# =============================================================================

def plot_project_curves(
    alternative_id,
    alternative_name,
    project_id,
    project_name,
    curve_table,
    allocated_space_kaf,
):
    """
    Create a storage-space plot for one project/alternative combination.
    """
    PLOT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    figure, axis = plt.subplots(
        figsize=(14, 7)
    )

    rule_storage = curve_table["rule_storage_kaf"]
    combined_storage = curve_table[
        "combined_storage_kaf"
    ]

    # Baseline rule curve.
    axis.plot(
        curve_table["date"],
        rule_storage,
        color="black",
        linewidth=2.8,
        label="Rule Curve",
        zorder=10,
    )

    # Individual capped component curves.
    component_columns = [
        column
        for column in curve_table.columns
        if column.startswith("component_")
        and column.endswith("_storage_kaf")
    ]

    for column in component_columns:
        component_code = (
            column
            .replace("component_", "")
            .replace("_storage_kaf", "")
        )

        values = curve_table[column]

        if values.notna().sum() == 0:
            continue

        axis.plot(
            curve_table["date"],
            values,
            color=COMPONENT_COLORS.get(
                component_code,
                None,
            ),
            linewidth=1.6,
            linestyle="--",
            alpha=0.85,
            label=f"{component_code} Component",
        )

    # Combined envelope.
    axis.plot(
        curve_table["date"],
        combined_storage,
        color="red",
        linewidth=2.8,
        label="Combined FIRO Envelope",
        zorder=20,
    )

    # Shade usable FIRO storage.
    axis.fill_between(
        curve_table["date"],
        rule_storage,
        combined_storage,
        where=(
            combined_storage
            >= rule_storage
        ),
        color="red",
        alpha=0.14,
        label="Combined FIRO Storage Space",
    )

    axis.set_title(
        f"Alternative {alternative_id}: {alternative_name}\n"
        f"{project_name} — Allocated FIRO Cap: "
        f"{allocated_space_kaf:.2f} KAF"
    )

    axis.set_xlabel("Date")
    axis.set_ylabel("Storage (KAF)")
    axis.grid(True, alpha=0.30)

    axis.xaxis.set_major_locator(
        mdates.MonthLocator()
    )

    axis.xaxis.set_major_formatter(
        mdates.DateFormatter("%b")
    )

    axis.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=3,
        frameon=True,
    )

    figure.tight_layout()

    filename = (
        f"alternative_{int(alternative_id):02d}_"
        f"{safe_filename(project_id)}_capped_curves.png"
    )

    output_path = PLOT_DIRECTORY / filename

    figure.savefig(
        output_path,
        dpi=180,
        bbox_inches="tight",
    )

    plt.close(figure)


# =============================================================================
# MAIN PROCESS
# =============================================================================

def main():
    for path in [
        COMPONENT_CURVES_FILE,
        PHYSICAL_ALLOCATIONS_FILE,
    ]:
        require_file(path)

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    PLOT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    issues = []

    print("Loading original component curves...")

    components = pd.read_csv(
        COMPONENT_CURVES_FILE,
        encoding="utf-8-sig",
        parse_dates=["date"],
    )

    allocations = pd.read_csv(
        PHYSICAL_ALLOCATIONS_FILE,
        encoding="utf-8-sig",
    )

    allocation_lookup = allocations[
        [
            "alternative_id",
            "project_id",
            "project_name",
            "decision_unit_id",
            "allocated_project_firo_space_kaf"
            if "allocated_project_firo_space_kaf"
            in allocations.columns
            else "project_firo_space_kaf",
        ]
    ].copy()

    allocation_column = (
        "allocated_project_firo_space_kaf"
        if "allocated_project_firo_space_kaf"
        in allocation_lookup.columns
        else "project_firo_space_kaf"
    )

    allocation_lookup = allocation_lookup.rename(
        columns={
            allocation_column: "allocated_project_firo_space_kaf"
        }
    )

    components = components.merge(
        allocation_lookup,
        on=[
            "alternative_id",
            "project_id",
            "project_name",
        ],
        how="left",
    )

    missing_allocations = components.loc[
        components[
            "allocated_project_firo_space_kaf"
        ].isna()
    ]

    if not missing_allocations.empty:
        for _, row in (
            missing_allocations[
                [
                    "alternative_id",
                    "project_id",
                ]
            ]
            .drop_duplicates()
            .iterrows()
        ):
            add_issue(
                issues,
                "ERROR",
                "component cap",
                "Component curve has no physical allocation",
                (
                    f"alternative={row['alternative_id']}; "
                    f"project={row['project_id']}"
                ),
            )

    components = components.dropna(
        subset=[
            "allocated_project_firo_space_kaf"
        ]
    ).copy()

    # -------------------------------------------------------------------------
    # Cap every active component curve.
    # -------------------------------------------------------------------------
    components[
        "allowed_storage_kaf"
    ] = (
        components["rule_storage_kaf"]
        + components[
            "allocated_project_firo_space_kaf"
        ]
    )

    components[
        "component_exceeded_allocation_before_cap"
    ] = (
        components["component_storage_kaf"]
        > (
            components["allowed_storage_kaf"]
            + TOLERANCE_KAF
        )
    )

    components[
        "capped_component_storage_kaf"
    ] = np.where(
        components["component_storage_kaf"].notna(),
        np.minimum(
            components["component_storage_kaf"],
            components["allowed_storage_kaf"],
        ),
        np.nan,
    )

    components[
        "capped_component_offset_kaf"
    ] = (
        components["capped_component_storage_kaf"]
        - components["rule_storage_kaf"]
    )

    components[
        "component_cap_reduction_kaf"
    ] = (
        components["component_storage_kaf"]
        - components["capped_component_storage_kaf"]
    )

    components[
        "component_cap_reduction_kaf"
    ] = components[
        "component_cap_reduction_kaf"
    ].clip(lower=0)

    # -------------------------------------------------------------------------
    # Rebuild project envelopes from capped component curves.
    # -------------------------------------------------------------------------
    combined_rows = []
    validation_rows = []
    alternative_summary_rows = []

    group_columns = [
        "alternative_id",
        "project_id",
        "project_name",
        "decision_unit_id",
    ]

    print("Capping components and rebuilding combined envelopes...")

    for group_key, group in components.groupby(
        group_columns
    ):
        (
            alternative_id,
            project_id,
            project_name,
            decision_unit_id,
        ) = group_key

        group = group.sort_values("date")

        allocation_kaf = float(
            group[
                "allocated_project_firo_space_kaf"
            ].iloc[0]
        )

        alternative_name = (
            group["alternative_id"]
            .map(
                dict(
                    zip(
                        allocations["alternative_id"],
                        allocations["alternative_name"],
                    )
                )
            )
            .iloc[0]
        )

        # One baseline rule curve value per date.
        daily_rule = (
            group
            .groupby("date", as_index=False)
            .agg(
                rule_elevation_ft=(
                    "rule_elevation_ft",
                    "first",
                ),
                rule_storage_kaf=(
                    "rule_storage_kaf",
                    "first",
                ),
            )
        )

        # Component curves in wide format.
        component_pivot = group.pivot_table(
            index="date",
            columns="component_code",
            values="capped_component_storage_kaf",
            aggfunc="first",
        )

        component_pivot = component_pivot.reindex(
            daily_rule["date"]
        )

        curve_table = daily_rule.set_index(
            "date"
        ).copy()

        for component_code in component_pivot.columns:
            curve_table[
                f"component_{component_code}_storage_kaf"
            ] = component_pivot[component_code]

        curve_columns = [
            column
            for column in curve_table.columns
            if column.startswith("component_")
            and column.endswith("_storage_kaf")
        ]

        combined_input = pd.DataFrame({
            "RULE_CURVE": curve_table[
                "rule_storage_kaf"
            ]
        })

        for column in curve_columns:
            combined_input[column] = curve_table[
                column
            ]

        curve_table["combined_storage_kaf"] = (
            combined_input.max(
                axis=1,
                skipna=True,
            )
        )

        curve_table["combined_offset_kaf"] = (
            curve_table["combined_storage_kaf"]
            - curve_table["rule_storage_kaf"]
        )

        # Identify controlling components.
        controlling = []

        for date_value, row in curve_table.iterrows():
            maximum = row["combined_storage_kaf"]

            names = []

            if abs(
                row["rule_storage_kaf"] - maximum
            ) <= TOLERANCE_KAF:
                names.append("RULE_CURVE")

            for column in curve_columns:
                value = row[column]

                if (
                    not pd.isna(value)
                    and abs(value - maximum)
                    <= TOLERANCE_KAF
                ):
                    names.append(
                        column
                        .replace("component_", "")
                        .replace("_storage_kaf", "")
                    )

            controlling.append(
                "|".join(sorted(set(names)))
            )

        curve_table["controlling_component"] = controlling

        # ---------------------------------------------------------------------
        # Cap validation.
        # ---------------------------------------------------------------------
        maximum_combined_offset = float(
            curve_table[
                "combined_offset_kaf"
            ].max()
        )

        cap_violation_after = (
            maximum_combined_offset
            > allocation_kaf + TOLERANCE_KAF
        )

        raw_component_violation_count = int(
            group[
                "component_exceeded_allocation_before_cap"
            ].sum()
        )

        maximum_cap_reduction = float(
            group[
                "component_cap_reduction_kaf"
            ]
            .fillna(0)
            .max()
        )

        if cap_violation_after:
            add_issue(
                issues,
                "ERROR",
                "combined curve cap validation",
                "Combined curve still exceeds allocated FIRO space after cap",
                (
                    f"alternative={alternative_id}; "
                    f"project={project_id}; "
                    f"max_offset={maximum_combined_offset:.6f}; "
                    f"allocation={allocation_kaf:.6f}"
                ),
            )

        if raw_component_violation_count > 0:
            add_issue(
                issues,
                "INFO",
                "component cap validation",
                "Raw component curve values were capped",
                (
                    f"alternative={alternative_id}; "
                    f"project={project_id}; "
                    f"capped_days={raw_component_violation_count}; "
                    f"max_reduction={maximum_cap_reduction:.6f} KAF"
                ),
            )

        validation_rows.append({
            "alternative_id": alternative_id,
            "alternative_name": alternative_name,
            "project_id": project_id,
            "project_name": project_name,
            "decision_unit_id": decision_unit_id,
            "allocated_project_firo_space_kaf": allocation_kaf,
            "maximum_combined_offset_kaf": (
                maximum_combined_offset
            ),
            "allocation_margin_kaf": (
                allocation_kaf
                - maximum_combined_offset
            ),
            "raw_component_cap_violation_day_count": (
                raw_component_violation_count
            ),
            "maximum_component_cap_reduction_kaf": (
                maximum_cap_reduction
            ),
            "combined_cap_violation_after_capping": (
                cap_violation_after
            ),
        })

        # ---------------------------------------------------------------------
        # Combined daily output rows.
        # ---------------------------------------------------------------------
        for date_value, row in curve_table.iterrows():
            combined_rows.append({
                "alternative_id": alternative_id,
                "alternative_name": alternative_name,
                "project_id": project_id,
                "project_name": project_name,
                "decision_unit_id": decision_unit_id,
                "date": date_value,
                "rule_elevation_ft": row[
                    "rule_elevation_ft"
                ],
                "rule_storage_kaf": row[
                    "rule_storage_kaf"
                ],
                "combined_storage_kaf": row[
                    "combined_storage_kaf"
                ],
                "combined_offset_kaf": row[
                    "combined_offset_kaf"
                ],
                "controlling_component": row[
                    "controlling_component"
                ],
                "allocated_project_firo_space_kaf": allocation_kaf,
            })

        # ---------------------------------------------------------------------
        # Plot selected alternatives/projects.
        # ---------------------------------------------------------------------
        plot_table = curve_table.reset_index().rename(
            columns={"index": "date"}
        )

        if should_plot(
            alternative_id,
            project_id,
        ):
            plot_project_curves(
                alternative_id=alternative_id,
                alternative_name=alternative_name,
                project_id=project_id,
                project_name=project_name,
                curve_table=plot_table,
                allocated_space_kaf=allocation_kaf,
            )

    # -------------------------------------------------------------------------
    # Alternative daily total storage-offset summary.
    # -------------------------------------------------------------------------
    combined_output = pd.DataFrame(combined_rows)

    if combined_output.empty:
        alternative_summary = pd.DataFrame()
    else:
        alternative_summary = (
            combined_output
            .groupby(
                [
                    "alternative_id",
                    "alternative_name",
                    "date",
                ],
                as_index=False,
            )
            .agg(
                total_project_offset_kaf=(
                    "combined_offset_kaf",
                    "sum",
                ),
                active_project_count=(
                    "project_id",
                    "nunique",
                ),
            )
        )

    # -------------------------------------------------------------------------
    # Write outputs.
    # -------------------------------------------------------------------------
    capped_component_output = components[
        [
            "alternative_id",
            "project_id",
            "project_name",
            "component_code",
            "date",
            "rule_elevation_ft",
            "rule_storage_kaf",
            "component_elevation_ft",
            "component_storage_kaf",
            "component_offset_kaf",
            "allocated_project_firo_space_kaf",
            "allowed_storage_kaf",
            "component_exceeded_allocation_before_cap",
            "capped_component_storage_kaf",
            "capped_component_offset_kaf",
            "component_cap_reduction_kaf",
        ]
    ].copy()

    validation_output = pd.DataFrame(
        validation_rows
    )

    quality_output = pd.DataFrame(
        issues,
        columns=[
            "severity",
            "dataset",
            "issue",
            "details",
        ],
    )

    write_csv(
        capped_component_output,
        "35_component_daily_curves_capped.csv",
    )

    write_csv(
        combined_output,
        "36_project_combined_daily_curves_capped.csv",
    )

    write_csv(
        alternative_summary,
        "37_alternative_daily_storage_summary_capped.csv",
    )

    write_csv(
        validation_output,
        "38_curve_cap_validation.csv",
    )

    write_csv(
        quality_output,
        "39_curve_cap_quality_report.csv",
    )

    print("")
    print("==============================================")
    print("CURVE CAP, VALIDATION, AND PLOTTING COMPLETE")
    print("==============================================")
    print(f"Plots created in: {PLOT_DIRECTORY}")
    print("")
    print("Review:")
    print("  outputs/diagnostics/38_curve_cap_validation.csv")
    print("  outputs/diagnostics/39_curve_cap_quality_report.csv")
    print("  outputs/diagnostics/36_project_combined_daily_curves_capped.csv")
    print("  outputs/diagnostics/plots/")


if __name__ == "__main__":
    main()