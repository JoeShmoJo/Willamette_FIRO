"""
02_build_component_curves.py

Build daily FIRO component curves and project combined envelopes for each
system alternative.

Inputs
------
data/
    01_projects_physical.csv
    03_rule_curves_long.csv
    ../shared/common_data/ElevStor.csv (normalized on load)
    12_alternative_component_selections.csv

outputs/diagnostics/
    25_alternative_physical_project_allocations.csv

Outputs
-------
outputs/diagnostics/
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
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "diagnostics"

PHYSICAL_PROJECTS_FILE = (
    DATA_DIRECTORY / "01_projects_physical.csv"
)

RULE_CURVES_FILE = (
    DATA_DIRECTORY / "03_rule_curves_long.csv"
)

STORAGE_ELEVATION_FILE = (
    PROJECT_ROOT.parent / "shared" / "common_data" / "ElevStor.csv"
)

COMPONENT_SELECTIONS_FILE = (
    DATA_DIRECTORY / "12_alternative_component_selections.csv"
)

# Trial curves use accepted production allocations as their input.
# Trial-generated curve outputs remain isolated in outputs.
PRODUCTION_OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "diagnostics"

PHYSICAL_ALLOCATIONS_FILE = (
    PROJECT_ROOT / "outputs" / "diagnostics"
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
    """Write an Excel-friendly UTF-8 CSV to outputs/diagnostics/."""
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

    # Use the same ResSim rating table as the other analysis workflows.
    ratings = pd.read_csv(STORAGE_ELEVATION_FILE).rename(
        columns={"Reservoir": "project_name", "Elev": "elevation_ft", "Stor": "storage_af"}
    )
    ratings["project_id"] = ratings["project_name"].map(canonical_id)
    ratings["storage_kaf"] = ratings["storage_af"] / 1000.0
    ratings = ratings[["project_id", "project_name", "elevation_ft", "storage_af", "storage_kaf"]]
    ratings = ratings.sort_values(["project_id", "elevation_ft"]).reset_index(drop=True)


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

    Geometry:
        receding rule-curve intersection
            -> flat winter pool
            -> rising rule-curve intersection
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

    drawdown_begins = mmdd_to_model_date(
        project["drawdown_begins_mmdd"]
    )

    drawdown_ends = mmdd_to_model_date(
        project["drawdown_ends_mmdd"]
    )

    start_refill = mmdd_to_model_date(
        project["start_refill_mmdd"]
    )

    hit_refill = mmdd_to_model_date(
        project["hit_refill_mmdd"]
    )

    # Find the target pool elevation on the receding rule-curve limb.
    start_date = find_crossing_date(
        rule_elev,
        target_elev,
        drawdown_begins,
        drawdown_ends,
        "falling",
    )

    # Find the target pool elevation on the rising rule-curve limb.
    reconnect_date = find_crossing_date(
        rule_elev,
        target_elev,
        start_refill,
        hit_refill,
        "rising",
    )

    start_status = "RULE_CURVE_INTERSECTION"
    end_status = "RULE_CURVE_INTERSECTION"

    # Conservative fallbacks if no daily crossing is found.
    if start_date is None:
        start_date = drawdown_ends
        start_status = "FALLBACK_DRAWDOWN_END"

    if reconnect_date is None:
        reconnect_date = hit_refill
        end_status = "FALLBACK_HIT_REFILL"

    curve = flat_curve(
        start_date,
        reconnect_date,
        target_storage,
    )

    # Start at the first daily falling-limb crossing. On the first
    # rising-limb day at or above the target pool, deactivate A and
    # allow the rule curve to resume without an artificial endpoint dip.
    curve.loc[reconnect_date] = np.nan

    parameters = {
        "parameter_1_name": "target_pool_elevation_ft",
        "parameter_1_value": target_elev,
        "parameter_2_name": "flat_pool_window",
        "parameter_2_value": (
            f"{start_date.strftime('%Y-%m-%d')} to "
            f"{reconnect_date.strftime('%Y-%m-%d')}"
        ),
        "geometry_assumption": (
            "Flat pool bounded by falling and rising rule-curve "
            f"intersections; start={start_status}; "
            f"end={end_status}."
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
    C: Straight refill guide curve.

    Geometry is linear in elevation:

        MinCon elevation at calculated C start date
            ->
        rule-curve elevation at RefillSlopeChange

    Each daily elevation is converted to storage through the rating curve.
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

    start_idx = date_index(calculated_start)
    end_idx = date_index(slope_change)

    curve = empty_curve()

    # Straight line in elevation, not in KAF storage.
    daily_elevations = np.linspace(
        min_con_elev,
        end_elev,
        end_idx - start_idx + 1,
    )

    daily_storages = np.array([
        elevation_to_storage_kaf(
            elevation,
            rating,
        )
        for elevation in daily_elevations
    ])

    curve.iloc[
        start_idx:end_idx + 1
    ] = daily_storages

    # Force exact daily rule-curve convergence at RefillSlopeChange.
    curve.loc[slope_change] = rule_storage.loc[
        slope_change
    ]

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
            "Straight line in elevation from MinCon to rule curve "
            f"at RefillSlopeChange; {status}."
        ),
    }

    return curve, parameters


def build_component_e(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """
    E: RefillSlopeChange to MaxCon.

    Geometry:
        RefillSlopeChange rule-curve point
        -> elevation-linear rise to MaxCon
        -> horizontal hold at MaxCon
        -> merge when the rule curve reaches MaxCon.

    The MaxCon-arrival date is variable. Each candidate arrival date is
    evaluated. The selected curve has the greatest feasible peak FIRO offset;
    KAF-days is used as a tie-breaker.

    A feasible E curve must:
        - remain on or above the rule curve;
        - remain at or below MaxCon;
        - not exceed the allocated FIRO-space cap.
    """
    max_con_elev = project["max_con_elev_ft"]

    max_con_storage = elevation_to_storage_kaf(
        max_con_elev,
        rating,
    )

    start_refill = nearest_model_date(
        mmdd_to_model_date(
            project["start_refill_mmdd"]
        )
    )

    inflection_date = mmdd_to_model_date(project["refill_slope_change_mmdd"])
    if inflection_date is None:
        inflection_date = mmdd_to_model_date("03-01")
    inflection_date = nearest_model_date(inflection_date)

    hit_refill = nearest_model_date(
        mmdd_to_model_date(
            project["hit_refill_mmdd"]
        )
    )

    # Use the actual rising-limb MaxCon crossing as the merge point.
    merge_date = find_crossing_date(
        rule_elev,
        max_con_elev,
        start_refill,
        hit_refill,
        "rising",
    )

    if merge_date is None:
        merge_date = hit_refill
    else:
        merge_date = nearest_model_date(merge_date)

    inflection_index = date_index(inflection_date)
    merge_index = date_index(merge_date)

    empty_curve = pd.Series(
        np.nan,
        index=DATES,
        dtype=float,
    )

    if merge_index <= inflection_index:
        parameters = {
            "parameter_1_name": "maxcon_arrival_date",
            "parameter_1_value": "",
            "parameter_2_name": "peak_offset_kaf",
            "parameter_2_value": 0.0,
            "geometry_assumption": (
                "NO_FEASIBLE_E_GEOMETRY: MaxCon merge date is not after "
                "RefillSlopeChange."
            ),
        }

        return empty_curve, parameters

    start_elev = rule_elev.loc[inflection_date]

    best_curve = None
    best_arrival_date = None
    best_peak_offset_kaf = -np.inf
    best_score_kaf_days = -np.inf

    # Test every day on which E could first reach MaxCon.
    for arrival_index in range(
        inflection_index + 1,
        merge_index + 1,
    ):
        arrival_date = DATES[arrival_index]

        candidate_curve = pd.Series(
            np.nan,
            index=DATES,
            dtype=float,
        )

        # Rising E leg is linear in elevation.
        rising_elevations = np.linspace(
            start_elev,
            max_con_elev,
            arrival_index - inflection_index + 1,
        )

        rising_storage = np.asarray(
            [
                elevation_to_storage_kaf(
                    elevation,
                    rating,
                )
                for elevation in rising_elevations
            ],
            dtype=float,
        )

        candidate_curve.iloc[
            inflection_index:arrival_index + 1
        ] = rising_storage

        # Hold at MaxCon until the ordinary rule curve reaches MaxCon.
        candidate_curve.iloc[
            arrival_index:merge_index + 1
        ] = max_con_storage

        candidate_segment = candidate_curve.iloc[
            inflection_index:merge_index + 1
        ]

        rule_segment = rule_storage.iloc[
            inflection_index:merge_index + 1
        ]

        offsets = (
            candidate_segment.to_numpy()
            - rule_segment.to_numpy()
        )

        # E cannot be below the rule curve.
        if np.any(offsets < -0.000001):
            continue

        peak_offset_kaf = float(np.nanmax(offsets))

        # E cannot exceed its assigned FIRO-space cap.
        if peak_offset_kaf > allocation_kaf + 0.000001:
            continue

        score_kaf_days = float(np.nansum(offsets))

        # Primary: largest feasible peak KAF.
        # Secondary: largest useful FIRO KAF-days.
        if (
            peak_offset_kaf > best_peak_offset_kaf + 0.000001
            or (
                abs(peak_offset_kaf - best_peak_offset_kaf)
                <= 0.000001
                and score_kaf_days > best_score_kaf_days
            )
        ):
            best_curve = candidate_curve
            best_arrival_date = arrival_date
            best_peak_offset_kaf = peak_offset_kaf
            best_score_kaf_days = score_kaf_days

    if best_curve is None or best_peak_offset_kaf <= 1e-8:
        # The uncapped straight leg can be infeasible on a curved rating/rule
        # combination. Retain the geometry where possible under the daily cap.
        best_arrival_date = DATES[inflection_index + 1]
        candidate = flat_curve(best_arrival_date, merge_date, max_con_storage)
        candidate.loc[inflection_date] = rule_storage.loc[inflection_date]
        active = candidate.notna()
        candidate.loc[active] = np.maximum(
            rule_storage.loc[active],
            np.minimum(candidate.loc[active], rule_storage.loc[active] + allocation_kaf),
        )
        return candidate, {
            "parameter_1_name": "maxcon_arrival_candidate",
            "parameter_1_value": best_arrival_date.strftime("%Y-%m-%d"),
            "parameter_2_name": "peak_offset_kaf",
            "parameter_2_value": float((candidate - rule_storage).max()),
            "geometry_assumption": "CAP_LIMITED_E: MaxCon upper target clipped to the daily allocation.",
        }

    parameters = {
        "parameter_1_name": "maxcon_arrival_date",
        "parameter_1_value": best_arrival_date.strftime("%Y-%m-%d"),
        "parameter_2_name": "peak_offset_kaf",
        "parameter_2_value": best_peak_offset_kaf,
        "geometry_assumption": (
            "Elevation-linear RefillSlopeChange-to-MaxCon rise; "
            "horizontal MaxCon hold to rule-curve MaxCon; arrival date "
            "selected for greatest feasible peak FIRO space."
        ),
    }

    return best_curve, parameters


def component_k_vertices(project, rule_elev, rule_storage, rating):
    """Return the existing K refill anchors and their storage elevations."""
    start_refill = nearest_model_date(
        mmdd_to_model_date(
            project["start_refill_mmdd"]
        )
    )

    hit_refill = nearest_model_date(
        mmdd_to_model_date(
            project["hit_refill_mmdd"]
        )
    )

    max_con_elev = project["max_con_elev_ft"]

    max_con_storage = elevation_to_storage_kaf(
        max_con_elev,
        rating,
    )

    merge_date = find_crossing_date(
        rule_elev,
        max_con_elev,
        start_refill,
        hit_refill,
        "rising",
    )

    if merge_date is None:
        merge_date = hit_refill
    else:
        merge_date = nearest_model_date(merge_date)

    min_con_storage = elevation_to_storage_kaf(project["min_con_elev_ft"], rating)
    start_index = date_index(start_refill)
    minimum_days = np.flatnonzero(
        np.isclose(rule_storage.iloc[:start_index + 1], min_con_storage, rtol=0, atol=1e-6)
    )
    if minimum_days.size:
        start_index = int(minimum_days[-1])
    merge_index = date_index(merge_date)

    return start_index, merge_index, min_con_storage, max_con_storage


def build_component_k(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """
    K: Constant horizontal time shift of the complete rising rule-curve limb.

    K is the refill analogue to J on the drawdown limb.

        K(date) = rising rule curve evaluated N days later

    The shift causes K to reach MaxCon early. K then remains horizontal at
    MaxCon until the ordinary rule curve reaches MaxCon.

    The selected value is the greatest feasible integer day shift that does
    not exceed the project allocation.
    """
    start_index, merge_index, min_con_storage, max_con_storage = component_k_vertices(
        project, rule_elev, rule_storage, rating
    )

    empty_curve = pd.Series(
        np.nan,
        index=DATES,
        dtype=float,
    )

    if merge_index <= start_index:
        parameters = {
            "parameter_1_name": "refill_shift_days",
            "parameter_1_value": 0,
            "parameter_2_name": "peak_offset_kaf",
            "parameter_2_value": 0.0,
            "geometry_assumption": (
                "NO_FEASIBLE_K_GEOMETRY: MaxCon merge date is not "
                "after StartRefill."
            ),
        }

        return empty_curve, parameters

    best_curve = None
    best_shift_days = 0
    best_peak_offset_kaf = 0.0

    # Test every possible positive integer day shift on the rising limb.
    for shift_days in range(
        1,
        merge_index - start_index + 1,
    ):
        candidate_curve = pd.Series(
            np.nan,
            index=DATES,
            dtype=float,
        )

        first_index = start_index - shift_days
        if first_index < 0:
            continue
        # Shift the MinCon vertex along with the rising limb.
        source_indices = np.minimum(np.arange(first_index, merge_index + 1) + shift_days, merge_index)
        shifted_storage = rule_storage.iloc[source_indices].to_numpy(copy=True)
        shifted_storage[0] = min_con_storage
        shifted_storage[source_indices == merge_index] = max_con_storage
        candidate_curve.iloc[first_index:merge_index + 1] = shifted_storage
        candidate_segment = candidate_curve.iloc[first_index:merge_index + 1]
        rule_segment = rule_storage.iloc[first_index:merge_index + 1]

        offsets = (
            candidate_segment.to_numpy()
            - rule_segment.to_numpy()
        )

        if np.any(offsets < -0.000001):
            continue

        peak_offset_kaf = float(np.nanmax(offsets))

        if peak_offset_kaf > allocation_kaf + 0.000001:
            continue

        if peak_offset_kaf > best_peak_offset_kaf + 0.000001:
            best_curve = candidate_curve
            best_shift_days = shift_days
            best_peak_offset_kaf = peak_offset_kaf

    if best_curve is None:
        parameters = {
            "parameter_1_name": "refill_shift_days",
            "parameter_1_value": 0,
            "parameter_2_name": "peak_offset_kaf",
            "parameter_2_value": 0.0,
            "geometry_assumption": (
                "NO_FEASIBLE_K_GEOMETRY: No positive rising-limb "
                "time shift fit within the allocated FIRO-space cap."
            ),
        }

        return empty_curve, parameters

    early_maxcon_date = DATES[
        max(
            start_index - best_shift_days,
            merge_index - best_shift_days,
        )
    ]

    parameters = {
        "parameter_1_name": "refill_shift_days",
        "parameter_1_value": best_shift_days,
        "parameter_2_name": "early_maxcon_date",
        "parameter_2_value": early_maxcon_date.strftime("%Y-%m-%d"),
        "geometry_assumption": (
            "Rising rule curve shifted earlier by a constant number of "
            "days; horizontal MaxCon hold occurs naturally after the "
            "shifted curve reaches MaxCon."
        ),
    }

    return best_curve, parameters

def build_component_h(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """
    H: Variable MinCon start -> spillway crest -> HitRefill rule curve.
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
    max_con_elev = project["max_con_elev_ft"]
    drawdown_ends = date_index(mmdd_to_model_date(project["drawdown_ends_mmdd"]))
    refill_start = date_index(mmdd_to_model_date(project["start_refill_mmdd"]))
    hit_refill = date_index(mmdd_to_model_date(project["hit_refill_mmdd"]))
    elevations = rule_elev.to_numpy()
    storage = rule_storage.to_numpy()
    tolerance = 1e-6

    # Join the first MaxCon day of ordinary refill, even when the configured
    # HitRefill date falls a day later on the same plateau.
    maxima = np.flatnonzero(
        np.isclose(elevations[refill_start:hit_refill + 1], max_con_elev, rtol=0, atol=tolerance)
    )
    starts = np.flatnonzero(
        np.isclose(elevations[drawdown_ends:refill_start + 1], min_con_elev, rtol=0, atol=tolerance)
    ) + drawdown_ends
    rating_elevation = rating["elevation_ft"].to_numpy()
    rating_storage = rating["storage_kaf"].to_numpy()

    if maxima.size and starts.size and min_con_elev < spillway_crest < max_con_elev:
        merge = refill_start + int(maxima[0])
        crest_storage = np.interp(spillway_crest, rating_elevation, rating_storage)
        for crest in range(int(starts[0]) + 1, merge):
            crest_offset = crest_storage - storage[crest]
            if not -tolerance <= crest_offset <= allocation_kaf + tolerance:
                continue

            upper_elevation = np.linspace(spillway_crest, max_con_elev, merge - crest + 1)
            upper = np.interp(upper_elevation, rating_elevation, rating_storage)
            upper_offset = upper - storage[crest:merge + 1]
            if (upper_offset < -tolerance).any() or (upper_offset > allocation_kaf + tolerance).any():
                continue

            for start in starts[starts < crest]:
                lower_elevation = np.linspace(min_con_elev, spillway_crest, crest - start + 1)
                lower = np.interp(lower_elevation, rating_elevation, rating_storage)
                lower_offset = lower - storage[start:crest + 1]
                if (lower_offset < -tolerance).any() or (lower_offset > allocation_kaf + tolerance).any():
                    continue
                curve = empty_curve()
                curve.iloc[start:merge + 1] = np.r_[lower[:-1], upper]
                return curve, {
                    "parameter_1_name": "mincon_start_date",
                    "parameter_1_value": DATES[start].strftime("%Y-%m-%d"),
                    "parameter_2_name": "spillway_crest_date",
                    "parameter_2_value": DATES[crest].strftime("%Y-%m-%d"),
                    "geometry_assumption": (
                        "Earliest feasible spillway crest, then earliest feasible MinCon start; "
                        f"straight elevation legs; MaxCon merge={DATES[merge]:%Y-%m-%d}."
                    ),
                }

    return empty_curve(), {
        "parameter_1_name": "mincon_start_date",
        "parameter_1_value": "",
        "parameter_2_name": "spillway_crest_date",
        "parameter_2_value": "",
        "geometry_assumption": "NO_FEASIBLE_H_GEOMETRY: No two-leg refill fits the project storage limit.",
    }


