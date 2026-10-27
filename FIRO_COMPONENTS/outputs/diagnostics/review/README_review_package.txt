FIRO REVIEW PACKAGE
===================

Purpose
-------
This folder is the normal human-review location for the FIRO model.
Review rebuild inputs are consolidated in ../scenarios/. Optional extra
intermediate and QA exports are saved in ../extra/ only when requested.

Open these files first
----------------------
1. index.html
   One-page index linking to every targeted review output.

2. 01_alternative_summary.csv
   One row per alternative. Shows total baseline FIRO space, total
   redistributed FIRO space, the system increase, and the number of
   decision units receiving redistributed space.

3. 02_decision_unit_changes.csv
   Only decision units whose allocations increased after redistribution.

4. 03_project_changes.csv
   Only physical reservoirs whose allocated FIRO space increased after
   redistribution. The daily review pages let you toggle between the corresponding
   before/after component curves.

5. 04_control_point_comparison.csv
   Baseline and redistributed control-point utilization side by side.

6. 05_quality_exceptions.csv
   Warnings, errors, or non-passing rows gathered from existing QA/QC reports.

Current review counts
---------------------
Alternatives:                         8
Decision units receiving space:       4
Physical projects receiving space:    4
Control-point comparison rows:        75
Quality/QA exceptions:                0

Important
---------
- No source, model, or existing output file was moved or deleted.
- Baseline means no redistribution after a project/decision unit reaches
  its physical cap.
- Redistributed means the constrained optimization case.
- Plotly geometry review remains in:
      ../plotly_component_review/index.html
