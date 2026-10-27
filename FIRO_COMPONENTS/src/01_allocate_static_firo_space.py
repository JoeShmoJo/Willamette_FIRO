"""
01_allocate_static_firo_space.py

Purpose
-------
Create a first static FIRO-space allocation for every System Alternative.

Static allocation method
------------------------
For each alternative:

1. A physical reservoir participates if it has at least one active component:
       A, C, E, H, I, J, or K

2. F and G remain deferred and do not activate a reservoir.

3. Active physical reservoirs are converted to allocation decision units:
       - Hills Creek and Lookout Point -> LOP_HCR
       - All other projects remain individual decision units

4. Each active decision unit has:
       effective_conservation_storage_kaf
       effective_physical_cap_kaf

5. For each applicable control point:
       ControlPointShare(j,c)
       =
       SpaceLimit(c)
       *
       EffectiveConservationStorage(j)
       /
       Sum(EffectiveConservationStorage of active upstream units)

6. Each unit's downstream cap is the minimum share across every applicable
   downstream control point.

7. Final static FIRO allocation:
       min(effective_physical_cap_kaf, downstream_cap_kaf)

Important limitations
---------------------
- No redistribution of unused control-point capacity yet.
- No daily curve coincidence check yet.
- No reach routing execution yet.
- No F/G components.
- Big Cliff and Dexter remain pass-through network reservoirs with zero
  FIRO allocation.
- Green Peter and Foster remain separate decision units but both are
  constrained at Waterloo, Jefferson, Salem, and downstream locations.

Inputs
------
    data/01_projects_physical.csv
    data/02_decision_units.csv
    ../shared/control_points_space.csv
    data/12_alternative_component_selections.csv
    data/15_network_control_points_decision_units.csv

Outputs
-------
    outputs/diagnostics/20_direct_control_point_assignments.csv
    outputs/diagnostics/21_static_control_point_relationships.csv
    outputs/diagnostics/22_alternative_active_decision_units.csv
    outputs/diagnostics/23_alternative_control_point_shares.csv
    outputs/diagnostics/24_alternative_decision_unit_allocations.csv
    outputs/diagnostics/25_alternative_physical_project_allocations.csv
    outputs/diagnostics/26_alternative_control_point_utilization.csv
    outputs/diagnostics/27_static_allocation_quality_report.csv

Dependencies
------------
    pip install pandas
"""

from pathlib import Path
import re

import pandas as pd


# =============================================================================
# SETTINGS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOURCE_DIRECTORY = PROJECT_ROOT / "src"
DATA_DIRECTORY = PROJECT_ROOT / "data"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "diagnostics"

# Read canonical inputs directly from data/.
PHYSICAL_PROJECTS_FILE = (
    DATA_DIRECTORY / "01_projects_physical.csv"
)

DECISION_UNITS_FILE = (
    DATA_DIRECTORY / "02_decision_units.csv"
)

CONTROL_POINT_LIMITS_FILE = (
    PROJECT_ROOT.parent / "shared" / "control_points_space.csv"
)

ALTERNATIVE_SELECTIONS_FILE = (
    DATA_DIRECTORY / "12_alternative_component_selections.csv"
)

NETWORK_CONTROL_POINTS_FILE = (
    DATA_DIRECTORY / "15_network_control_points_decision_units.csv"
)

# F/G are intentionally excluded from the current model phase.
ACTIVE_COMPONENT_CODES = {
    "A",
    "C",
    "E",
    "H",
    "I",
    "J",
    "K",
}


# =============================================================================
# DIRECT TRIBUTARY CONTROL-POINT ASSIGNMENTS
# =============================================================================
#
# These assignments supplement the topology-derived matrix.
#
# Most are directly confirmed by network.json.
#
# DORENA and COTTAGE_GROVE are assigned to Goshen based on the legacy
# DSControlPoint allocations summing to the Goshen capacity:
#
#     Dorena DS space + Cottage Grove DS space = Goshen SpaceLimit
#
# This file is written as outputs/diagnostics/20_direct_control_point_assignments.csv
# so it can be reviewed or moved to a user-maintained config folder later.
#

