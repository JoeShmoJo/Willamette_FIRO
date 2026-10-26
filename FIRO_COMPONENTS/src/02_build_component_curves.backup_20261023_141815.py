"""
02_build_component_curves.py

Build daily FIRO component curves and project combined envelopes for each
system alternative.

Inputs
------
data/
    01_projects_physical.csv
    03_rule_curves_long.csv
    04_storage_elevation_long.csv
    12_alternative_component_selections.csv

outputs/
    25_alternative_physical_project_allocations.csv

Outputs
-------
outputs/
    30_component_parameters.csv
    31_component_daily_curves.csv
    32_project_combined_daily_curves.csv
    33_alternative_daily_storage_summary.csv
    34_component_curve_quality_report.csv

Current phase
-------------
Active components:
    A, C, E, H, I, J, K

Deferred components:
    F, G

Important:
    This script creates daily reservoir storage curves. It does not yet route
    daily releases through Lookout Point, Foster, Dexter, or Big Cliff, and
    it does not yet perform the final daily control-point constraint check.
"""

from pathlib import Path
import re

import numpy as np
import pandas as pd


# =============================================================================
# PATHS AND SETTINGS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIRECTORY = PROJECT_ROOT / "data"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

PHYSICAL_PROJECTS_FILE = (
    DATA_DIRECTORY / "01_projects_physical.csv"
)

RULE_CURVES_FILE = (
    DATA_DIRECTORY / "03_rule_curves_long.csv"
)

STORAGE_ELEVATION_FILE = (
    DATA_DIRECTORY / "04_storage_elevation_long.csv"
)

COMPONENT_SELECTIONS_FILE = (
    DATA_DIRECTORY / "12_alternative_component_selections.csv"
)

PHYSICAL_ALLOCATIONS_FILE = (
    OUTPUT_DIRECTORY
    / "25_alternative_physical_project_allocations.csv"
)

# Use the same template year embedded in project_data.csv.
MODEL_START = pd.Timestamp("2018-08-01")
MODEL_END = pd.Timestamp("2019-07-31")
DATES = pd.date_range(MODEL_START, MODEL_END, freq="D")

ACTIVE_COMPONENTS = {
    "A",
    "C",
    "E",
    "H",
    "I",
    "J",
    "K",
}

# K is provisionally implemented using the same general early-refill geometry
# as E. This remains visible in the parameter output.
K_GEOMETRY_STATUS = "PROVISIONAL_E_STYLE_GEOMETRY"


# =============================================================================
# BASIC HELPERS
# =============================================================================

def require_file(path):
    """Raise a clear error for missing inputs."""
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found:\n{path}"
        )


def write_csv(dataframe, filename):
    """Write an Excel-friendly UTF-8 CSV to outputs/."""
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


def to_bool(value):
    """Interpret Boolean-like CSV values."""
    return str(value).strip().upper() in {
        "TRUE",
        "T",
        "YES",
        "Y",
        "1",
    }


def canonical_id(value):
    """Create a stable uppercase identifier."""
    return re.sub(
        r"[^A-Z0-9]+",
        "_",
        str(value).upper(),
    ).strip("_")


def join_unique(values):
    """Join unique, nonblank text values."""
    result = []

    for value in values:
        if pd.isna(value):
            continue

        for item in str(value).split("|"):
            item = item.strip()

            if item and item not in result:
                result.append(item)

    return "|".join(sorted(result))


# =============================================================================
# DATE HELPERS
# =============================================================================

def mmdd_to_model_date(mmdd):
    """
    Convert MM-DD to a date in the August-through-July model year.
    """
    if pd.isna(mmdd) or str(mmdd).strip() == "":
        return None

    month, day = map(
        int,
        str(mmdd).strip().split("-"),
    )

    year = 2018 if month >= 8 else 2019

    return pd.Timestamp(year=year, month=month, day=day)


def nearest_model_date(date_value):
    """
    Return the nearest valid model date.
    """
    if date_value is None:
        return None

    if date_value < DATES[0]:
        return DATES[0]

    if date_value > DATES[-1]:
        return DATES[-1]

    position = DATES.get_indexer(
        [date_value],
        method="nearest",
    )[0]

    return DATES[position]