def component_i_candidates(project, allocation_kaf, rule_elev, rule_storage, rating):
    """Yield feasible whole-day K advances with a straight April-to-MaxCon leg."""
    start, merge, _, _ = component_k_vertices(project, rule_elev, rule_storage, rating)
    april = date_index(mmdd_to_model_date("04-01"))
    if not start < april < merge:
        return

    baseline = rule_elev.to_numpy()
    storage = rule_storage.to_numpy()
    low = project["min_con_elev_ft"]
    high = project["max_con_elev_ft"]
    rating_elevations = rating["elevation_ft"].to_numpy()
    rating_storage = rating["storage_kaf"].to_numpy()
    tolerance = 1e-6
    for advance in range(1, min(start, merge - start) + 1):
        first = start - advance
        source = np.minimum(np.arange(first, april + 1) + advance, merge)
        lower = baseline[source].copy()
        lower[0] = low
        lower[source == merge] = high
        upper = np.linspace(lower[-1], high, merge - april + 1)
        elevations = np.r_[lower[:-1], upper]
        volumes = np.interp(elevations, rating_elevations, rating_storage)
        offset = volumes - storage[first:merge + 1]
        if (
            (elevations < baseline[first:merge + 1] - tolerance).any()
            or (elevations > high + tolerance).any()
            or (offset > allocation_kaf + tolerance).any()
        ):
            continue
        yield advance, first, elevations, volumes, lower[-1]