DIRECT_CONTROL_POINT_ASSIGNMENTS = [
    {
        "decision_unit_id": "LOP_HCR",
        "control_point_id": "JASPER",
        "control_point_role": "direct_tributary",
        "verification_status": "TOPOLOGY_CONFIRMED",
        "notes": (
            "LOP_HCR passes through Dexter before reaching Jasper. "
            "Hills Creek and Lookout Point are one allocation system."
        ),
    },
    {
        "decision_unit_id": "FALL_CREEK",
        "control_point_id": "JASPER",
        "control_point_role": "direct_tributary",
        "verification_status": "TOPOLOGY_CONFIRMED",
        "notes": "",
    },
    {
        "decision_unit_id": "BLUE_RIVER",
        "control_point_id": "VIDA",
        "control_point_role": "direct_tributary",
        "verification_status": "TOPOLOGY_CONFIRMED",
        "notes": "",
    },
    {
        "decision_unit_id": "COUGAR",
        "control_point_id": "VIDA",
        "control_point_role": "direct_tributary",
        "verification_status": "TOPOLOGY_CONFIRMED",
        "notes": "",
    },
    {
        "decision_unit_id": "DORENA",
        "control_point_id": "GOSHEN",
        "control_point_role": "direct_tributary",
        "verification_status": "INFERRED_LEGACY_DS_SUM",
        "notes": (
            "Dorena and Cottage Grove legacy DS allocations sum "
            "to the Goshen control-point capacity."
        ),
    },
    {
        "decision_unit_id": "COTTAGE_GROVE",
        "control_point_id": "GOSHEN",
        "control_point_role": "direct_tributary",
        "verification_status": "INFERRED_LEGACY_DS_SUM",
        "notes": (
            "Dorena and Cottage Grove legacy DS allocations sum "
            "to the Goshen control-point capacity."
        ),
    },
    {
        "decision_unit_id": "FERN_RIDGE",
        "control_point_id": "MONROE",
        "control_point_role": "direct_tributary",
        "verification_status": "TOPOLOGY_CONFIRMED",
        "notes": "",
    },
    {
        "decision_unit_id": "GREEN_PETER",
        "control_point_id": "WATERLOO",
        "control_point_role": "direct_tributary",
        "verification_status": "TOPOLOGY_CONFIRMED",
        "notes": (
            "Green Peter water passes through Foster before Waterloo."
        ),
    },
    {
        "decision_unit_id": "FOSTER",
        "control_point_id": "WATERLOO",
        "control_point_role": "direct_tributary",
        "verification_status": "TOPOLOGY_CONFIRMED",
        "notes": "",
    },
    {
        "decision_unit_id": "DETROIT",
        "control_point_id": "MEHAMA",
        "control_point_role": "direct_tributary",
        "verification_status": "TOPOLOGY_CONFIRMED",
        "notes": (
            "Detroit water passes through Big Cliff before Mehama."
        ),
    },
]


# =============================================================================
# HELPERS
# =============================================================================