# =============================================================================
# INPUT LOADERS
# =============================================================================

def load_inputs():
    """Load all required data sources."""
    projects = pd.read_csv(
        PHYSICAL_PROJECTS_FILE,
        encoding="utf-8-sig",
    )

    rule_curves = pd.read_csv(
        RULE_CURVES_FILE,
        encoding="utf-8-sig",
    )

    ratings = pd.read_csv(
        STORAGE_ELEVATION_FILE,
        encoding="utf-8-sig",
    )

    selections = pd.read_csv(
        COMPONENT_SELECTIONS_FILE,
        encoding="utf-8-sig",
    )

    allocations = pd.read_csv(
        PHYSICAL_ALLOCATIONS_FILE,
        encoding="utf-8-sig",
    )

    return (
        projects,
        rule_curves,
        ratings,
        selections,
        allocations,
    )


def build_rule_curve_lookup(rule_curves, issues):
    """
    Build one daily elevation rule curve per project.
    """
    lookup = {}

    for project_id, group in rule_curves.groupby("project_id"):
        group = group.copy()

        group["date"] = group["month_day"].apply(
            mmdd_to_model_date
        )

        group = group.dropna(
            subset=[
                "date",
                "rule_elevation_ft",
            ]
        )

        # Drop February 29 if present in source recurring curve.
        group = group.loc[
            group["date"].isin(DATES)
        ]

        series = pd.Series(
            group["rule_elevation_ft"].to_numpy(),
            index=group["date"],
        )

        series = (
            series
            .groupby(level=0)
            .mean()
            .sort_index()
            .reindex(DATES)
            .interpolate()
            .ffill()
            .bfill()
        )

        if series.isna().any():
            add_issue(
                issues,
                "ERROR",
                "rule curves",
                "Rule curve contains unresolved missing values",
                project_id,
            )

        lookup[project_id] = series

    return lookup


def build_rating_lookup(ratings, issues):
    """
    Build elevation/storage interpolation tables by project.

    All calculation storage units are KAF.
    """
    lookup = {}

    for project_id, group in ratings.groupby("project_id"):
        rating = group[
            [
                "elevation_ft",
                "storage_kaf",
            ]
        ].copy()

        rating = rating.dropna().sort_values(
            "elevation_ft"
        )

        rating = rating.drop_duplicates(
            subset="elevation_ft",
            keep="last",
        )

        if len(rating) < 2:
            add_issue(
                issues,
                "ERROR",
                "storage elevation ratings",
                "Project has fewer than two usable rating points",
                project_id,
            )
            continue

        lookup[project_id] = rating

    return lookup


# =============================================================================
# STORAGE / ELEVATION CONVERSION
# =============================================================================

def elevation_to_storage_kaf(elevation_ft, rating):
    """Interpolate elevation to KAF."""
    elevations = rating["elevation_ft"].to_numpy(
        dtype=float
    )

    storages = rating["storage_kaf"].to_numpy(
        dtype=float
    )

    return float(
        np.interp(
            elevation_ft,
            elevations,
            storages,
        )
    )


def storage_kaf_to_elevation(storage_kaf, rating):
    """Interpolate KAF to elevation."""
    elevations = rating["elevation_ft"].to_numpy(
        dtype=float
    )

    storages = rating["storage_kaf"].to_numpy(
        dtype=float
    )

    # Prevent extrapolation outside the provided rating table.
    clipped_storage = min(
        max(storage_kaf, storages.min()),
        storages.max(),
    )

    return float(
        np.interp(
            clipped_storage,
            storages,
            elevations,
        )
    )


# =============================================================================
# CURVE CONSTRUCTION HELPERS
# =============================================================================

def empty_curve():
    """Return an inactive daily KAF curve."""
    return pd.Series(
        np.nan,
        index=DATES,
        dtype=float,
    )


def date_index(date_value):
    """Return daily index position for an in-model date."""
    return int(
        DATES.get_indexer(
            [nearest_model_date(date_value)]
        )[0]
    )


