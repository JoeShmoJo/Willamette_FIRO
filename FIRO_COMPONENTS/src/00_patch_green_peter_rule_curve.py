"""
00_patch_green_peter_rule_curve.py

Patch the canonical Green Peter rule curve in:

    data/03_rule_curves_long.csv

The original raw source file is not modified.

The Green Peter curve is replaced with the user-supplied recurring
rule-curve breakpoints, rounded to one decimal foot.
"""

from pathlib import Path
from datetime import datetime
import re

import numpy as np
import pandas as pd


# =============================================================================
# PATHS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIRECTORY = PROJECT_ROOT / "data"

RULE_CURVE_FILE = (
    DATA_DIRECTORY / "03_rule_curves_long.csv"
)

BACKUP_DIRECTORY = (
    DATA_DIRECTORY / "rule_curve_backups"
)

AUDIT_FILE = (
    DATA_DIRECTORY / "green_peter_rule_curve_patch_audit.csv"
)

ANCHOR_FILE = (
    DATA_DIRECTORY / "green_peter_rule_curve_patch_anchors.csv"
)


# =============================================================================
# USER-SUPPLIED GREEN PETER RULE-CURVE ANCHORS
# =============================================================================
#
# Values are rounded to one decimal foot in the canonical working file.
#
# The curve:
#   - remains at full pool through August;
#   - draws down to 922.0 by 30 November;
#   - remains at 922.0 through 01 February;
#   - refills to 1010.0 by 10 May;
#   - remains full afterward.
#

GREEN_PETER_ANCHORS = [
    ("08-01", 1010.001),
    ("08-31", 1010.001),

    ("09-07", 1006.008),
    ("09-15", 1000.535),
    ("09-22", 994.937),
    ("09-30", 989.145),

    ("10-07", 984.725),
    ("10-15", 978.648),
    ("10-23", 972.363),
    ("10-31", 964.796),

    ("11-07", 959.615),
    ("11-15", 952.707),
    ("11-22", 938.861),
    ("11-30", 922.010),

    ("12-07", 922.010),
    ("12-15", 922.010),
    ("12-23", 922.010),
    ("12-31", 922.010),

    ("01-01", 922.010),
    ("02-01", 922.010),

    ("02-07", 935.803),
    ("02-14", 948.303),
    ("02-21", 959.803),
    ("02-28", 970.403),

    ("03-07", 974.703),
    ("03-15", 979.403),
    ("03-23", 984.103),
    ("03-31", 988.703),

    ("04-07", 992.603),
    ("04-15", 996.903),
    ("04-22", 1000.703),
    ("04-30", 1004.903),

    ("05-07", 1008.503),
    ("05-10", 1010.001),

    ("07-31", 1010.001),
]


# =============================================================================
# HELPERS
# =============================================================================

def model_date(month_day):
    """
    Convert MM-DD to an August-through-July template year.

    Aug-Dec = 2000
    Jan-Jul = 2001
    """
    month, day = map(
        int,
        month_day.split("-"),
    )

    year = 2000 if month >= 8 else 2001

    return pd.Timestamp(
        year=year,
        month=month,
        day=day,
    )


def model_dates():
    """Create the recurring Aug-through-Jul daily curve."""
    return pd.date_range(
        "2000-08-01",
        "2001-07-31",
        freq="D",
    )


def canonical_month_day(value):
    """
    Extract MM-DD from source data such as:
        30Nov3000
        01Jan3001
    """
    match = re.search(
        r"(\d{1,2})([A-Za-z]{3})",
        str(value),
    )

    if not match:
        return ""

    day = int(match.group(1))
    month_text = match.group(2).title()

    month = pd.to_datetime(
        month_text,
        format="%b",
    ).month

    return f"{month:02d}-{day:02d}"


# =============================================================================
# BUILD DAILY PATCH CURVE
# =============================================================================

def build_daily_green_peter_curve():
    """Interpolate the supplied anchors to a daily recurring curve."""
    dates = model_dates()

    anchor_dates = [
        model_date(month_day)
        for month_day, _ in GREEN_PETER_ANCHORS
    ]

    anchor_values = np.array([
        elevation
        for _, elevation in GREEN_PETER_ANCHORS
    ])

    anchor_positions = np.array([
        int(dates.get_indexer([date])[0])
        for date in anchor_dates
    ])

    daily_values = np.interp(
        np.arange(len(dates)),
        anchor_positions,
        anchor_values,
    )

    daily_values = np.round(
        daily_values,
        1,
    )

    daily_curve = pd.DataFrame({
        "date": dates,
        "month_day": dates.strftime("%m-%d"),
        "patched_rule_elevation_ft": daily_values,
    })

    return daily_curve


