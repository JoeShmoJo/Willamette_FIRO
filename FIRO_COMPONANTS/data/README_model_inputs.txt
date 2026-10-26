FIRO CANONICAL MODEL INPUTS
===========================

Generated:
    2026-10-23T12:54:08

Purpose:
    These files are derived copies of legacy source data. The source files
    in the project root and data/ folder were not modified.

Core model scope:
    - Physical reservoirs are retained for rule-curve and component geometry.
    - LOP_HCR is the allocation decision unit for Hills Creek and Lookout
      Point because Hills Creek is upstream of Lookout Point.
    - Big Cliff and Dexter remain available in rule/rating sources but are
      not included in the initial allocation model because project_data.csv
      does not provide the corresponding evacuation/operational parameters.

Output files:
    01_projects_physical.csv
        Physical projects with curve-relevant project parameters.

    02_decision_units.csv
        Allocation decision units, including the lumped LOP_HCR system.

    03_rule_curves_long.csv
        Daily recurring rule curves in long format.

    04_storage_elevation_long.csv
        Elevation/storage table for interpolation.

    05_control_point_limits.csv
        Total downstream space limits by control point.

    06_legacy_project_space_summary_reconciled.csv
        Legacy project-space summary matched to projects through numerical
        keys rather than assumed row order.

    07_project_control_points_candidate.csv
        Candidate project/control-point relationships inferred from nonblank
        legacy allocation values. Requires review before operational use.

    08_project_allocation_caps.csv
        Per-decision-unit physical caps before downstream allocation.

    09_source_coverage.csv
        Source completeness for physical-project curve generation.

    10_data_quality_report.csv
        Warnings, unresolved mappings, scope exclusions, and errors.

Next modeling step:
    Review and validate project_control_points_candidate.csv, then implement
    the transparent control-point allocation model.
