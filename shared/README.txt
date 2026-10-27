SHARED INPUTS AND UTILITIES

common_data/
    Shared reservoir metadata, elevation-storage ratings, rule curves, and
    other common inputs. See common_data/readme.txt for source notes.
    These datasets have not all been reconciled or certified authoritative.

control_points_space.csv
    Existing downstream storage-space limits used directly by FIRO_COMPONENTS.
    Retain until FIRO is connected to reviewed replacement MAX outputs.

LP3_Residual.csv
    Residual flood-frequency parameters used by RULE_CURVE_WORKSHOP.
    Source: ResidualVolumeFrequency\out, September 1, 2026.
    This is not duplicated in common_data and remains an active input.

modules/
    Shared Python utilities.

datasets_sharepoint/
    Local copies of datasets maintained on the CW3E SharePoint site.
    Dataset contents are ignored by Git; see the folder README.

temp_data/
    Temporary/intermediate datasets, ignored by Git. See the folder README.

REMOVED REDUNDANT COPIES

project_data.csv, project_space_summary.csv, Willamette_Rule_Curves.dss,
and willamette_rule_curves.pkl were removed from this directory. Their
historical counterparts remain in MAX_FIRO_SPACE/data/; they were not moved
into common_data. The summary, DSS, and pickle copies were byte-identical.
The project settings agree apart from date formatting and small numerical
rounding differences. Active rule-curve workshop and delayed-drawdown scripts
use common_data/Willamette_Rule_Curves.csv.

MAX's retained snapshots are not freshly recalculated MAX outputs.
Project-specific FIRO inputs remain in FIRO_COMPONENTS/data/, with preparation
history in FIRO_COMPONENTS/provenance/.

SCRIPT / INPUT / OUTPUT CROSSWALK

Double-click Start-Script-Data-Crosswalk.cmd to browse sortable, searchable file
references, open scripts/data, locate files in Explorer, and export to CSV.
See Script-Data-Crosswalk-README.md for instructions and scan limitations.