# =============================================================================
# MAIN
# =============================================================================

def main():
    if not RULE_CURVE_FILE.exists():
        raise FileNotFoundError(
            f"Canonical rule curve file not found:\n{RULE_CURVE_FILE}"
        )

    BACKUP_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    source = pd.read_csv(
        RULE_CURVE_FILE,
        encoding="utf-8-sig",
    )

    required_columns = {
        "source_datetime",
        "project_id",
        "rule_elevation_ft",
    }

    missing_columns = required_columns - set(source.columns)

    if missing_columns:
        raise ValueError(
            "Rule curve file is missing required columns: "
            f"{sorted(missing_columns)}"
        )

    if "month_day" not in source.columns:
        source["month_day"] = source[
            "source_datetime"
        ].apply(canonical_month_day)

    green_peter_mask = (
        source["project_id"]
        .astype(str)
        .str.upper()
        == "GREEN_PETER"
    )

    if green_peter_mask.sum() == 0:
        raise ValueError(
            "No GREEN_PETER rows found in canonical rule curve file."
        )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup_file = (
        BACKUP_DIRECTORY
        / f"03_rule_curves_long_before_green_peter_patch_{timestamp}.csv"
    )

    source.to_csv(
        backup_file,
        index=False,
        encoding="utf-8-sig",
    )

    print(f"Backup created: {backup_file}")

    daily_patch = build_daily_green_peter_curve()

    patch_lookup = dict(
        zip(
            daily_patch["month_day"],
            daily_patch[
                "patched_rule_elevation_ft"
            ],
        )
    )

    original_values = source.loc[
        green_peter_mask,
        [
            "source_datetime",
            "month_day",
            "rule_elevation_ft",
        ],
    ].copy()

    original_values = original_values.rename(
        columns={
            "rule_elevation_ft": "original_rule_elevation_ft"
        }
    )

    source.loc[
        green_peter_mask,
        "rule_elevation_ft",
    ] = source.loc[
        green_peter_mask,
        "month_day",
    ].map(patch_lookup)

    if source.loc[
        green_peter_mask,
        "rule_elevation_ft",
    ].isna().any():
        raise ValueError(
            "Patch produced missing Green Peter rule-curve values."
        )

    patched_values = source.loc[
        green_peter_mask,
        [
            "source_datetime",
            "month_day",
            "rule_elevation_ft",
        ],
    ].copy()

    patched_values = patched_values.rename(
        columns={
            "rule_elevation_ft": "patched_rule_elevation_ft"
        }
    )

    audit = original_values.merge(
        patched_values,
        on=[
            "source_datetime",
            "month_day",
        ],
        how="outer",
    )

    audit["difference_ft"] = (
        audit["patched_rule_elevation_ft"]
        - audit["original_rule_elevation_ft"]
    )

    audit = audit.sort_values(
        "month_day"
    ).reset_index(drop=True)

    source.to_csv(
        RULE_CURVE_FILE,
        index=False,
        encoding="utf-8-sig",
    )

    daily_patch.to_csv(
        ANCHOR_FILE,
        index=False,
        encoding="utf-8-sig",
    )

    audit.to_csv(
        AUDIT_FILE,
        index=False,
        encoding="utf-8-sig",
    )

    print("")
    print("Green Peter canonical rule curve updated.")
    print(f"Updated: {RULE_CURVE_FILE}")
    print(f"Daily patch curve: {ANCHOR_FILE}")
    print(f"Audit file: {AUDIT_FILE}")
    print("")

    # Print critical user-specified verification dates.
    check_dates = [
        "08-31",
        "09-07",
        "11-30",
        "12-31",
        "01-01",
        "02-01",
        "02-07",
        "02-14",
        "02-28",
        "03-07",
        "03-15",
        "03-31",
        "04-15",
        "04-30",
        "05-07",
        "05-10",
    ]

    verification = daily_patch.loc[
        daily_patch["month_day"].isin(check_dates)
    ]

    print("Verification points:")
    print(
        verification.to_string(
            index=False
        )
    )


if __name__ == "__main__":
    main()