# POR post-processing metrics

This provides a data audit, daily duration plots and POR recreation metrics,
including seasonal boat-ramp-day totals, box plots, seasonal exceedance plots,
system rollups and paired baseline changes. Other purpose metrics and ensemble
processing are not implemented yet.
The folder currently tracked in Git is `Post_Process_Metrics` (mixed case).

## Run

From the repository root in an activated Python 3.12 environment:

```powershell
cd 'C:\Projects\A_Recent_Projects\Willamette_FIRO_GIT'
python -m pip install -r Post_Process_Metrics/requirements.txt
python Post_Process_Metrics/inspect_por.py
```

The default compares `data/Baseline.dss` and `data/Alternative.dss`, selecting the
`ALL_D-----0` F part explicitly in both files. File labels distinguish the cases;
the shared F part does not identify which operating alternative each represents.
Additional or different cases can be selected without editing the script:

```powershell
python Post_Process_Metrics/inspect_por.py --case Baseline Post_Process_Metrics/data/Baseline.dss ALL_D-----0 --case Alternative Post_Process_Metrics/data/Alternative.dss ALL_D-----0
```

Outputs are ignored under `outputs/por_inventory/`:

- Per-case catalogs of all DSS records, grouped across date blocks.
- `coverage.csv`: available dates, valid/missing day counts and descriptive
  statistics for daily pool elevation, inflow and outflow.
- `paired_daily_comparison.csv`: mean alternative-minus-baseline differences on
  dates valid in both cases, and paired day counts.
- `duration_plots.html`: self-contained, offline daily elevation and outflow
  exceedance curves for each reservoir. Each curve uses its own available days;
  check coverage before comparing different periods.
- `inputs.json`: labels, input paths and selected F parts.

The input files are copied to temporary storage before opening: HEC-DSS can
modify bookkeeping even when its reader requests read-only access. Daily ResSim
interval-end midnight stamps are shifted back one day. Confirm that convention
against the simulation before defining study windows. Read failures, overlapping
blocks and inconsistent units stop the audit rather than silently dropping data.
Both files' pool results currently span 1990-09-29 through 2000-09-30 inclusive:
3,655 valid daily values for each of three parameters at 13 reservoirs per case.
These files do not yet supply the intended 84-year coverage. Initial days may be
model lookback; the audit retains them and makes no claim that they are study days.

## Optional model metadata

Run `copy_model_metadata.ps1` in PowerShell. It copies configuration TXT/CSV
files and rule-stack JSON reports from the supplied local watershed into
`model_metadata/`, preserving paths and recording SHA256 hashes. It does not copy
DSS files or overwrite differing metadata. Review the copied alternative configs
for references to files outside the standard folders; those may need another copy.

The standard input table families read by `model_check` are FIRO space, minimum
flow, withdrawals, diversions, and Salem/Albany BiOp targets. Copying all CSVs in
the two standard configuration directories also captures alternative-specific
names without assuming the defaults are correct. Model reports can be overwritten
by later computes: identify which simulation and DSS snapshot each report belongs
to before using its zone/rule order. Shared rss reports alone cannot prove this.

The imported checker can identify rules returning values equal to release, but
multiple rules may tie. This is diagnostic evidence, not unique causal attribution.
Do not substitute the lowest water-year target for the applicable ESA target.
Prefer the saved model target where available or reconstruct the actual target
using its documented year-type selection.

## Boat ramp inputs

`python Post_Process_Metrics/convert_boat_ramps.py` converts the supplied
`data/Boat_Ramp_Elevations.xlsx` to `data/boat_ramp_elevations.csv`: one row per
ramp, with basin, normalized reservoir name, ramp name, elevation in feet, and
source sheet/row. It preserves all 36 ramps at 12 reservoirs, including separate
ramps sharing an elevation. `Fall Ck` is normalized to `Fall Creek`; trailing
whitespace is trimmed. Vertical datum is not specified in the workbook and must
match the simulated pool elevations before use.

