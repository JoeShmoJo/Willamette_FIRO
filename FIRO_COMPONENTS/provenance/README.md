# Input preparation provenance

These records explain how the active FIRO inputs were prepared. They are not
read by the normal calculation or plot workflow and are excluded from the
input-comparison tool's active data-folder scan.

- 06: legacy summary with reconciled project identities. Numerical fields repeat
  shared/project_space_summary.csv, but the row-to-project mapping is preserved.
- 07 and 16: legacy/candidate physical and decision-unit allocations. These are
  history, not competing active allocation files.
- 10 and 19: source/network preparation quality notes, including unresolved
  DSControlPoint mapping and scope exclusions.
- 13 and 14: detailed network paths and physical-project relationships used to
  prepare active decision-unit relationships (15). The original network.json
  is not tracked, so these are retained as source evidence.
- 17 and 18: comparisons with legacy relationships and intervening-reservoir
  exceptions.
- green_peter_*: saved daily patch anchors and audit. The saved audit records a
  no-change application; it is not proof of the first patch operation.
- rule_curve_backups/: the distinct earlier stored curve snapshot. The later
  snapshot identical to the active curve was removed.
- README_original_input_preparation.txt: original preparation notes, preserved
  as history; filenames and descriptions may refer to the old layout.

The patch script 00 still explicitly modifies the active recurring rule curve,
with new anchors, audit and timestamped backups written under
outputs/input_patches/ rather than creating more candidate input files here.

During cleanup, the complete allocation/geometry/capping/redistribution chain
was run against both old and new source-loading arrangements in isolated test
folders. All 26 output tables matched within floating-point rounding, including
component parameters and selected dates. Core model output CSVs in the working
repository were not overwritten by that regression check.
