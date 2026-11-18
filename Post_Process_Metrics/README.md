# POR post-processing metrics

This provides a data audit, daily duration plots, and a first-pass comparison
across six purposes for the paired ResSim period-of-record snapshots. Ensemble
processing is deferred.
The folder currently tracked in Git is `Post_Process_Metrics` (mixed case).

## Run

On Windows, use the existing Conda `hydro13Nov2026` environment (Python 3.11).
From the repository root:

```powershell
cd 'C:\Projects\A_Recent_Projects\Willamette_FIRO_GIT'
conda activate hydro13Nov2026
python Post_Process_Metrics/inspect_por.py
```

To plot both cases from a local `simulation.dss`, pass its path:

```powershell
$dss = 'C:\Projects\A_Recent_Projects\JYTHON\NWP_Willamette_Master_2026_11_17_ReloadFix\rss\DAY_POR_Baseline_Proxy\simulation.dss'
python Post_Process_Metrics/inspect_por.py --simulation-dss $dss
if ($LASTEXITCODE -eq 0) {
    Invoke-Item Post_Process_Metrics/outputs/por_inventory/elevation_duration_plots.html
}
```

This selects the unique daily pool elevation F-parts ending in `-0` (Baseline)
and `-1` (Alternative). If there are multiple matches, use two explicit `--case`
arguments with the full F-parts and the same DSS path. Both cases share one
temporary copy, so the Windows temporary directory needs room for one copy of
the DSS file.

Without arguments the script compares `data/Baseline.dss` and `data/Alternative.dss`, selecting the
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
- `elevation_duration_plots.html`: one offline plot per reservoir, with
  Baseline and Alternative daily pool elevations in feet versus percent of
  time equaled or exceeded. Dashed horizontal lines show supplied boat-ramp
  elevations. Big Cliff has no ramp elevations in the supplied table.
- `duration_plots.html`: self-contained, offline daily elevation and outflow
  exceedance curves for each reservoir. Dashed lines on the elevation plots mark
  boat ramps from `data/boat_ramp_elevations.csv`. Hover over a line for each
  case's percentage of valid days strictly above that elevation. Ramps at the
  same elevation share a line and are listed together. Each curve uses its own
  available days. Check coverage before comparing different periods. The ramp
  percentages use actual pool elevations for all available dates. The seasonal
  recreation metrics apply additional operating-rule criteria.
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

## Six-purpose comparison

For the local 1935–2019 simulation, select the shared DSS and requested years:

```powershell
python Post_Process_Metrics/compare_purposes.py --simulation-dss $dss --first-year 1935 --last-year 2019
if ($LASTEXITCODE -eq 0) {
    Invoke-Item Post_Process_Metrics/outputs/purpose_comparison_local/index.html
}
```

This uses the same `-0` Baseline and `-1` Alternative convention as the
elevation report. Each metric's plots show how many periods have complete paired
coverage. Water years run October 1 of the previous calendar year through
September 30. Recreation windows run February 1 through December 1 of the
labeled calendar year. If the DSS begins in January 1935, water year 1935 is
incomplete. The 2019 ramp season requires data through December 1, 2019.

Local DSS mode provides an elevation-only ramp screen, counting a ramp-day when
pool elevation is strictly above the ramp. Verified recreation ramp-days and
special-release counts require run-specific evidence. For those metrics, use
`--config` with matching model reports and FIRO evidence. Set both case
`dss` paths to the local file, enter each full `f_part`, and set
`first_year` and `last_year` to the intended window in that configuration.

To reproduce the bundled example with matching run evidence:

```powershell
python Post_Process_Metrics/compare_purposes.py
Invoke-Item Post_Process_Metrics/outputs/purpose_comparison/index.html
```

The command uses the paired cases and years in `recreation_config.json`.
Non-recreation metrics use complete paired water years 1991–2000 (October 1,
1990 through September 30, 2000), excluding the two leading audit days.
Recreation uses the configured season within each calendar year. All changes
are Alternative minus Baseline. Annual values are blank if an expected paired
date is missing. Recreation completeness is reported in the recreation tables.

