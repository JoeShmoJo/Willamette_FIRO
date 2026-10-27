# Final combined FIRO curves

Use `alternative_XX_combined_curves.csv` in this folder for the **after-reallocation** result.
Each file contains all modeled reservoirs for one alternative, one row per reservoir per day.
`baseline/` holds the corresponding **before-reallocation** curves for comparison.
Alternative 5 has no selected components and therefore has no curve file.

These are the final capped combined envelopes, not the individual component curves.
- `combined_storage_kaf`: total storage coordinate of the combined envelope.
- `combined_offset_kaf`: FIRO-space offset from the rule-curve storage; use this for FIRO space.
- `rule_storage_kaf`: reference rule-curve storage.
- `rule_elevation_ft`: reference rule-curve elevation, in feet.
- `allocated_project_firo_space_kaf`: allocation limit used for that reservoir and alternative.
- `controlling_component`: component controlling the envelope on that date.
- `allocation_case`: `after` or `before`; IDs and names identify the alternative and reservoir.

KAF means thousand acre-feet. Dates cover the existing August 2018–July 2019 model year;
these are planning curves, not historical observations or a routed operating simulation.
Do not treat `combined_storage_kaf` as FIRO space or infer elevation from storage without a rating table.

Rebuild with `python FIRO_COMPONENTS/run.py model` (or `all`). Source inputs, physical assumptions,
and supplied control-point limits retain the limitations documented in the project README.
Supporting numerical tables, QA reports, plots, and scenario provenance live in `../diagnostics/`.
