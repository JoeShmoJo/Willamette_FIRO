"""
Add navigation controls to existing Plotly FIRO component-review pages.

Run this after:
    python FIRO_COMPONENTS/src/04_build_plotly_component_review.py

The script adds:
- Alternative selector
- Reservoir selector
- Link back to the Plotly review index
- Cleanup for malformed dash characters in generated HTML titles
"""

from __future__ import annotations

from html import escape
from pathlib import Path
import re

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "diagnostics"
REVIEW_DIRECTORY = OUTPUT_DIRECTORY / "plotly_component_review"

CAPPED_COMPONENT_FILE = OUTPUT_DIRECTORY / "35_component_daily_curves_capped.csv"
RAW_COMPONENT_FILE = OUTPUT_DIRECTORY / "31_component_daily_curves.csv"


def choose_component_file() -> Path:
    if CAPPED_COMPONENT_FILE.exists():
        return CAPPED_COMPONENT_FILE

    if RAW_COMPONENT_FILE.exists():
        return RAW_COMPONENT_FILE

    raise FileNotFoundError(
        "Could not find either capped or raw component daily curves."
    )


def make_filename(alternative_id: int, project_id: str) -> str:
    safe_project_id = str(project_id).replace(" ", "_")

    return (
        f"alternative_{int(alternative_id):02d}_"
        f"{safe_project_id}_component_review.html"
    )


def clean_mojibake(text: str) -> str:
    """
    Replace common UTF-8/Windows text-decoding artifacts with plain ASCII.
    """
    replacements = {
        "\u00e2\u20ac\u201d": "-",   # common bad em dash display
        "\u00e2\u20ac\u201c": "-",   # alternate malformed dash display
        "\u00c2\u00a0": " ",         # nonbreaking-space artifact
    }

    for bad_text, replacement in replacements.items():
        text = text.replace(bad_text, replacement)

    return text


def build_navigation_html(
    entries: list[dict],
    current_entry: dict,
) -> str:
    """
    Build page navigation for one alternative/project review page.
    """
    current_alternative = current_entry["alternative_id"]
    current_project_id = current_entry["project_id"]

    # For an alternative change: keep the same project if that project is
    # active in the target alternative; otherwise open the first project.
    alternative_options = []

    alternatives = sorted(
        {
            (
                entry["alternative_id"],
                entry["alternative_name"],
            )
            for entry in entries
        },
        key=lambda item: item[0],
    )

    for alternative_id, alternative_name in alternatives:
        alternative_entries = [
            entry
            for entry in entries
            if entry["alternative_id"] == alternative_id
        ]

        same_project = next(
            (
                entry
                for entry in alternative_entries
                if entry["project_id"] == current_project_id
            ),
            None,
        )

        target = same_project or alternative_entries[0]

        selected = (
            " selected"
            if alternative_id == current_alternative
            else ""
        )

        alternative_options.append(
            f'<option value="{escape(target["filename"])}"{selected}>'
            f'Alt {alternative_id}: '
            f'{escape(str(alternative_name))}'
            f"</option>"
        )

    # For a reservoir change: remain within the current alternative.
    reservoir_options = []

    current_alternative_entries = sorted(
        [
            entry
            for entry in entries
            if entry["alternative_id"] == current_alternative
        ],
        key=lambda entry: (
            entry["project_name"],
            entry["project_id"],
        ),
    )

    for entry in current_alternative_entries:
        selected = (
            " selected"
            if entry["project_id"] == current_project_id
            else ""
        )

        reservoir_options.append(
            f'<option value="{escape(entry["filename"])}"{selected}>'
            f'{escape(str(entry["project_name"]))}'
            f"</option>"
        )

    return f"""
<!-- FIRO_NAV_START -->
<style>
.firo-navigation {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: end;
    padding: 12px 16px;
    margin: 0 0 10px 0;
    background: #eef4fa;
    border-bottom: 1px solid #9eb6cf;
    font-family: Arial, sans-serif;
}}
.firo-navigation label {{
    display: block;
    margin-bottom: 4px;
    font-weight: 700;
    color: #173a5e;
    font-size: 13px;
}}
.firo-navigation select {{
    min-width: 250px;
    padding: 6px;
    font-size: 14px;
}}
.firo-navigation a {{
    display: inline-block;
    padding: 7px 10px;
    color: #ffffff;
    background: #245a8d;
    text-decoration: none;
    border-radius: 3px;
    font-size: 14px;
}}
.firo-navigation a:hover {{
    background: #173a5e;
}}
</style>

<div class="firo-navigation">
    <div>
        <label for="alternative-selector">Alternative</label>
        <select id="alternative-selector"
                onchange="window.location.href=this.value">
            {''.join(alternative_options)}
        </select>
    </div>

    <div>
        <label for="reservoir-selector">Reservoir</label>
        <select id="reservoir-selector"
                onchange="window.location.href=this.value">
            {''.join(reservoir_options)}
        </select>
    </div>

    <div>
        <a href="index.html">Review Index</a>
    </div>
</div>
<!-- FIRO_NAV_END -->
"""