def piecewise_curve(points):
    """
    Build a daily line through ordered (date, storage_kaf) points.

    The curve is NaN before the first point and after the final point.
    """
    curve = empty_curve()

    cleaned = []

    for date_value, storage_kaf in points:
        if date_value is None:
            continue

        if pd.isna(storage_kaf):
            continue

        model_date = nearest_model_date(date_value)

        cleaned.append(
            (
                model_date,
                float(storage_kaf),
            )
        )

    if not cleaned:
        return curve

    # Sort and retain the final value where dates repeat.
    point_map = {}

    for date_value, storage_kaf in cleaned:
        point_map[date_value] = storage_kaf

    ordered = sorted(point_map.items())

    if len(ordered) == 1:
        curve.loc[ordered[0][0]] = ordered[0][1]
        return curve

    for (
        start_date,
        start_storage,
    ), (
        end_date,
        end_storage,
    ) in zip(
        ordered[:-1],
        ordered[1:],
    ):
        start_idx = date_index(start_date)
        end_idx = date_index(end_date)

        if end_idx < start_idx:
            continue

        curve.iloc[
            start_idx:end_idx + 1
        ] = np.linspace(
            start_storage,
            end_storage,
            end_idx - start_idx + 1,
        )

    return curve


def flat_curve(start_date, end_date, storage_kaf):
    """
    Build a flat active curve.
    """
    curve = empty_curve()

    if start_date is None or end_date is None:
        return curve

    start_idx = date_index(start_date)
    end_idx = date_index(end_date)

    if end_idx < start_idx:
        return curve

    curve.iloc[
        start_idx:end_idx + 1
    ] = storage_kaf

    return curve


def find_crossing_date(
    rule_curve,
    target_elevation,
    start_date,
    end_date,
    direction,
):
    """
    Find first daily rule-curve crossing within a date window.

    direction:
        "rising"
        "falling"

    Returns a daily model date or None.
    """
    if start_date is None or end_date is None:
        return None

    start_date = nearest_model_date(start_date)
    end_date = nearest_model_date(end_date)

    if end_date <= start_date:
        return None

    segment = rule_curve.loc[
        start_date:end_date
    ]

    values = segment.to_numpy(dtype=float)
    dates = segment.index

    for index in range(1, len(values)):
        previous = values[index - 1]
        current = values[index]

        if direction == "rising":
            crossed = (
                previous <= target_elevation
                <= current
                and current >= previous
            )

        elif direction == "falling":
            crossed = (
                previous >= target_elevation
                >= current
                and current <= previous
            )

        else:
            raise ValueError(
                "direction must be rising or falling"
            )

        if crossed:
            return dates[index]

    # If no formal crossing exists, use the closest date in the window.
    if len(segment) == 0:
        return None

    closest_index = int(
        np.argmin(
            np.abs(values - target_elevation)
        )
    )

    return dates[closest_index]


# =============================================================================
# COMPONENT BUILDERS
# =============================================================================

