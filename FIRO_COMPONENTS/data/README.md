# Active FIRO inputs

This folder contains six local tables. Five are read by the model; the
alternative catalog is retained to describe the full set, including selections
not active in the current phase.

| File | Purpose | Used by |
| --- | --- | --- |
| 01_projects_physical.csv | Physical project parameters and seasonal dates | 01, 02 |
| 02_decision_units.csv | Allocation units, including the combined LOP/HCR unit | 01 |
| 03_rule_curves_long.csv | Current recurring FIRO rule curves | 02; explicitly changed by patch tool 00 |
| 11_system_alternatives.csv | Alternative catalog | Reference for interpreting selections |
| 12_alternative_component_selections.csv | Selected components for each alternative/project | 01, 02 |
| 15_network_control_points_decision_units.csv | Downstream constraint relationships | 01 |

Two inputs are read directly from shared sources rather than copied into this folder:

| Shared source | Replaces |
| --- | --- |
| shared/common_data/ElevStor.csv | 04_storage_elevation_long.csv |
| shared/control_points_space.csv | 05_control_point_limits.csv |

The paths above are relative to the repository root. Scripts normalize names,
IDs, column headings and acre-feet-to-KAF units when loading these sources.
FIRO now uses the same ElevStor.csv rating source as the workshop and delayed-
drawdown workflows. Its Reservoir/Elev/Stor columns are converted to normalized
project IDs and KAF in memory. This is a deliberate change from the former
spreadsheet rating source, so geometry results can change. The duplicated
04_storage_elevation_long.csv was already removed; the retired active spreadsheet
shared/storage_elevation.xlsx is removed as part of this source change.

Conservation-storage weights and evacuation caps in 01_projects_physical.csv
remain supplied project parameters; this source switch does not recompute them
from the rating curves. Reconciling those parameters is a separate input decision.

Preparation history, legacy comparisons and unresolved quality notes are in
../provenance/. They are not runtime input alternatives. The empty initial cap
template (08), redundant source-coverage table (09), and rule-curve backup that
was byte-identical to the working curve were removed. Current run coverage and
cap results are available in generated model/QA outputs.

Conflicts identified in the wider input review remain unresolved, including
the source choice for recurring rule curves, remaining fixed conservation-storage parameters, missing
spillway fields and operational-rate discrepancies. This cleanup does not
certify the retained data as authoritative.