| Purpose | First-pass comparison | Inputs still needed |
| --- | --- | --- |
| Flood Control | Peak daily routed flow at Albany and Salem is an exposure proxy. Special-release days use the study's strict outflow test at the applicable projects. | Approved downstream thresholds and impact information for bankfull, flood impacts, or damages. |
| Hydropower | Annual discharge volume through each of eight modeled powerplants, in acre-feet, is a throughput proxy. | Net head, efficiency, operating limits and generation or pricing data. |
| Recreation | Verified FIRO activation and reconstructed daily zone membership feed February 1–December 1 boat-ramp days by reservoir and system. | Confirm workbook/DSS vertical datum. |
| Water Quality | The 10th percentile of daily routed flow at Albany and Salem gives low-flow context. | Water temperature, dissolved oxygen, or a calibrated constituent model and applicable criteria. |
| Water Supply | Minimum daily total pool storage by reservoir is a storage proxy. | Approved usable-storage bounds, accounting, demand, delivery, and any snapshot dates. |
| ESA flow compliance | Both cases' routed flow is screened against the same positive daily `Min_Flow_Target_*/Flow-Min` series saved in the Alternative DSS. | Verified water-year-specific ESA targets and compliance criteria. The Baseline lacks a usable target and the shared reference screen does not establish ESA compliance. |

The flood test compares daily total pool outflow strictly above the named
`Flow-MAX` rule value when that rule is in the reconstructed operating-zone
stack. Hills Creek uses its corresponding `Max Evacuation Rate` rule. Big
Cliff, Dexter and Foster have no matching rule in the supplied stacks. A known
zone without the rule contributes zero special-release days. An unknown zone
or missing required outflow or limit leaves the day unknown. The rule output
and the corresponding model report must come from the same run.

The ESA reference screen counts days strictly below the Alternative's saved
model target at Albany and Salem. Zero target days are outside the comparison,
and missing target days make the year incomplete. Using one common reference
keeps the paired comparison on the same dates. The saved model target has no
verified ESA status for this analysis.

Outputs under `outputs/purpose_comparison/` include an offline HTML report,
`annual_comparison.csv` with coverage and paired changes,
`daily_threshold_checks.csv` with rule or target inputs and event flags,
`provenance.json` with source hashes and DSS paths, and the existing recreation
reports in `recreation/`. Source DSS files are opened through temporary copies.

In the HTML report, choose a metric to see the system and applicable locations
stacked on one page. Each row has Baseline and Alternative box plots, ranked
duration curves, and a bar chart of Alternative minus Baseline by year.
The distributions use complete paired water years or recreation
seasons. For daily pool elevation duration curves, use the separate elevation
report described above.

`SYSTEM` includes special-release reservoir-days across applicable projects,
total throughput across modeled powerplants, the minimum of the daily combined
pool storage, and total seasonal ramp-days. The sum of plant throughput can
include the same water at successive plants. System storage is the minimum of
the daily sum, which preserves the timing of reservoir storage. Missing member
data make the system result incomplete. Routed flow and minimum-flow screening
stay separate at Albany and Salem because the sites share upstream flows.

The system storage section plots the duration of daily combined storage relative
to a common zero. Zero is the lowest observed Baseline daily system total in
the complete paired conservation seasons. The default reference window is
February 1–December 1, inclusive. Override it with `--storage-season MM-DD MM-DD`
if the conservation season differs from the configured recreation season.
Both cases subtract the same value, including on days when the result is negative.
The daily duration curve uses paired days across the requested water years. The
dropdown option **Maximum combined storage relative to seasonal minimum** uses
one peak daily system total per complete water year. The reference is an
observed storage level. Approved usable-storage bounds are a separate input.

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
is corrected by inference. The original workbook is unchanged.

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
The default season is February 1 through December 1 inclusive for 1991–2000.
Set `season` in the configuration to change the dates. Outputs include daily availability, ramp and
reservoir/system seasonal totals, paired changes, seasonal percentiles and box
plots. The bundled DSS files end September 30, 2000, so 1991–1999 have complete
seasons and 2000 appears as incomplete in the coverage tables. FIRO receipts record enabled
at 11 reservoirs in both runs. Zone membership is reconstructed using previous-day
pool elevation and saved zone tops, following the prior checker. Dexter has no
FIRO rule in its stacks and uses its rule curve alone. The receipt/report linkage
uses the supplied corresponding run folders; receipts do not contain a DSS-content
hash, so they are not independent proof against a later replacement of simulation
results. Earlier provisional results are marked `UNVERIFIED_FIRO` and must not be
used as study results.

Run the study-rule tests with
`python -m unittest discover -s Post_Process_Metrics -p test_recreation.py -v`.