def require_file(path):
    """Raise a clear error when a required input is missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"Required input file not found:\n{path}"
        )


def write_csv(dataframe, filename):
    """Write derived model output without changing source data."""
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

def to_bool(value):
    """Convert common text Boolean values to Python Boolean."""
    return str(value).strip().upper() in {
        "TRUE",
        "T",
        "YES",
        "Y",
        "1",
    }


def join_unique(values):
    """Join unique nonblank values in sorted order."""
    cleaned = []

    for value in values:
        if pd.isna(value):
            continue

        text = str(value).strip()

        if text and text not in cleaned:
            cleaned.append(text)

    return "|".join(sorted(cleaned))


def add_issue(issues, severity, dataset, issue, details=""):
    """Append one quality-report issue."""
    issues.append({
        "severity": severity,
        "dataset": dataset,
        "issue": issue,
        "details": details,
    })


# =============================================================================
# LOAD INPUTS
# =============================================================================

def load_inputs():
    """Load all canonical model inputs."""
    physical_projects = pd.read_csv(
        PHYSICAL_PROJECTS_FILE,
        encoding="utf-8-sig",
    )

    decision_units = pd.read_csv(
        DECISION_UNITS_FILE,
        encoding="utf-8-sig",
    )

    control_points = pd.read_csv(
        CONTROL_POINT_LIMITS_FILE, encoding="utf-8-sig"
    ).rename(columns={"Location": "control_point_name", "SpaceLimit": "space_limit_kaf"})
    control_points["control_point_id"] = (
        control_points["control_point_name"].astype(str).str.upper()
        .str.replace(r"[^A-Z0-9]+", "_", regex=True).str.strip("_")
    )
    control_points = control_points.sort_values("control_point_id").reset_index(drop=True)


    component_selections = pd.read_csv(
        ALTERNATIVE_SELECTIONS_FILE,
        encoding="utf-8-sig",
    )

    network_control_points = pd.read_csv(
        NETWORK_CONTROL_POINTS_FILE,
        encoding="utf-8-sig",
    )

    return (
        physical_projects,
        decision_units,
        control_points,
        component_selections,
        network_control_points,
    )


# =============================================================================
# CONTROL-POINT RELATIONSHIPS
# =============================================================================

def build_control_point_relationships(
    network_control_points,
    control_points,
    issues,
):
    """
    Combine topology-derived network relationships with direct tributary
    control-point assignments.
    """
    cp_lookup = control_points[
        [
            "control_point_id",
            "control_point_name",
            "space_limit_kaf",
        ]
    ].copy()

    # Preserve unique topology rows only.
    topology = network_control_points[
        [
            "decision_unit_id",
            "control_point_id",
            "control_point_name",
            "space_limit_kaf",
            "member_project_ids",
            "member_project_names",
            "member_project_count",
            "first_control_point_path_order",
            "intervening_reservoirs",
            "routing_factor",
            "relationship_source",
            "verification_status",
        ]
    ].copy()

    topology["control_point_role"] = "downstream"

    topology = topology.drop_duplicates(
        subset=[
            "decision_unit_id",
            "control_point_id",
        ],
        keep="first",
    )

    direct = pd.DataFrame(
        DIRECT_CONTROL_POINT_ASSIGNMENTS
    )

    direct = direct.merge(
        cp_lookup,
        on="control_point_id",
        how="left",
    )

    for _, row in direct.loc[
        direct["control_point_name"].isna()
    ].iterrows():
        add_issue(
            issues,
            "ERROR",
            "direct control point assignments",
            "Direct assignment references unknown control point",
            (
                f"decision_unit={row['decision_unit_id']}; "
                f"control_point={row['control_point_id']}"
            ),
        )

    # Add missing fields to match topology table.
    direct["member_project_ids"] = ""
    direct["member_project_names"] = ""
    direct["member_project_count"] = pd.NA
    direct["first_control_point_path_order"] = pd.NA
    direct["intervening_reservoirs"] = ""
    direct["routing_factor"] = 1.0
    direct["relationship_source"] = (
        "direct_control_point_assignment"
    )

    # Remove any topology row that will be replaced by an explicit direct row.
    direct_keys = set(
        zip(
            direct["decision_unit_id"],
            direct["control_point_id"],
        )
    )

    keep_topology = topology.apply(
        lambda row: (
            row["decision_unit_id"],
            row["control_point_id"],
        )
        not in direct_keys,
        axis=1,
    )

    relationships = pd.concat(
        [
            topology.loc[keep_topology],
            direct[
                topology.columns.tolist()
            ],
        ],
        ignore_index=True,
    )

    # Restore member-project information from topology where available.
    member_info = (
        topology[
            [
                "decision_unit_id",
                "member_project_ids",
                "member_project_names",
                "member_project_count",
                "intervening_reservoirs",
            ]
        ]
        .drop_duplicates("decision_unit_id")
    )

    relationships = relationships.drop(
        columns=[
            "member_project_ids",
            "member_project_names",
            "member_project_count",
            "intervening_reservoirs",
        ]
    ).merge(
        member_info,
        on="decision_unit_id",
        how="left",
    )

    relationships = relationships[
        [
            "decision_unit_id",
            "control_point_id",
            "control_point_name",
            "space_limit_kaf",
            "control_point_role",
            "member_project_ids",
            "member_project_names",
            "member_project_count",
            "first_control_point_path_order",
            "intervening_reservoirs",
            "routing_factor",
            "relationship_source",
            "verification_status",
        ]
    ]

    relationships = relationships.sort_values(
        [
            "control_point_name",
            "decision_unit_id",
        ]
    ).reset_index(drop=True)

    return direct, relationships


# =============================================================================
# ACTIVE ALTERNATIVE MEMBERS
# =============================================================================

def build_active_decision_units(
    physical_projects,
    decision_units,
    component_selections,
    issues,
):
    """
    Convert physical project component selections to active allocation
    decision units for each alternative.

    LOP_HCR treatment:
        - If both Hills Creek and Lookout Point are active, use combined
          LOP_HCR physical cap.
        - If only one is active, use that member's individual physical cap.
        - Effective conservation-storage weight equals the sum of active
          physical member conservation storage.
    """
    selections = component_selections.copy()

    selections["project_id"] = (
        selections["project_id"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    selections["component_code"] = (
        selections["component_code"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    selections["active_for_current_phase"] = (
        selections["active_for_current_phase"]
        .apply(to_bool)
    )

    # Exclude F/G and any other nonactive component codes.
    selections = selections.loc[
        selections["active_for_current_phase"]
        & selections["component_code"].isin(
            ACTIVE_COMPONENT_CODES
        )
    ].copy()

    physical_lookup = physical_projects[
        [
            "project_id",
            "project_name",
            "allocation_unit_id",
            "conservation_storage_kaf",
            "physical_cap_kaf",
        ]
    ].copy()

    active_physical = (
        selections
        .groupby(
            [
                "alternative_id",
                "alternative_name",
                "project_id",
            ],
            as_index=False,
        )
        .agg(
            active_components=(
                "component_code",
                join_unique,
            )
        )
    )

    active_physical = active_physical.merge(
        physical_lookup,
        on="project_id",
        how="left",
    )

    # Flag alternatives that reference unknown physical projects.
    unknown_projects = active_physical.loc[
        active_physical["project_name"].isna()
    ]

    for _, row in unknown_projects.iterrows():
        add_issue(
            issues,
            "ERROR",
            "alternative component selections",
            "Selected project is not in physical project table",
            (
                f"alternative={row['alternative_id']}; "
                f"project={row['project_id']}"
            ),
        )

    active_physical = active_physical.dropna(
        subset=["project_name"]
    ).copy()

    decision_lookup = decision_units[
        [
            "decision_unit_id",
            "decision_unit_name",
            "decision_unit_type",
            "conservation_storage_kaf",
            "seven_day_evacuation_kaf",
            "physical_cap_kaf",
        ]
    ].copy()

    rows = []

    for (
        alternative_id,
        alternative_name,
        allocation_unit_id,
    ), group in active_physical.groupby(
        [
            "alternative_id",
            "alternative_name",
            "allocation_unit_id",
        ]
    ):
        decision = decision_lookup.loc[
            decision_lookup["decision_unit_id"]
            == allocation_unit_id
        ]

        if len(decision) != 1:
            add_issue(
                issues,
                "ERROR",
                "decision units",
                "Active allocation unit missing or duplicated",
                allocation_unit_id,
            )
            continue

        decision = decision.iloc[0]

        active_member_count = len(group)

        active_member_ids = join_unique(
            group["project_id"]
        )

        active_member_names = join_unique(
            group["project_name"]
        )

        active_components = join_unique(
            group["active_components"]
        )

        # Effective conservation-storage weight is always the total of
        # participating physical members.
        effective_conservation_storage = group[
            "conservation_storage_kaf"
        ].sum()

        # For lumped LOP_HCR:
        # - both active -> combined system cap
        # - one active -> the individual reservoir cap
        if (
            decision["decision_unit_type"]
            == "lumped_system"
            and active_member_count > 1
        ):
            effective_physical_cap = decision[
                "physical_cap_kaf"
            ]
            cap_method = "combined_system_cap"

        else:
            effective_physical_cap = group[
                "physical_cap_kaf"
            ].sum()
            cap_method = "active_member_physical_cap"

        rows.append({
            "alternative_id": alternative_id,
            "alternative_name": alternative_name,
            "decision_unit_id": allocation_unit_id,
            "decision_unit_name": decision[
                "decision_unit_name"
            ],
            "decision_unit_type": decision[
                "decision_unit_type"
            ],
            "active_member_ids": active_member_ids,
            "active_member_names": active_member_names,
            "active_member_count": active_member_count,
            "active_components": active_components,
            "effective_conservation_storage_kaf": (
                effective_conservation_storage
            ),
            "effective_physical_cap_kaf": (
                effective_physical_cap
            ),
            "physical_cap_method": cap_method,
        })

    active_units = pd.DataFrame(rows)

    return active_physical, active_units


# =============================================================================
# STATIC PROPORTIONAL ALLOCATION
# =============================================================================

def allocate_control_point_shares(
    active_units,
    relationships,
    issues,
):
    """
    Allocate each control-point capacity proportionally among active upstream
    decision units.

    This first version does not redistribute residual capacity after a unit
    is constrained by another control point or physical cap.
    """
    rows = []

    for (
        alternative_id,
        alternative_name,
    ), alternative_units in active_units.groupby(
        [
            "alternative_id",
            "alternative_name",
        ]
    ):
        merged = alternative_units.merge(
            relationships,
            on="decision_unit_id",
            how="inner",
        )

        if merged.empty:
            add_issue(
                issues,
                "WARNING",
                "static allocation",
                "Alternative has active units but no control-point relationships",
                f"alternative={alternative_id}",
            )
            continue

        for (
            control_point_id,
            control_point_name,
            space_limit_kaf,
        ), group in merged.groupby(
            [
                "control_point_id",
                "control_point_name",
                "space_limit_kaf",
            ]
        ):
            total_weight = group[
                "effective_conservation_storage_kaf"
            ].sum()

            if total_weight <= 0:
                add_issue(
                    issues,
                    "ERROR",
                    "static allocation",
                    "Control point has zero active conservation-storage weight",
                    (
                        f"alternative={alternative_id}; "
                        f"control_point={control_point_id}"
                    ),
                )
                continue

            for _, row in group.iterrows():
                proportional_share = (
                    space_limit_kaf
                    * row[
                        "effective_conservation_storage_kaf"
                    ]
                    / total_weight
                )

                rows.append({
                    "alternative_id": alternative_id,
                    "alternative_name": alternative_name,
                    "control_point_id": control_point_id,
                    "control_point_name": control_point_name,
                    "space_limit_kaf": space_limit_kaf,
                    "decision_unit_id": row[
                        "decision_unit_id"
                    ],
                    "decision_unit_name": row[
                        "decision_unit_name"
                    ],
                    "decision_unit_type": row[
                        "decision_unit_type"
                    ],
                    "active_member_ids": row[
                        "active_member_ids"
                    ],
                    "active_member_names": row[
                        "active_member_names"
                    ],
                    "effective_conservation_storage_kaf": row[
                        "effective_conservation_storage_kaf"
                    ],
                    "effective_physical_cap_kaf": row[
                        "effective_physical_cap_kaf"
                    ],
                    "control_point_role": row[
                        "control_point_role"
                    ],
                    "intervening_reservoirs": row[
                        "intervening_reservoirs"
                    ],
                    "proportional_share_kaf": proportional_share,
                    "allocation_weight_fraction": (
                        row[
                            "effective_conservation_storage_kaf"
                        ]
                        / total_weight
                    ),
                })

    shares = pd.DataFrame(rows)

    if shares.empty:
        return shares

    return shares.sort_values(
        [
            "alternative_id",
            "control_point_name",
            "decision_unit_id",
        ]
    ).reset_index(drop=True)


def calculate_decision_unit_allocations(
    active_units,
    shares,
    issues,
):
    """
    Calculate one static FIRO allocation per decision unit and alternative.
    """
    rows = []

    for _, active_row in active_units.iterrows():
        alternative_id = active_row["alternative_id"]
        decision_unit_id = active_row["decision_unit_id"]

        unit_shares = shares.loc[
            (shares["alternative_id"] == alternative_id)
            & (
                shares["decision_unit_id"]
                == decision_unit_id
            )
        ].copy()

        if unit_shares.empty:
            add_issue(
                issues,
                "WARNING",
                "static allocation",
                "Active decision unit has no applicable control-point share",
                (
                    f"alternative={alternative_id}; "
                    f"decision_unit={decision_unit_id}"
                ),
            )

            downstream_cap = pd.NA
            limiting_control_points = ""
            final_space = active_row[
                "effective_physical_cap_kaf"
            ]
            limiting_factor = "PHYSICAL_CAP_ONLY"

        else:
            downstream_cap = unit_shares[
                "proportional_share_kaf"
            ].min()

            limiting_control_points = join_unique(
                unit_shares.loc[
                    unit_shares[
                        "proportional_share_kaf"
                    ].sub(downstream_cap).abs()
                    < 0.000001,
                    "control_point_id",
                ]
            )

            physical_cap = active_row[
                "effective_physical_cap_kaf"
            ]

            if physical_cap < downstream_cap:
                final_space = physical_cap
                limiting_factor = "PHYSICAL_CAP"

            elif downstream_cap < physical_cap:
                final_space = downstream_cap
                limiting_factor = "DOWNSTREAM_CONTROL_POINT"

            else:
                final_space = physical_cap
                limiting_factor = "BOTH"

        rows.append({
            **active_row.to_dict(),
            "downstream_cap_kaf": downstream_cap,
            "limiting_control_points": limiting_control_points,
            "final_firo_space_kaf": final_space,
            "limiting_factor": limiting_factor,
        })

    allocations = pd.DataFrame(rows)

    return allocations.sort_values(
        [
            "alternative_id",
            "decision_unit_id",
        ]
    ).reset_index(drop=True)


def split_lumped_allocations_to_physical_projects(
    active_physical,
    decision_allocations,
):
    """
    Convert decision-unit allocation into physical-reservoir allocations.

    Standalone project:
        receives full decision-unit allocation.

    LOP_HCR:
        - if one member is active: it receives 100 percent;
        - if both members are active: split in proportion to active-member
          conservation storage.
    """
    rows = []

    for (
        alternative_id,
        alternative_name,
        allocation_unit_id,
    ), physical_group in active_physical.groupby(
        [
            "alternative_id",
            "alternative_name",
            "allocation_unit_id",
        ]
    ):
        allocation = decision_allocations.loc[
            (
                decision_allocations["alternative_id"]
                == alternative_id
            )
            & (
                decision_allocations["decision_unit_id"]
                == allocation_unit_id
            )
        ]

        if allocation.empty:
            continue

        allocation = allocation.iloc[0]

        total_active_storage = physical_group[
            "conservation_storage_kaf"
        ].sum()

        for _, project in physical_group.iterrows():
            if len(physical_group) == 1:
                project_fraction = 1.0
                split_method = "single_active_member"

            else:
                project_fraction = (
                    project["conservation_storage_kaf"]
                    / total_active_storage
                )
                split_method = (
                    "active_member_conservation_storage_proportional"
                )

            physical_allocation = (
                allocation["final_firo_space_kaf"]
                * project_fraction
            )

            rows.append({
                "alternative_id": alternative_id,
                "alternative_name": alternative_name,
                "project_id": project["project_id"],
                "project_name": project["project_name"],
                "decision_unit_id": allocation_unit_id,
                "active_components": project[
                    "active_components"
                ],
                "project_conservation_storage_kaf": project[
                    "conservation_storage_kaf"
                ],
                "project_physical_cap_kaf": project[
                    "physical_cap_kaf"
                ],
                "decision_unit_final_firo_space_kaf": allocation[
                    "final_firo_space_kaf"
                ],
                "decision_unit_limiting_factor": allocation[
                    "limiting_factor"
                ],
                "decision_unit_limiting_control_points": allocation[
                    "limiting_control_points"
                ],
                "project_split_fraction": project_fraction,
                "project_split_method": split_method,
                "project_firo_space_kaf": physical_allocation,
            })

    return pd.DataFrame(rows).sort_values(
        [
            "alternative_id",
            "project_id",
        ]
    ).reset_index(drop=True)


def calculate_control_point_utilization(
    shares,
    decision_allocations,
):
    """
    Calculate total assigned FIRO volume at each control point after each
    decision unit has been limited by its most restrictive constraint.
    """
    if shares.empty:
        return pd.DataFrame()

    allocation_lookup = decision_allocations[
        [
            "alternative_id",
            "decision_unit_id",
            "final_firo_space_kaf",
        ]
    ].copy()

    utilization = shares.merge(
        allocation_lookup,
        on=[
            "alternative_id",
            "decision_unit_id",
        ],
        how="left",
    )

    utilization = (
        utilization
        .groupby(
            [
                "alternative_id",
                "alternative_name",
                "control_point_id",
                "control_point_name",
                "space_limit_kaf",
            ],
            as_index=False,
        )
        .agg(
            allocated_firo_space_kaf=(
                "final_firo_space_kaf",
                "sum",
            ),
            active_decision_unit_count=(
                "decision_unit_id",
                "nunique",
            ),
            active_decision_units=(
                "decision_unit_id",
                join_unique,
            ),
        )
    )

    utilization["unused_control_point_space_kaf"] = (
        utilization["space_limit_kaf"]
        - utilization["allocated_firo_space_kaf"]
    )

    utilization["utilization_fraction"] = (
        utilization["allocated_firo_space_kaf"]
        / utilization["space_limit_kaf"]
    )

    return utilization.sort_values(
        [
            "alternative_id",
            "control_point_name",
        ]
    ).reset_index(drop=True)


# =============================================================================
# MAIN
# =============================================================================

def main():
    for path in [
        PHYSICAL_PROJECTS_FILE,
        DECISION_UNITS_FILE,
        CONTROL_POINT_LIMITS_FILE,
        ALTERNATIVE_SELECTIONS_FILE,
        NETWORK_CONTROL_POINTS_FILE,
    ]:
        require_file(path)

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    issues = []

    print("Loading canonical FIRO model inputs...")

    (
        physical_projects,
        decision_units,
        control_points,
        component_selections,
        network_control_points,
    ) = load_inputs()

    print("Building direct and downstream control-point relationships...")

    direct_assignments, relationships = (
        build_control_point_relationships(
            network_control_points,
            control_points,
            issues,
        )
    )

    print("Identifying active decision units for each alternative...")

    active_physical, active_units = build_active_decision_units(
        physical_projects,
        decision_units,
        component_selections,
        issues,
    )

    # Record alternatives with no active components.
    all_alternatives = sorted(
        component_selections["alternative_id"].unique()
    )

    active_alternatives = set(
        active_units["alternative_id"].unique()
    )

    for alternative_id in all_alternatives:
        if alternative_id not in active_alternatives:
            add_issue(
                issues,
                "INFO",
                "alternative activation",
                "Alternative has no active current-phase components",
                f"alternative={alternative_id}",
            )

    print("Calculating proportional control-point shares...")

    control_point_shares = allocate_control_point_shares(
        active_units,
        relationships,
        issues,
    )

    print("Calculating static decision-unit FIRO allocations...")

    decision_allocations = (
        calculate_decision_unit_allocations(
            active_units,
            control_point_shares,
            issues,
        )
    )

    physical_allocations = (
        split_lumped_allocations_to_physical_projects(
            active_physical,
            decision_allocations,
        )
    )

    control_point_utilization = (
        calculate_control_point_utilization(
            control_point_shares,
            decision_allocations,
        )
    )

    # -------------------------------------------------------------------------
    # Write outputs.
    # -------------------------------------------------------------------------
    write_csv(
        direct_assignments,
        "20_direct_control_point_assignments.csv",
    )

    write_csv(
        relationships,
        "21_static_control_point_relationships.csv",
    )

    write_csv(
        active_units,
        "22_alternative_active_decision_units.csv",
    )

    write_csv(
        control_point_shares,
        "23_alternative_control_point_shares.csv",
    )

    write_csv(
        decision_allocations,
        "24_alternative_decision_unit_allocations.csv",
    )

    write_csv(
        physical_allocations,
        "25_alternative_physical_project_allocations.csv",
    )

    write_csv(
        control_point_utilization,
        "26_alternative_control_point_utilization.csv",
    )

    quality_report = pd.DataFrame(
        issues,
        columns=[
            "severity",
            "dataset",
            "issue",
            "details",
        ],
    )

    write_csv(
        quality_report,
        "27_static_allocation_quality_report.csv",
    )

    # -------------------------------------------------------------------------
    # Summary.
    # -------------------------------------------------------------------------
    print("\n==============================================")
    print("STATIC FIRO ALLOCATION COMPLETE")
    print("==============================================")
    print(
        f"Active alternative/unit rows: {len(active_units)}"
    )
    print(
        f"Control-point share rows:     {len(control_point_shares)}"
    )
    print(
        f"Decision-unit allocations:    {len(decision_allocations)}"
    )
    print(
        f"Physical-project allocations: {len(physical_allocations)}"
    )
    print("")
    print("Review these files next:")
    print(
        "  outputs/diagnostics/24_alternative_decision_unit_allocations.csv"
    )
    print(
        "  outputs/diagnostics/25_alternative_physical_project_allocations.csv"
    )
    print(
        "  outputs/diagnostics/26_alternative_control_point_utilization.csv"
    )
    print(
        "  outputs/diagnostics/27_static_allocation_quality_report.csv"
    )


if __name__ == "__main__":
    main()