def build_component_a(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """
    A: Flat winter pool.

    Parameter:
        Vertical storage difference above MinCon.

    Geometry:
        Hold MinCon storage + allocation from DrawdownEnds until the rising
        rule curve reconnects with that target pool.
    """
    min_con_elev = project["min_con_elev_ft"]
    min_con_storage = elevation_to_storage_kaf(
        min_con_elev,
        rating,
    )

    target_storage = min_con_storage + allocation_kaf

    target_elev = storage_kaf_to_elevation(
        target_storage,
        rating,
    )

    start_date = mmdd_to_model_date(
        project["drawdown_ends_mmdd"]
    )

    refill_start = mmdd_to_model_date(
        project["start_refill_mmdd"]
    )

    hit_refill = mmdd_to_model_date(
        project["hit_refill_mmdd"]
    )

    reconnect_date = find_crossing_date(
        rule_elev,
        target_elev,
        refill_start,
        hit_refill,
        "rising",
    )

    curve = flat_curve(
        start_date,
        reconnect_date,
        target_storage,
    )

    # Force exact rule-curve convergence on final day.
    if reconnect_date is not None:
        curve.loc[reconnect_date] = rule_storage.loc[
            reconnect_date
        ]

    parameters = {
        "parameter_1_name": "target_pool_elevation_ft",
        "parameter_1_value": target_elev,
        "parameter_2_name": "reconnect_date",
        "parameter_2_value": (
            reconnect_date.strftime("%Y-%m-%d")
            if reconnect_date is not None
            else ""
        ),
        "geometry_assumption": (
            "Flat pool from DrawdownEnds to rising rule-curve reconnection."
        ),
    }

    return curve, parameters


def build_component_c(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """
    C: Straight refill line.

    Parameter:
        Calculated start date.

    Geometry:
        MinCon at calculated start date -> rule curve at fixed
        RefillSlopeChange date.
    """
    min_con_elev = project["min_con_elev_ft"]
    min_con_storage = elevation_to_storage_kaf(
        min_con_elev,
        rating,
    )

    target_storage = min_con_storage + allocation_kaf

    target_elev = storage_kaf_to_elevation(
        target_storage,
        rating,
    )

    start_refill = mmdd_to_model_date(
        project["start_refill_mmdd"]
    )

    slope_change = mmdd_to_model_date(
        project["refill_slope_change_mmdd"]
    )

    drawdown_end = mmdd_to_model_date(
        project["drawdown_ends_mmdd"]
    )

    end_elev = rule_elev.loc[slope_change]

    days_between = (
        slope_change - start_refill
    ).days

    if days_between <= 0 or end_elev <= target_elev:
        calculated_start = drawdown_end
        status = "FALLBACK_DRAWDOWN_END"

    else:
        slope_ft_per_day = (
            end_elev - target_elev
        ) / days_between

        days_to_min_con = (
            target_elev - min_con_elev
        ) / slope_ft_per_day

        calculated_start = (
            start_refill
            - pd.to_timedelta(
                days_to_min_con,
                unit="D",
            )
        )

        if calculated_start < drawdown_end:
            calculated_start = drawdown_end
            status = "CAPPED_AT_DRAWDOWN_END"
        else:
            status = "CALCULATED"

    calculated_start = nearest_model_date(
        calculated_start
    )

    curve = piecewise_curve([
        (
            calculated_start,
            min_con_storage,
        ),
        (
            slope_change,
            rule_storage.loc[slope_change],
        ),
    ])

    parameters = {
        "parameter_1_name": "calculated_start_date",
        "parameter_1_value": (
            calculated_start.strftime("%Y-%m-%d")
        ),
        "parameter_2_name": "rule_curve_slope_change_date",
        "parameter_2_value": (
            slope_change.strftime("%Y-%m-%d")
        ),
        "geometry_assumption": (
            "Straight line from MinCon to rule curve at RefillSlopeChange; "
            f"{status}."
        ),
    }

    return curve, parameters


def build_component_e_or_k(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
    component_code,
):
    """
    E/K: Early refill / maximum conservation transition.

    E parameter:
        FIRO-adjusted rule-curve crossing date based on MaxCon storage minus
        allocated FIRO space.

    K:
        Provisional implementation using the same E-style geometry.
    """
    max_con_elev = project["max_con_elev_ft"]
    max_con_storage = elevation_to_storage_kaf(
        max_con_elev,
        rating,
    )

    target_storage = max_con_storage - allocation_kaf

    target_elev = storage_kaf_to_elevation(
        target_storage,
        rating,
    )

    start_refill = mmdd_to_model_date(
        project["start_refill_mmdd"]
    )

    hit_refill = mmdd_to_model_date(
        project["hit_refill_mmdd"]
    )

    start_date = find_crossing_date(
        rule_elev,
        target_elev,
        start_refill,
        hit_refill,
        "rising",
    )

    # Provisional geometry:
    # Start at rule curve on target crossing date and rise linearly to MaxCon
    # at HitRefill, where it converges with the rule curve.
    curve = piecewise_curve([
        (
            start_date,
            rule_storage.loc[start_date],
        ),
        (
            hit_refill,
            rule_storage.loc[hit_refill],
        ),
    ])

    if component_code == "E":
        assumption = (
            "FIRO-adjusted MaxCon crossing date to HitRefill rule curve."
        )
    else:
        assumption = (
            "Provisional E-style early-refill geometry; "
            "replace when distinct K geometry is confirmed."
        )

    parameters = {
        "parameter_1_name": "firo_adjusted_maxcon_cross_date",
        "parameter_1_value": (
            start_date.strftime("%Y-%m-%d")
            if start_date is not None
            else ""
        ),
        "parameter_2_name": "target_elevation_ft",
        "parameter_2_value": target_elev,
        "geometry_assumption": assumption,
    }

    return curve, parameters


def build_component_h(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """
    H: Refill line to spillway crest, then rule curve at HitRefill.

    Parameters:
        StartRefill date
        FIRO-adjusted spillway-crest crossing date
    """
    spillway_crest = project["spillway_crest_elev_ft"]

    if pd.isna(spillway_crest):
        return None, {
            "parameter_1_name": "status",
            "parameter_1_value": "NOT_APPLICABLE",
            "parameter_2_name": "",
            "parameter_2_value": "",
            "geometry_assumption": (
                "No spillway crest defined for project."
            ),
        }

    min_con_elev = project["min_con_elev_ft"]

    min_con_storage = elevation_to_storage_kaf(
        min_con_elev,
        rating,
    )

    spillway_storage = elevation_to_storage_kaf(
        spillway_crest,
        rating,
    )

    target_storage = spillway_storage - allocation_kaf

    target_elev = storage_kaf_to_elevation(
        target_storage,
        rating,
    )

    start_refill = mmdd_to_model_date(
        project["start_refill_mmdd"]
    )

    hit_refill = mmdd_to_model_date(
        project["hit_refill_mmdd"]
    )

    crest_date = find_crossing_date(
        rule_elev,
        target_elev,
        start_refill,
        hit_refill,
        "rising",
    )

    if crest_date is None:
        crest_date = start_refill

    curve = piecewise_curve([
        (
            start_refill,
            min_con_storage,
        ),
        (
            crest_date,
            spillway_storage,
        ),
        (
            hit_refill,
            rule_storage.loc[hit_refill],
        ),
    ])

    parameters = {
        "parameter_1_name": "start_refill_date",
        "parameter_1_value": (
            start_refill.strftime("%Y-%m-%d")
        ),
        "parameter_2_name": "spillway_crest_date",
        "parameter_2_value": (
            crest_date.strftime("%Y-%m-%d")
        ),
        "geometry_assumption": (
            "StartRefill/MinCon -> spillway crest -> HitRefill/rule curve."
        ),
    }

    return curve, parameters


def build_component_i(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """
    I: 01 April inflection elevation.

    Geometry:
        StartRefill / MinCon
        -> 01 April target elevation
        -> HitRefill / rule curve.
    """
    min_con_elev = project["min_con_elev_ft"]
    max_con_elev = project["max_con_elev_ft"]

    min_con_storage = elevation_to_storage_kaf(
        min_con_elev,
        rating,
    )

    april_1 = pd.Timestamp("2019-04-01")

    april_rule_storage = rule_storage.loc[april_1]

    target_storage = april_rule_storage + allocation_kaf

    max_con_storage = elevation_to_storage_kaf(
        max_con_elev,
        rating,
    )

    target_storage = min(
        target_storage,
        max_con_storage,
    )

    target_elev = storage_kaf_to_elevation(
        target_storage,
        rating,
    )

    start_refill = mmdd_to_model_date(
        project["start_refill_mmdd"]
    )

    hit_refill = mmdd_to_model_date(
        project["hit_refill_mmdd"]
    )

    curve = piecewise_curve([
        (
            start_refill,
            min_con_storage,
        ),
        (
            april_1,
            target_storage,
        ),
        (
            hit_refill,
            rule_storage.loc[hit_refill],
        ),
    ])

    parameters = {
        "parameter_1_name": "april_1_target_elevation_ft",
        "parameter_1_value": target_elev,
        "parameter_2_name": "april_1_target_storage_kaf",
        "parameter_2_value": target_storage,
        "geometry_assumption": (
            "StartRefill/MinCon -> April 1 target -> HitRefill/rule curve."
        ),
    }

    return curve, parameters


def build_component_j(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """
    J: Drawdown flexibility guide curve.

    Parameter:
        Days from DrawdownBegins to the FIRO-adjusted MaxCon crossing.

    Geometry:
        DrawdownBegins / MaxCon
        -> FIRO-adjusted MaxCon crossing
        -> DrawdownEnds / rule curve.
    """
    max_con_elev = project["max_con_elev_ft"]

    max_con_storage = elevation_to_storage_kaf(
        max_con_elev,
        rating,
    )

    target_storage = max_con_storage - allocation_kaf

    target_elev = storage_kaf_to_elevation(
        target_storage,
        rating,
    )

    drawdown_begins = mmdd_to_model_date(
        project["drawdown_begins_mmdd"]
    )

    drawdown_ends = mmdd_to_model_date(
        project["drawdown_ends_mmdd"]
    )

    crossing_date = find_crossing_date(
        rule_elev,
        target_elev,
        drawdown_begins,
        drawdown_ends,
        "falling",
    )

    if crossing_date is None:
        crossing_date = drawdown_ends

    days_from_drawdown = (
        crossing_date - drawdown_begins
    ).days

    curve = piecewise_curve([
        (
            drawdown_begins,
            max_con_storage,
        ),
        (
            crossing_date,
            target_storage,
        ),
        (
            drawdown_ends,
            rule_storage.loc[drawdown_ends],
        ),
    ])

    parameters = {
        "parameter_1_name": "days_from_drawdown_begins",
        "parameter_1_value": days_from_drawdown,
        "parameter_2_name": "firo_adjusted_drawdown_cross_date",
        "parameter_2_value": (
            crossing_date.strftime("%Y-%m-%d")
        ),
        "geometry_assumption": (
            "DrawdownBegins/MaxCon -> FIRO-adjusted crossing "
            "-> DrawdownEnds/rule curve."
        ),
    }

    return curve, parameters


def build_component(
    component_code,
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """Dispatch to the correct component builder."""
    if component_code == "A":
        return build_component_a(
            project,
            allocation_kaf,
            rule_elev,
            rule_storage,
            rating,
        )

    if component_code == "C":
        return build_component_c(
            project,
            allocation_kaf,
            rule_elev,
            rule_storage,
            rating,
        )

    if component_code in {"E", "K"}:
        return build_component_e_or_k(
            project,
            allocation_kaf,
            rule_elev,
            rule_storage,
            rating,
            component_code,
        )

    if component_code == "H":
        return build_component_h(
            project,
            allocation_kaf,
            rule_elev,
            rule_storage,
            rating,
        )

    if component_code == "I":
        return build_component_i(
            project,
            allocation_kaf,
            rule_elev,
            rule_storage,
            rating,
        )

    if component_code == "J":
        return build_component_j(
            project,
            allocation_kaf,
            rule_elev,
            rule_storage,
            rating,
        )

    raise ValueError(
        f"Unsupported active component code: {component_code}"
    )


# =============================================================================
# MAIN CURVE PROCESS
# =============================================================================

def main():
    for path in [
        PHYSICAL_PROJECTS_FILE,
        RULE_CURVES_FILE,
        STORAGE_ELEVATION_FILE,
        COMPONENT_SELECTIONS_FILE,
        PHYSICAL_ALLOCATIONS_FILE,
    ]:
        require_file(path)

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    issues = []

    print("Loading FIRO curve inputs...")

    (
        projects,
        rule_curves,
        ratings,
        selections,
        allocations,
    ) = load_inputs()

    projects = projects.set_index("project_id")

    rule_lookup = build_rule_curve_lookup(
        rule_curves,
        issues,
    )

    rating_lookup = build_rating_lookup(
        ratings,
        issues,
    )

    selections["active_for_current_phase"] = (
        selections["active_for_current_phase"]
        .apply(to_bool)
    )

    selections["component_code"] = (
        selections["component_code"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    active_selections = selections.loc[
        selections["active_for_current_phase"]
        & selections["component_code"].isin(
            ACTIVE_COMPONENTS
        )
    ].copy()

    allocation_lookup = allocations[
        [
            "alternative_id",
            "project_id",
            "project_name",
            "decision_unit_id",
            "active_components",
            "project_firo_space_kaf",
        ]
    ].copy()

    component_parameter_rows = []
    component_daily_rows = []
    combined_daily_rows = []

    print("Building daily component curves...")

    for _, allocation_row in allocation_lookup.iterrows():
        alternative_id = allocation_row["alternative_id"]
        project_id = allocation_row["project_id"]
        project_name = allocation_row["project_name"]
        allocation_kaf = allocation_row[
            "project_firo_space_kaf"
        ]

        if project_id not in projects.index:
            add_issue(
                issues,
                "ERROR",
                "component curves",
                "Allocated project not in physical project table",
                project_id,
            )
            continue

        if project_id not in rule_lookup:
            add_issue(
                issues,
                "ERROR",
                "component curves",
                "Allocated project has no rule curve",
                project_id,
            )
            continue

        if project_id not in rating_lookup:
            add_issue(
                issues,
                "ERROR",
                "component curves",
                "Allocated project has no storage/elevation rating",
                project_id,
            )
            continue

        project = projects.loc[project_id]
        rule_elev = rule_lookup[project_id]
        rating = rating_lookup[project_id]

        rule_storage = pd.Series(
            [
                elevation_to_storage_kaf(
                    elevation,
                    rating,
                )
                for elevation in rule_elev
            ],
            index=DATES,
            dtype=float,
        )

        project_components = active_selections.loc[
            (
                active_selections["alternative_id"]
                == alternative_id
            )
            & (
                active_selections["project_id"]
                == project_id
            )
        ]

        if project_components.empty:
            continue

        component_curves = {}

        for component_code in project_components[
            "component_code"
        ].unique():
            try:
                component_curve, parameters = build_component(
                    component_code=component_code,
                    project=project,
                    allocation_kaf=allocation_kaf,
                    rule_elev=rule_elev,
                    rule_storage=rule_storage,
                    rating=rating,
                )

                if component_curve is None:
                    add_issue(
                        issues,
                        "INFO",
                        "component curves",
                        "Component not applicable to project",
                        (
                            f"alternative={alternative_id}; "
                            f"project={project_id}; "
                            f"component={component_code}"
                        ),
                    )
                    continue

                component_curves[component_code] = component_curve

                active_values = component_curve.dropna()

                if active_values.empty:
                    add_issue(
                        issues,
                        "WARNING",
                        "component curves",
                        "Component produced no active curve values",
                        (
                            f"alternative={alternative_id}; "
                            f"project={project_id}; "
                            f"component={component_code}"
                        ),
                    )

                component_parameter_rows.append({
                    "alternative_id": alternative_id,
                    "project_id": project_id,
                    "project_name": project_name,
                    "decision_unit_id": allocation_row[
                        "decision_unit_id"
                    ],
                    "component_code": component_code,
                    "allocated_firo_space_kaf": allocation_kaf,
                    "parameter_1_name": parameters[
                        "parameter_1_name"
                    ],
                    "parameter_1_value": parameters[
                        "parameter_1_value"
                    ],
                    "parameter_2_name": parameters[
                        "parameter_2_name"
                    ],
                    "parameter_2_value": parameters[
                        "parameter_2_value"
                    ],
                    "geometry_assumption": parameters[
                        "geometry_assumption"
                    ],
                })

                for date_value in DATES:
                    storage_kaf = component_curve.loc[
                        date_value
                    ]

                    if pd.isna(storage_kaf):
                        elevation_ft = np.nan
                    else:
                        elevation_ft = storage_kaf_to_elevation(
                            storage_kaf,
                            rating,
                        )

                    component_daily_rows.append({
                        "alternative_id": alternative_id,
                        "project_id": project_id,
                        "project_name": project_name,
                        "component_code": component_code,
                        "date": date_value,
                        "rule_elevation_ft": rule_elev.loc[
                            date_value
                        ],
                        "rule_storage_kaf": rule_storage.loc[
                            date_value
                        ],
                        "component_elevation_ft": elevation_ft,
                        "component_storage_kaf": storage_kaf,
                        "component_offset_kaf": (
                            storage_kaf
                            - rule_storage.loc[date_value]
                            if not pd.isna(storage_kaf)
                            else np.nan
                        ),
                    })

            except Exception as error:
                add_issue(
                    issues,
                    "ERROR",
                    "component curves",
                    "Component construction failed",
                    (
                        f"alternative={alternative_id}; "
                        f"project={project_id}; "
                        f"component={component_code}; "
                        f"error={error}"
                    ),
                )

        # ---------------------------------------------------------------------
        # Combined project envelope: highest active curve or baseline rule.
        # ---------------------------------------------------------------------
        combined_storage = rule_storage.copy()

        if component_curves:
            component_frame = pd.DataFrame(component_curves)

            combined_storage = pd.concat(
                [
                    rule_storage.rename("RULE_CURVE"),
                    component_frame,
                ],
                axis=1,
            ).max(
                axis=1,
                skipna=True,
            )

            controlling_components = []

            for date_value in DATES:
                combined_value = combined_storage.loc[
                    date_value
                ]

                controls = []

                for component_code, curve in component_curves.items():
                    value = curve.loc[date_value]

                    if (
                        not pd.isna(value)
                        and abs(value - combined_value) < 0.000001
                    ):
                        controls.append(component_code)

                if not controls:
                    controls = ["RULE_CURVE"]

                controlling_components.append(
                    "|".join(controls)
                )

        else:
            controlling_components = [
                "RULE_CURVE"
                for _ in DATES
            ]

        for date_value, controlling_component in zip(
            DATES,
            controlling_components,
        ):
            storage_kaf = combined_storage.loc[date_value]

            combined_daily_rows.append({
                "alternative_id": alternative_id,
                "project_id": project_id,
                "project_name": project_name,
                "decision_unit_id": allocation_row[
                    "decision_unit_id"
                ],
                "date": date_value,
                "rule_elevation_ft": rule_elev.loc[
                    date_value
                ],
                "rule_storage_kaf": rule_storage.loc[
                    date_value
                ],
                "combined_storage_kaf": storage_kaf,
                "combined_elevation_ft": storage_kaf_to_elevation(
                    storage_kaf,
                    rating,
                ),
                "combined_offset_kaf": (
                    storage_kaf
                    - rule_storage.loc[date_value]
                ),
                "controlling_component": controlling_component,
                "allocated_project_firo_space_kaf": allocation_kaf,
            })

    # -------------------------------------------------------------------------
    # Alternative daily storage summary.
    # -------------------------------------------------------------------------
    combined_daily = pd.DataFrame(
        combined_daily_rows
    )

    if combined_daily.empty:
        alternative_summary = pd.DataFrame()
    else:
        alternative_summary = (
            combined_daily
            .groupby(
                [
                    "alternative_id",
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
    parameter_output = pd.DataFrame(
        component_parameter_rows
    )

    component_daily_output = pd.DataFrame(
        component_daily_rows
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
        parameter_output,
        "30_component_parameters.csv",
    )

    write_csv(
        component_daily_output,
        "31_component_daily_curves.csv",
    )

    write_csv(
        combined_daily,
        "32_project_combined_daily_curves.csv",
    )

    write_csv(
        alternative_summary,
        "33_alternative_daily_storage_summary.csv",
    )

    write_csv(
        quality_output,
        "34_component_curve_quality_report.csv",
    )

    print("\n==============================================")
    print("FIRO COMPONENT CURVE BUILD COMPLETE")
    print("==============================================")
    print(
        f"Component parameter rows: {len(parameter_output)}"
    )
    print(
        f"Component daily rows:     {len(component_daily_output)}"
    )
    print(
        f"Combined daily rows:      {len(combined_daily)}"
    )
    print(
        f"Quality-report rows:      {len(quality_output)}"
    )
    print("")
    print("Review these files:")
    print("  outputs/30_component_parameters.csv")
    print("  outputs/32_project_combined_daily_curves.csv")
    print("  outputs/33_alternative_daily_storage_summary.csv")
    print("  outputs/34_component_curve_quality_report.csv")


if __name__ == "__main__":
    main()