def build_component_i(project, allocation_kaf, rule_elev, rule_storage, rating):
    """Choose the feasible advance with the highest April 1 target."""
    choice = max(
        component_i_candidates(project, allocation_kaf, rule_elev, rule_storage, rating),
        key=lambda candidate: candidate[4],
        default=None,
    )
    curve = empty_curve()
    if choice is None:
        advance, april_target = 0, np.nan
        note = "NO_FEASIBLE_I_GEOMETRY: No positive K advance and April-to-MaxCon line fit the project limit."
    else:
        advance, first, _, volumes, april_target = choice
        curve.iloc[first:first + len(volumes)] = volumes
        note = "K-style refill advance to April 1, then a straight elevation leg to ordinary MaxCon refill."
    return curve, {
        "parameter_1_name": "refill_advance_days",
        "parameter_1_value": advance,
        "parameter_2_name": "april_1_target_elevation_ft",
        "parameter_2_value": april_target,
        "geometry_assumption": note,
    }

def build_component_j(
    project,
    allocation_kaf,
    rule_elev,
    rule_storage,
    rating,
):
    """
    J: Constant horizontal time offset from the rule curve.

    J is one continuous shifted rule curve:

        J(t) = RC(t - j_delay_days)

    It follows the delayed falling limb from DrawdownBegins to the
    shifted MinCon touchdown.
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

    hit_refill = mmdd_to_model_date(
        project["hit_refill_mmdd"]
    )

    # Find the first annual low-pool date after drawdown begins.
    rule_drawdown_refill = rule_elev.loc[
        drawdown_begins:hit_refill
    ]

    baseline_mincon_date = rule_drawdown_refill.idxmin()

    # Legacy-style nominal delay: days from drawdown start to the
    # FIRO-adjusted falling rule-curve crossing.
    crossing_date = find_crossing_date(
        rule_elev,
        target_elev,
        drawdown_begins,
        baseline_mincon_date,
        "falling",
    )

    if crossing_date is None:
        nominal_delay_days = 0
        crossing_status = "FALLBACK_ZERO_DELAY"
    else:
        nominal_delay_days = max(
            0,
            (crossing_date - drawdown_begins).days,
        )
        crossing_status = "RULE_CURVE_CROSSING"

    # Select the largest constant time shift that does not exceed the
    # allocated FIRO storage cap anywhere the shifted curve is above RC.
    effective_delay_days = 0
    max_offset_kaf = 0.0

    for candidate_delay in range(
        nominal_delay_days,
        -1,
        -1,
    ):
        candidate_touchdown = nearest_model_date(
            baseline_mincon_date + pd.Timedelta(days=candidate_delay)
        )

        shifted_elev = rule_elev.shift(candidate_delay)

        candidate_dates = DATES[
            date_index(drawdown_begins):
            date_index(candidate_touchdown) + 1
        ]

        candidate_elev = shifted_elev.loc[
            candidate_dates
        ].dropna()

        if candidate_elev.empty:
            continue

        candidate_storage = pd.Series(
            [
                elevation_to_storage_kaf(
                    elevation,
                    rating,
                )
                for elevation in candidate_elev
            ],
            index=candidate_elev.index,
        )

        candidate_offsets = (
            candidate_storage
            - rule_storage.loc[candidate_storage.index]
        )

        positive_max_offset = max(
            0.0,
            float(candidate_offsets.max()),
        )

        if positive_max_offset <= (
            allocation_kaf + 0.000001
        ):
            effective_delay_days = candidate_delay
            max_offset_kaf = positive_max_offset
            break

    touchdown = nearest_model_date(
        baseline_mincon_date + pd.Timedelta(days=effective_delay_days)
    )

    delayed_rule_elev = rule_elev.shift(
        effective_delay_days
    )

    curve = empty_curve()

    start_idx = date_index(drawdown_begins)
    end_idx = date_index(touchdown)

    for date_value in DATES[
        start_idx:end_idx + 1
    ]:
        delayed_elevation = delayed_rule_elev.loc[
            date_value
        ]

        if pd.isna(delayed_elevation):
            continue

        curve.loc[date_value] = elevation_to_storage_kaf(
            delayed_elevation,
            rating,
        )

    curve.loc[touchdown] = elevation_to_storage_kaf(project["min_con_elev_ft"], rating)

    parameters = {
        "parameter_1_name": "j_effective_delay_days",
        "parameter_1_value": effective_delay_days,
        "parameter_2_name": "mincon_touchdown_date",
        "parameter_2_value": (
            touchdown.strftime("%Y-%m-%d")
        ),
        "geometry_assumption": (
            "Single continuous rule curve shifted horizontally; "
            f"nominal_delay={nominal_delay_days}; "
            f"effective_delay={effective_delay_days}; "
            f"max_positive_offset={max_offset_kaf:.3f} KAF; "
            f"crossing={crossing_status}."
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


    if component_code == "E":
        return build_component_e(
            project,
            allocation_kaf,
            rule_elev,
            rule_storage,
            rating,
        )

    if component_code == "K":
        return build_component_k(
            project,
            allocation_kaf,
            rule_elev,
            rule_storage,
            rating,
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
    print("  outputs/diagnostics/30_component_parameters.csv")
    print("  outputs/diagnostics/32_project_combined_daily_curves.csv")
    print("  outputs/diagnostics/33_alternative_daily_storage_summary.csv")
    print("  outputs/diagnostics/34_component_curve_quality_report.csv")


if __name__ == "__main__":
    main()





