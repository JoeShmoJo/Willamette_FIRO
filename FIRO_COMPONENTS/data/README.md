# Active FIRO inputs

This folder contains five local tables. Four are read by the model; the
alternative catalog is retained to describe the full set, including selections
not active in the current phase.

| File | Purpose | Used by |
| --- | --- | --- |
| 01_projects_physical.csv | Physical project parameters and seasonal dates | 01, 02 |
| 02_decision_units.csv | Allocation units, including the combined LOP/HCR unit | 01 |
| 11_system_alternatives.csv | Alternative catalog | Reference for interpreting selections |
| 12_alternative_component_selections.csv | Selected components for each alternative/project | 01, 02 |
| 15_network_control_points_decision_units.csv | Downstream constraint relationships | 01 |

These inputs are read directly from shared sources rather than copied into this folder:

| Shared source | Replaces |
| --- | --- |
| shared/common_data/Willamette_Rule_Curves.csv | 03_rule_curves_long.csv |
| shared/common_data/ElevStor.csv | 04_storage_elevation_long.csv |
| MAX_FIRO_SPACE/out/ControlPointsSpace.csv | 05_control_point_limits.csv |
| MAX_FIRO_SPACE/out/ReservoirEvacLimits.csv | Seven-day evacuation limits previously supplied in the local project and decision-unit tables |

The paths above are relative to the repository root. Scripts normalize names,
IDs, column headings and acre-feet-to-KAF units when loading these sources.
FIRO now uses the same ElevStor.csv rating source as the workshop and delayed-
drawdown workflows. Its Reservoir/Elev/Stor columns are converted to normalized
project IDs and KAF in memory. This is a deliberate change from the former
spreadsheet rating source, so geometry results can change. The duplicated
04_storage_elevation_long.csv was already removed; the retired active spreadsheet
shared/storage_elevation.xlsx is removed as part of this source change.

The shared rule-curve CSV contains dated elevations that can vary by year.
FIRO uses the complete 2001 non-leap calendar as its repeating analysis
baseline for both curve generation and plotting. This schedule is a modeling
choice. WAT and ResSim still resolve their rule curves from the study.

Conservation-storage weights remain supplied project parameters in
01_projects_physical.csv. The allocator reads the seven-day evacuation limits
directly from MAX_FIRO_SPACE and caps each project and decision unit at the
smaller of its evacuation limit and conservation storage. The separate combined
Lookout Point + Hills Creek evacuation row applies when both projects participate.

Preparation history, legacy comparisons and unresolved quality notes are in
../provenance/. They are not runtime input alternatives. The empty initial cap
template (08), redundant source-coverage table (09), and rule-curve backup that
was byte-identical to the working curve were removed. Current run coverage and
cap results are available in generated model/QA outputs.

Conflicts identified in the wider input review remain unresolved, including
remaining fixed conservation-storage parameters, missing
spillway fields and operational-rate discrepancies. This cleanup does not
certify the retained data as authoritative.
