"""
Create a non-destructive E/K component-geometry trial builder.

Source:
    src/02_build_component_curves.py

Created trial builder:
    src/02_build_component_curves_ek_trial.py

The trial builder writes only to:
    outputs_ek_trial/

The production builder and outputs/ directory are not modified.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOURCE_SCRIPT = PROJECT_ROOT / "src" / "02_build_component_curves.py"
TRIAL_SCRIPT = (
    PROJECT_ROOT / "src" / "02_build_component_curves_ek_trial.py"
)

PRODUCTION_OUTPUT_DECLARATION = (
    'OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"'
)

TRIAL_OUTPUT_DECLARATION = (
    'OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs_ek_trial"'
)


NEW_E_AND_K_FUNCTIONS = r'''
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

    inflection_date = nearest_model_date(
        mmdd_to_model_date(
            project["refill_slope_change_mmdd"]
        )
    )

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

    if best_curve is None:
        parameters = {
            "parameter_1_name": "maxcon_arrival_date",
            "parameter_1_value": "",
            "parameter_2_name": "peak_offset_kaf",
            "parameter_2_value": 0.0,
            "geometry_assumption": (
                "NO_FEASIBLE_E_GEOMETRY: No elevation-linear "
                "RefillSlopeChange-to-MaxCon path remained above the "
                "rule curve while staying within the allocated FIRO cap."
            ),
        }

        return empty_curve, parameters

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

    start_index = date_index(start_refill)
    merge_index = date_index(merge_date)

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

        shifted_storage = []

        for current_index in range(
            start_index,
            merge_index + 1,
        ):
            source_index = min(
                current_index + shift_days,
                merge_index,
            )

            if source_index >= merge_index:
                shifted_storage.append(max_con_storage)
            else:
                shifted_storage.append(
                    elevation_to_storage_kaf(
                        rule_elev.iloc[source_index],
                        rating,
                    )
                )

        candidate_curve.iloc[
            start_index:merge_index + 1
        ] = shifted_storage

        candidate_segment = candidate_curve.iloc[
            start_index:merge_index + 1
        ]

        rule_segment = rule_storage.iloc[
            start_index:merge_index + 1
        ]

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
            start_index,
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
'''


NEW_DISPATCH = r'''
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
'''


def replace_section(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
) -> str:
    start = text.find(start_marker)

    if start < 0:
        raise ValueError(
            f"Could not find start marker:\n{start_marker}"
        )

    end = text.find(end_marker, start)

    if end < 0:
        raise ValueError(
            f"Could not find end marker:\n{end_marker}"
        )

    return (
        text[:start]
        + replacement.rstrip()
        + "\n\n"
        + text[end:]
    )


def main() -> None:
    if not SOURCE_SCRIPT.exists():
        raise FileNotFoundError(
            f"Missing production builder:\n  {SOURCE_SCRIPT}"
        )

    text = SOURCE_SCRIPT.read_text(
        encoding="utf-8",
    )

    if PRODUCTION_OUTPUT_DECLARATION not in text:
        raise ValueError(
            "Could not find the expected output-directory declaration:\n"
            f"  {PRODUCTION_OUTPUT_DECLARATION}\n\n"
            "No trial file was created."
        )

    text = text.replace(
        PRODUCTION_OUTPUT_DECLARATION,
        TRIAL_OUTPUT_DECLARATION,
        1,
    )

    # Replace the full shared E/K function, regardless of its internal body.
    text = replace_section(
        text=text,
        start_marker="def build_component_e_or_k(",
        end_marker="def find_earliest_valid_mincon_start(",
        replacement=NEW_E_AND_K_FUNCTIONS,
    )

    # Replace the complete E/K dispatcher block with separate E and K calls.
    text = replace_section(
        text=text,
        start_marker='    if component_code in {"E", "K"}:',
        end_marker='    if component_code == "H":',
        replacement=NEW_DISPATCH,
    )

    if "build_component_e_or_k(" in text:
        raise ValueError(
            "The shared E/K function call still exists after transformation. "
            "No trial file was created."
        )

    if "def build_component_e(" not in text:
        raise ValueError(
            "The E trial function was not inserted. "
            "No trial file was created."
        )

    if "def build_component_k(" not in text:
        raise ValueError(
            "The K trial function was not inserted. "
            "No trial file was created."
        )

    TRIAL_SCRIPT.write_text(
        text,
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("E/K TRIAL BUILDER CREATED")
    print("=" * 72)
    print(f"Production builder unchanged: {SOURCE_SCRIPT}")
    print(f"Trial builder created:        {TRIAL_SCRIPT}")
    print("Trial output directory:       outputs_ek_trial")
    print()
    print("Next command:")
    print(f"  python .\\src\\{TRIAL_SCRIPT.name}")


if __name__ == "__main__":
    main()