def add_navigation_to_page(
    page_path: Path,
    navigation_html: str,
) -> None:
    """
    Remove a prior navigation block, clean text artifacts, and inject
    the current navigation block immediately after the opening body tag.
    """
    text = page_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    text = clean_mojibake(text)

    text = re.sub(
        r"<!-- FIRO_NAV_START -->.*?<!-- FIRO_NAV_END -->",
        "",
        text,
        flags=re.DOTALL,
    )

    body_match = re.search(r"<body[^>]*>", text, flags=re.IGNORECASE)

    if body_match is None:
        raise ValueError(
            f"Could not find HTML body tag in: {page_path.name}"
        )

    insertion_point = body_match.end()

    text = (
        text[:insertion_point]
        + navigation_html
        + text[insertion_point:]
    )

    page_path.write_text(
        text,
        encoding="utf-8",
    )


def main() -> None:
    if not REVIEW_DIRECTORY.exists():
        raise FileNotFoundError(
            "Plotly review directory does not exist. "
            "Run 04_build_plotly_component_review.py first."
        )

    component_file = choose_component_file()
    component_data = pd.read_csv(component_file)

    # Component-curve files identify alternatives by ID but do not always
    # include the alternative name. Add it from the baseline allocation file.
    if "alternative_name" not in component_data.columns:
        allocation_file = (
            OUTPUT_DIRECTORY
            / "24_alternative_decision_unit_allocations.csv"
        )

        if not allocation_file.exists():
            raise FileNotFoundError(
                "Cannot add alternative names because this file is missing:\n"
                f"  {allocation_file}"
            )

        alternative_names = pd.read_csv(
            allocation_file,
            usecols=["alternative_id", "alternative_name"],
        ).drop_duplicates()

        component_data = component_data.merge(
            alternative_names,
            on="alternative_id",
            how="left",
            validate="many_to_one",
        )

    required_columns = {
        "alternative_id",
        "alternative_name",
        "project_id",
        "project_name",
    }

    missing_columns = required_columns - set(component_data.columns)

    if missing_columns:
        raise ValueError(
            "Component data are missing required columns:\n"
            + "\n".join(
                f"  - {column}"
                for column in sorted(missing_columns)
            )
        )

    entries = []

    grouped = component_data.groupby(
        [
            "alternative_id",
            "alternative_name",
            "project_id",
            "project_name",
        ],
        sort=True,
    )

    for group_values, _ in grouped:
        (
            alternative_id,
            alternative_name,
            project_id,
            project_name,
        ) = group_values

        filename = make_filename(
            alternative_id=int(alternative_id),
            project_id=str(project_id),
        )

        page_path = REVIEW_DIRECTORY / filename

        if not page_path.exists():
            continue

        entries.append(
            {
                "alternative_id": int(alternative_id),
                "alternative_name": str(alternative_name),
                "project_id": str(project_id),
                "project_name": str(project_name),
                "filename": filename,
            }
        )

    if not entries:
        raise FileNotFoundError(
            "No Plotly component-review HTML pages were found."
        )

    updated_count = 0

    for entry in entries:
        page_path = REVIEW_DIRECTORY / entry["filename"]

        navigation_html = build_navigation_html(
            entries=entries,
            current_entry=entry,
        )

        add_navigation_to_page(
            page_path=page_path,
            navigation_html=navigation_html,
        )

        updated_count += 1

    print()
    print("=" * 70)
    print("PLOTLY REVIEW NAVIGATION COMPLETE")
    print("=" * 70)
    print(f"Component input used: {component_file.name}")
    print(f"Updated HTML review pages: {updated_count}")
    print(f"Open: {REVIEW_DIRECTORY / 'index.html'}")


if __name__ == "__main__":
    main()