The 24 conservation-pool reference rows are exported separately to
`boat_ramp_pool_references.csv` and are not counted as ramps or automatically
adopted as water-supply bounds. `boat_ramp_conversion_issues.json` flags Dexter's
two maximum-pool labels (695 and 690 ft) and absent minimum-pool label; no label
is corrected by inference. The original workbook is unchanged. The recreation
evaluation season remains to be selected.

FRM special-curve days are defined by the study as outflow strictly greater than
the applicable Max Evacuation Release. Use the matching rule value, not the
combined Flow-MAXLIM, which can reflect other constraints.

## Recreation calculations

`recreation.py` implements a ramp-day as both actual pool elevation and
`max(rule curve, enabled FIRO target)` being strictly above the ramp. Disabled
FIRO uses the rule curve alone. Unknown activation produces unknown availability,
not zero; incomplete seasons are excluded from percentile and box-plot results.
System totals sum all ramps within each season before calculating percentiles.

The supplied target spreadsheet does not establish FIRO activation. The default
`recreation_config.json` links each case to its run marker, resolved configuration,
initialization receipts and model report. Receipts must match the selected POR F
part, configuration ID and resolved hash. The actual target table is resolved from
that configuration and its recorded checksum is verified. Git's normalization of
Windows text is handled by reconstructing CRLF bytes and requiring an exact match
to the unchanged original checksum; arbitrary content changes fail verification.
An optional explicitly supplied `firo_activation_csv` supports alternative data
sources with `date,reservoir,enabled` columns (`true`, `false`, or `unknown`).
Missing activation is unknown, never inferred from the target spreadsheet.
Flow-SPEC equal to zero is not assumed to mean off, and equality to actual release
means a rule may be controlling, not that all other enabled rules are off.

The supplied FIRO source and runtime adapter identify run-specific active JSON
markers, immutable configuration sets containing `resolved.json` and table
hashes/paths, and `initialization-receipts` with FIRO `active`, `reservoir`,
`output_fpart` and resolved-configuration hash. The runtime can override both
`firoActive` and the target CSV, and can dispatch through an RTS runtime.
Use these configuration records to establish the actual settings; the shared
alt_config and target CSV alone are insufficient. `copy_run_configuration.ps1`
collects markers and their referenced JSON/CSV artifacts for the two POR runs,
preserving model-relative paths and refusing to overwrite differing copies.
Confirm artifacts correspond to the supplied DSS snapshots before adoption.

Run `python Post_Process_Metrics/recreation.py` from the repository root.
The initial configurable season is Memorial Day through Labor Day inclusive for
1991–2000; a fixed season can instead be specified as
`{"type":"fixed","start":"05-01","end":"09-30"}`. No season has yet been
confirmed by the study owner. Outputs include daily availability, ramp and
reservoir/system seasonal totals, paired changes, seasonal percentiles and box
plots. Initial validation produced complete results for all 36 ramps in both
cases across ten seasons, with no unknown ramp-days. FIRO receipts record enabled
at 11 reservoirs in both runs. Zone membership is reconstructed using previous-day
pool elevation and saved zone tops, following the prior checker. Dexter has no
FIRO rule in its stacks and uses its rule curve alone. The receipt/report linkage
uses the supplied corresponding run folders; receipts do not contain a DSS-content
hash, so they are not independent proof against a later replacement of simulation
results. Earlier provisional results are marked `UNVERIFIED_FIRO` and must not be
used as study results.

Run the study-rule tests with
`python -m unittest discover -s Post_Process_Metrics -p test_recreation.py -v`.

Next inputs needed for purpose metrics: study dates and seasons, water-supply bounds and snapshot dates,
power conversion/capacity relationships, and water-quality estimation functions.
Bankfull thresholds already exist in shared data and in the prior checker, but
their definitions and units must be reconciled before adopting either source.
