"""
Optimize static FIRO allocation redistribution.

Purpose
-------
Preserve the existing static allocation as the baseline, then create a second
allocation case that redistributes unused capacity left behind when one or more
decision units reach their physical FIRO caps.

Optimization logic, by alternative
----------------------------------
1. Keep every decision unit at least at its baseline allocation.
2. Do not exceed its physical FIRO cap.
3. Do not exceed any applicable downstream control-point space limit.
4. Maximize total feasible FIRO space.
5. Among equally feasible maximum-total solutions, distribute incremental
   FIRO space as proportionally as possible by effective conservation storage.

This script DOES NOT overwrite the current baseline allocation files:
    24_alternative_decision_unit_allocations.csv
    25_alternative_physical_project_allocations.csv
    26_alternative_control_point_utilization.csv

It creates explicitly named baseline and redistributed QA/QC outputs instead.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog, minimize


# =============================================================================
# PATHS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

BASELINE_DECISION_FILE = (
    OUTPUT_DIRECTORY / "24_alternative_decision_unit_allocations.csv"
)
BASELINE_PHYSICAL_FILE = (
    OUTPUT_DIRECTORY / "25_alternative_physical_project_allocations.csv"
)
STATIC_RELATIONSHIPS_FILE = (
    OUTPUT_DIRECTORY / "21_static_control_point_relationships.csv"
)

BASELINE_DECISION_OUTPUT = (
    OUTPUT_DIRECTORY / "40_baseline_decision_unit_allocations.csv"
)
REDISTRIBUTED_DECISION_OUTPUT = (
    OUTPUT_DIRECTORY / "41_redistributed_decision_unit_allocations.csv"
)
BASELINE_PHYSICAL_OUTPUT = (
    OUTPUT_DIRECTORY / "42_baseline_physical_project_allocations.csv"
)
REDISTRIBUTED_PHYSICAL_OUTPUT = (
    OUTPUT_DIRECTORY / "43_redistributed_physical_project_allocations.csv"
)
QAQC_OUTPUT = (
    OUTPUT_DIRECTORY / "44_allocation_qaqc_summary.csv"
)
BASELINE_CONTROL_POINT_OUTPUT = (
    OUTPUT_DIRECTORY / "45_control_point_utilization_baseline.csv"
)
REDISTRIBUTED_CONTROL_POINT_OUTPUT = (
    OUTPUT_DIRECTORY / "46_control_point_utilization_redistributed.csv"
)
OPTIMIZATION_SUMMARY_OUTPUT = (
    OUTPUT_DIRECTORY / "47_redistribution_optimization_summary.csv"
)

TOLERANCE_KAF = 1.0e-6


# =============================================================================
# VALIDATION
# =============================================================================

def require_columns(dataframe: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = columns - set(dataframe.columns)

    if missing:
        raise ValueError(
            f"{label} is missing required columns:\n"
            + "\n".join(f"  - {column}" for column in sorted(missing))
        )


def validate_input_files() -> None:
    required_files = [
        BASELINE_DECISION_FILE,
        BASELINE_PHYSICAL_FILE,
        STATIC_RELATIONSHIPS_FILE,
    ]

    missing_files = [path for path in required_files if not path.exists()]

    if missing_files:
        raise FileNotFoundError(
            "Missing required input files:\n"
            + "\n".join(f"  - {path}" for path in missing_files)
        )


# =============================================================================
# CONTROL-POINT UTILIZATION
# =============================================================================

def calculate_control_point_utilization(
    allocation_data: pd.DataFrame,
    relationships: pd.DataFrame,
    scenario: str,
) -> pd.DataFrame:
    """
    Calculate downstream-control-point utilization for one allocation scenario.
    """
    rows = []

    for alternative_id, alternative_data in allocation_data.groupby(
        "alternative_id",
        sort=True,
    ):
        alternative_name = alternative_data["alternative_name"].iloc[0]

        active_units = set(alternative_data["decision_unit_id"])

        relationship_data = relationships.loc[
            relationships["decision_unit_id"].isin(active_units)
        ].copy()

        for control_point_id, control_point_data in relationship_data.groupby(
            "control_point_id",
            sort=True,
        ):
            control_point_name = control_point_data[
                "control_point_name"
            ].iloc[0]

            space_limit_kaf = float(
                control_point_data["space_limit_kaf"].iloc[0]
            )

            applicable_units = sorted(
                control_point_data["decision_unit_id"].unique()
            )

            applicable_allocation = alternative_data.loc[
                alternative_data["decision_unit_id"].isin(applicable_units)
            ]

            allocated_space_kaf = float(
                applicable_allocation["scenario_firo_space_kaf"].sum()
            )

            unused_space_kaf = space_limit_kaf - allocated_space_kaf

            rows.append(
                {
                    "scenario": scenario,
                    "alternative_id": alternative_id,
                    "alternative_name": alternative_name,
                    "control_point_id": control_point_id,
                    "control_point_name": control_point_name,
                    "space_limit_kaf": space_limit_kaf,
                    "allocated_firo_space_kaf": allocated_space_kaf,
                    "unused_control_point_space_kaf": unused_space_kaf,
                    "utilization_fraction": (
                        allocated_space_kaf / space_limit_kaf
                        if space_limit_kaf > 0.0
                        else np.nan
                    ),
                    "active_decision_unit_count": len(applicable_units),
                    "active_decision_units": "|".join(applicable_units),
                }
            )

    return pd.DataFrame(rows)


# =============================================================================
# OPTIMIZATION
# =============================================================================

def solve_redistributed_allocation(
    alternative_data: pd.DataFrame,
    relationships: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """
    Optimize one alternative.

    Phase 1:
        Maximize total FIRO space subject to physical and downstream limits.

    Phase 2:
        Hold the Phase-1 total fixed, then choose the feasible allocation
        closest to conservation-storage-proportional incremental additions.
    """
    alternative_data = alternative_data.copy().reset_index(drop=True)

    alternative_id = int(alternative_data["alternative_id"].iloc[0])
    alternative_name = alternative_data["alternative_name"].iloc[0]

    unit_ids = alternative_data["decision_unit_id"].tolist()
    unit_count = len(unit_ids)

    baseline = alternative_data["final_firo_space_kaf"].to_numpy(dtype=float)
    physical_caps = alternative_data[
        "effective_physical_cap_kaf"
    ].to_numpy(dtype=float)

    conservation_storage = alternative_data[
        "effective_conservation_storage_kaf"
    ].to_numpy(dtype=float)

    if np.any(baseline - physical_caps > TOLERANCE_KAF):
        bad_units = alternative_data.loc[
            baseline - physical_caps > TOLERANCE_KAF,
            "decision_unit_id",
        ].tolist()

        raise ValueError(
            f"Alternative {alternative_id} has baseline allocation(s) "
            "above physical cap:\n"
            + "\n".join(f"  - {unit_id}" for unit_id in bad_units)
        )

    relationship_data = relationships.loc[
        relationships["decision_unit_id"].isin(unit_ids)
    ].copy()

    relationship_data = relationship_data.drop_duplicates(
        subset=["decision_unit_id", "control_point_id"]
    )

    control_point_ids = sorted(
        relationship_data["control_point_id"].unique()
    )

    unit_index = {
        unit_id: index
        for index, unit_id in enumerate(unit_ids)
    }

    control_point_rows = []
    control_point_limits = []
    control_point_names = []

    for control_point_id in control_point_ids:
        cp_data = relationship_data.loc[
            relationship_data["control_point_id"] == control_point_id
        ]

        row = np.zeros(unit_count, dtype=float)

        for decision_unit_id in cp_data["decision_unit_id"].unique():
            row[unit_index[decision_unit_id]] = 1.0

        control_point_rows.append(row)
        control_point_limits.append(
            float(cp_data["space_limit_kaf"].iloc[0])
        )
        control_point_names.append(
            str(cp_data["control_point_name"].iloc[0])
        )

    if control_point_rows:
        constraint_matrix = np.vstack(control_point_rows)
        constraint_limits = np.asarray(
            control_point_limits,
            dtype=float,
        )
    else:
        constraint_matrix = np.empty((0, unit_count), dtype=float)
        constraint_limits = np.empty(0, dtype=float)

    baseline_control_point_use = (
        constraint_matrix @ baseline
        if len(constraint_matrix) > 0
        else np.empty(0, dtype=float)
    )

    baseline_violation = (
        baseline_control_point_use - constraint_limits
        if len(constraint_matrix) > 0
        else np.empty(0, dtype=float)
    )

    if np.any(baseline_violation > TOLERANCE_KAF):
        problem_rows = np.where(
            baseline_violation > TOLERANCE_KAF
        )[0]

        problem_text = "\n".join(
            (
                f"  - {control_point_ids[index]} "
                f"({control_point_names[index]}): "
                f"baseline exceeds limit by "
                f"{baseline_violation[index]:.6f} KAF"
            )
            for index in problem_rows
        )

        raise ValueError(
            f"Alternative {alternative_id} baseline violates "
            f"control-point constraints:\n{problem_text}"
        )

    # -------------------------------------------------------------------------
    # Phase 1: maximize total system FIRO space.
    # linprog minimizes; use negative coefficients to maximize.
    # -------------------------------------------------------------------------

    phase_1 = linprog(
        c=-np.ones(unit_count, dtype=float),
        A_ub=constraint_matrix if len(constraint_matrix) else None,
        b_ub=(
            constraint_limits + TOLERANCE_KAF
            if len(constraint_matrix)
            else None
        ),
        bounds=list(zip(baseline, physical_caps)),
        method="highs",
    )

    if not phase_1.success:
        raise RuntimeError(
            f"Phase-1 optimization failed for Alternative {alternative_id}: "
            f"{phase_1.message}"
        )

    phase_1_solution = phase_1.x
    optimum_total_kaf = float(phase_1_solution.sum())

    # -------------------------------------------------------------------------
    # Phase 2: retain maximum total, then make added allocation as close as
    # possible to conservation-storage-proportional redistribution.
    # -------------------------------------------------------------------------

    baseline_total_kaf = float(baseline.sum())
    total_increment_kaf = max(
        0.0,
        optimum_total_kaf - baseline_total_kaf,
    )

    available_headroom = np.maximum(physical_caps - baseline, 0.0)

    weights = np.maximum(conservation_storage, 0.0)

    if weights.sum() <= TOLERANCE_KAF:
        weights = np.ones(unit_count, dtype=float)

    weights = weights / weights.sum()

    target_increment = total_increment_kaf * weights
    target_solution = baseline + target_increment

    # Scale by available headroom so a large project does not dominate solely
    # because it has a larger numerical storage value.
    fairness_scale = np.maximum(available_headroom, 1.0)

    def fairness_objective(values: np.ndarray) -> float:
        normalized_difference = (
            (values - target_solution) / fairness_scale
        )
        return float(np.sum(normalized_difference ** 2))

    constraints = [
        {
            "type": "eq",
            "fun": lambda values: values.sum() - optimum_total_kaf,
        }
    ]

    if len(constraint_matrix):
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda values: (
                    constraint_limits + TOLERANCE_KAF
                    - constraint_matrix @ values
                ),
            }
        )

    phase_2 = minimize(
        fun=fairness_objective,
        x0=phase_1_solution,
        method="SLSQP",
        bounds=list(zip(baseline, physical_caps)),
        constraints=constraints,
        options={
            "ftol": 1.0e-10,
            "maxiter": 2_000,
            "disp": False,
        },
    )

    if phase_2.success:
        optimized = phase_2.x
        phase_2_status = "SUCCESS"
        solver_status = (
            "Phase 1: HiGHS linear program; "
            "Phase 2: SLSQP proportional redistribution"
        )
    else:
        # Phase 1 remains a valid maximum-total solution. Retain it rather
        # than failing the entire alternative if only the fairness refinement
        # cannot converge.
        optimized = phase_1_solution
        phase_2_status = "FALLBACK_TO_PHASE_1"
        solver_status = (
            "Phase 1: HiGHS linear program; "
            "Phase 2: SLSQP did not converge; retained Phase-1 solution"
        )

    optimized = np.maximum(optimized, baseline)
    optimized = np.minimum(optimized, physical_caps)

    output = alternative_data.copy()

    output["baseline_firo_space_kaf"] = baseline
    output["redistributed_firo_space_kaf"] = optimized
    output["redistribution_increase_kaf"] = optimized - baseline
    output["unused_physical_capacity_kaf_after_redistribution"] = (
        physical_caps - optimized
    )

    output["optimization_status"] = phase_2_status
    output["optimization_solver"] = solver_status

    summary = {
        "alternative_id": alternative_id,
        "alternative_name": alternative_name,
        "decision_unit_count": unit_count,
        "control_point_count": len(control_point_ids),
        "baseline_total_firo_space_kaf": baseline_total_kaf,
        "redistributed_total_firo_space_kaf": float(optimized.sum()),
        "total_redistribution_increase_kaf": float(
            optimized.sum() - baseline_total_kaf
        ),
        "phase_1_status": phase_1.message,
        "phase_2_status": phase_2_status,
        "solver_status": solver_status,
    }

    return output, summary


# =============================================================================
# POST-OPTIMIZATION QA/QC
# =============================================================================

def add_limiting_control_points(
    allocation_data: pd.DataFrame,
    utilization_data: pd.DataFrame,
    relationships: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add control points that are effectively full after redistribution.
    """
    allocation_data = allocation_data.copy()

    full_control_points = utilization_data.loc[
        utilization_data["unused_control_point_space_kaf"]
        <= TOLERANCE_KAF
    ]

    lookup = {}

    for alternative_id, cp_data in full_control_points.groupby(
        "alternative_id"
    ):
        full_ids = set(cp_data["control_point_id"])

        related = relationships.loc[
            relationships["control_point_id"].isin(full_ids)
        ]

        for decision_unit_id, unit_data in related.groupby(
            "decision_unit_id"
        ):
            names = sorted(unit_data["control_point_name"].unique())

            lookup[(alternative_id, decision_unit_id)] = "|".join(names)

    allocation_data["redistributed_limiting_control_points"] = [
        lookup.get(
            (
                row.alternative_id,
                row.decision_unit_id,
            ),
            "",
        )
        for row in allocation_data.itertuples()
    ]

    return allocation_data


