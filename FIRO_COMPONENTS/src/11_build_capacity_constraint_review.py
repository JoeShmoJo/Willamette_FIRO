"""
Prepare daily reservoir and control-point capacity/status tables.

These tables feed the retained utilization overview (14) and controller
view (13). This step no longer creates the superseded standalone capacity
plots. Numerical status and contribution calculations are unchanged.
This is an unrouted storage-space screen, not an operational release model.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# =============================================================================
# PATHS AND SETTINGS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "diagnostics"

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


# =============================================================================
# HTML INDEX
# =============================================================================


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

    print(f"Capacity/status tables created in: {REVIEW_DIRECTORY}")
    print("Build the overview with 14 and controller diagnostics with 13.")


if __name__ == "__main__":
    main()