def build_redistributed_physical_allocations(
    baseline_physical: pd.DataFrame,
    redistributed_decision: pd.DataFrame,
) -> pd.DataFrame:
    """
    Apply the current decision-unit project split fractions to the optimized
    decision-unit allocation.
    """
    redistribution_columns = redistributed_decision[
        [
            "alternative_id",
            "decision_unit_id",
            "redistributed_firo_space_kaf",
            "redistribution_increase_kaf",
        ]
    ].copy()

    output = baseline_physical.merge(
        redistribution_columns,
        on=["alternative_id", "decision_unit_id"],
        how="left",
        validate="many_to_one",
    )

    output["baseline_project_firo_space_kaf"] = (
        output["project_firo_space_kaf"]
    )

    output["redistributed_project_firo_space_kaf"] = (
        output["redistributed_firo_space_kaf"]
        * output["project_split_fraction"]
    )

    output["project_redistribution_increase_kaf"] = (
        output["redistributed_project_firo_space_kaf"]
        - output["baseline_project_firo_space_kaf"]
    )

    output["project_physical_cap_exceeded"] = (
        output["redistributed_project_firo_space_kaf"]
        > output["project_physical_cap_kaf"] + TOLERANCE_KAF
    )

    return output


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    validate_input_files()

    baseline_decision = pd.read_csv(BASELINE_DECISION_FILE)
    baseline_physical = pd.read_csv(BASELINE_PHYSICAL_FILE)
    relationships = pd.read_csv(STATIC_RELATIONSHIPS_FILE)

    require_columns(
        baseline_decision,
        {
            "alternative_id",
            "alternative_name",
            "decision_unit_id",
            "effective_conservation_storage_kaf",
            "effective_physical_cap_kaf",
            "final_firo_space_kaf",
        },
        BASELINE_DECISION_FILE.name,
    )

    require_columns(
        baseline_physical,
        {
            "alternative_id",
            "decision_unit_id",
            "project_firo_space_kaf",
            "project_split_fraction",
            "project_physical_cap_kaf",
        },
        BASELINE_PHYSICAL_FILE.name,
    )

    require_columns(
        relationships,
        {
            "decision_unit_id",
            "control_point_id",
            "control_point_name",
            "space_limit_kaf",
        },
        STATIC_RELATIONSHIPS_FILE.name,
    )

    # Retain only one relationship per decision unit / control point.
    relationships = relationships.drop_duplicates(
        subset=["decision_unit_id", "control_point_id"]
    ).copy()

    # -------------------------------------------------------------------------
    # Explicit baseline outputs: no change to current model outputs.
    # -------------------------------------------------------------------------

    baseline_decision_output = baseline_decision.copy()
    baseline_decision_output["scenario"] = "BASELINE_NO_REDISTRIBUTION"
    baseline_decision_output["scenario_firo_space_kaf"] = (
        baseline_decision_output["final_firo_space_kaf"]
    )

    baseline_decision_output.to_csv(
        BASELINE_DECISION_OUTPUT,
        index=False,
    )

    baseline_physical_output = baseline_physical.copy()
    baseline_physical_output["scenario"] = "BASELINE_NO_REDISTRIBUTION"
    baseline_physical_output["baseline_project_firo_space_kaf"] = (
        baseline_physical_output["project_firo_space_kaf"]
    )

    baseline_physical_output.to_csv(
        BASELINE_PHYSICAL_OUTPUT,
        index=False,
    )

    # -------------------------------------------------------------------------
    # Optimize every alternative.
    # -------------------------------------------------------------------------

    redistributed_parts = []
    optimization_summaries = []

    for _, alternative_data in baseline_decision.groupby(
        "alternative_id",
        sort=True,
    ):
        redistributed_part, summary = solve_redistributed_allocation(
            alternative_data=alternative_data,
            relationships=relationships,
        )

        redistributed_parts.append(redistributed_part)
        optimization_summaries.append(summary)

    redistributed_decision = pd.concat(
        redistributed_parts,
        ignore_index=True,
    )

    redistributed_decision["scenario"] = "REDISTRIBUTED_OPTIMIZED"
    redistributed_decision["scenario_firo_space_kaf"] = (
        redistributed_decision["redistributed_firo_space_kaf"]
    )

    baseline_control_points = calculate_control_point_utilization(
        allocation_data=baseline_decision_output,
        relationships=relationships,
        scenario="BASELINE_NO_REDISTRIBUTION",
    )

    redistributed_control_points = calculate_control_point_utilization(
        allocation_data=redistributed_decision,
        relationships=relationships,
        scenario="REDISTRIBUTED_OPTIMIZED",
    )

    redistributed_decision = add_limiting_control_points(
        allocation_data=redistributed_decision,
        utilization_data=redistributed_control_points,
        relationships=relationships,
    )

    redistributed_physical = build_redistributed_physical_allocations(
        baseline_physical=baseline_physical,
        redistributed_decision=redistributed_decision,
    )

    # -------------------------------------------------------------------------
    # QA/QC comparison table.
    # -------------------------------------------------------------------------

    qaqc_columns = [
        "alternative_id",
        "alternative_name",
        "decision_unit_id",
        "decision_unit_name",
        "decision_unit_type",
        "active_components",
        "effective_conservation_storage_kaf",
        "effective_physical_cap_kaf",
        "downstream_cap_kaf",
        "limiting_control_points",
        "baseline_firo_space_kaf",
        "redistributed_firo_space_kaf",
        "redistribution_increase_kaf",
        "unused_physical_capacity_kaf_after_redistribution",
        "redistributed_limiting_control_points",
        "optimization_status",
        "optimization_solver",
    ]

    qaqc_columns = [
        column
        for column in qaqc_columns
        if column in redistributed_decision.columns
    ]

    qaqc = redistributed_decision[qaqc_columns].copy()

    qaqc["physical_cap_exceeded"] = (
        qaqc["redistributed_firo_space_kaf"]
        > qaqc["effective_physical_cap_kaf"] + TOLERANCE_KAF
    )

    # -------------------------------------------------------------------------
    # Write outputs.
    # -------------------------------------------------------------------------

    redistributed_decision.to_csv(
        REDISTRIBUTED_DECISION_OUTPUT,
        index=False,
    )

    redistributed_physical.to_csv(
        REDISTRIBUTED_PHYSICAL_OUTPUT,
        index=False,
    )

    qaqc.to_csv(
        QAQC_OUTPUT,
        index=False,
    )

    baseline_control_points.to_csv(
        BASELINE_CONTROL_POINT_OUTPUT,
        index=False,
    )

    redistributed_control_points.to_csv(
        REDISTRIBUTED_CONTROL_POINT_OUTPUT,
        index=False,
    )

    optimization_summary = pd.DataFrame(optimization_summaries)

    optimization_summary.to_csv(
        OPTIMIZATION_SUMMARY_OUTPUT,
        index=False,
    )

    # -------------------------------------------------------------------------
    # Console summary.
    # -------------------------------------------------------------------------

    baseline_total = baseline_decision[
        "final_firo_space_kaf"
    ].sum()

    redistributed_total = redistributed_decision[
        "redistributed_firo_space_kaf"
    ].sum()

    total_increase = redistributed_total - baseline_total

    changed_units = redistributed_decision.loc[
        redistributed_decision["redistribution_increase_kaf"]
        > TOLERANCE_KAF
    ]

    project_cap_issues = redistributed_physical.loc[
        redistributed_physical["project_physical_cap_exceeded"]
    ]

    print()
    print("=" * 78)
    print("FIRO STATIC REDISTRIBUTION OPTIMIZATION COMPLETE")
    print("=" * 78)
    print(f"Baseline total FIRO space:      {baseline_total:,.3f} KAF")
    print(f"Redistributed total FIRO space: {redistributed_total:,.3f} KAF")
    print(f"System increase:                {total_increase:,.3f} KAF")
    print(f"Decision units receiving space: {len(changed_units):,}")
    print()

    print("Created:")
    print(f"  {BASELINE_DECISION_OUTPUT.name}")
    print(f"  {REDISTRIBUTED_DECISION_OUTPUT.name}")
    print(f"  {BASELINE_PHYSICAL_OUTPUT.name}")
    print(f"  {REDISTRIBUTED_PHYSICAL_OUTPUT.name}")
    print(f"  {QAQC_OUTPUT.name}")
    print(f"  {BASELINE_CONTROL_POINT_OUTPUT.name}")
    print(f"  {REDISTRIBUTED_CONTROL_POINT_OUTPUT.name}")
    print(f"  {OPTIMIZATION_SUMMARY_OUTPUT.name}")
    print()

    if project_cap_issues.empty:
        print("QA/QC: No redistributed physical-project allocation exceeds cap.")
    else:
        print(
            "QA/QC WARNING: One or more redistributed physical-project "
            "allocations exceed cap. Review:"
        )
        print(
            project_cap_issues[
                [
                    "alternative_id",
                    "project_id",
                    "project_name",
                    "redistributed_project_firo_space_kaf",
                    "project_physical_cap_kaf",
                ]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()