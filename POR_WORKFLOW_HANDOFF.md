# CSV POR comparison handoff

Updated 2026-11-24. See [AGENTS.md](AGENTS.md) for PowerShell and repository
standards. [JYTHON](https://github.com/JoeShmoJo/JYTHON/blob/main/POR_WORKFLOW_HANDOFF.md)
owns ResSim configuration and exports. The user confirmed the three-run
comparison looked good after running `ALL_D-----0`, `ALL_D-----1`, and
`ALL_D-----2` in `DAY_POR_Baseline_Proxy`.

## Progressive FIRO and WAT handoff

The Windows analysis checkout is
`C:\Projects\A_Recent_Projects\Willamette_FIRO_GIT`. The user confirmed
a clean full merge through `14ed1f5`. The subsequent `336697e` flattening
was published to GitHub. Whether the Windows checkout pulled that commit
and moved the generated files was not confirmed.

The progressive generator and review use
`shared/common_data/Willamette_Rule_Curves.csv` and `ElevStor.csv`.
The 2001 non-leap schedule is the repeating offline baseline. ResSim still
gets the `ALL_D` rule curves from the study. Equivalence to the offline
baseline and a WAT recompute with the latest CSVs remain unverified.

Follow the [output guide](FIRO_COMPONENTS/outputs/README.md) to regenerate
the eight WAT CSVs and review directly in `FIRO_COMPONENTS/outputs`. Open
`index.html`. The Lookout Point demonstration uses storage only and has
all eight component traces. The component pages show storage and elevation
with axis titles that follow the selected tick spacing, plus the constraint
and utilization table. All eight CSVs passed the offline reservoir and
shared-limit checks. Keep the review HTML files and `plotly.min.js` together
when sharing. See the [progressive workflow](FIRO_COMPONENTS/PROGRESSIVE_FIRO.md)
for installation and refresh commands.

## Run the comparison

Use [compare_por_trials.py](Post_Process_Metrics/compare_por_trials.py) with the
simulation folder and `--targets` pointing to the watershed's
`scripts/externalSVs` folder. On Windows, work from
`C:\Projects\A_Recent_Projects\JYTHON` and use
`C:\Users\g2encjer\AppData\Local\miniconda3\envs\hydro13Nov2026\python.exe`.
The local watershed is `NWP_Willamette_Master_2026_11_17_ReloadFix`. The tested
launcher stages the Git files in a temporary sparse checkout, so a separate
Windows Willamette_FIRO checkout is optional. Use `main` for new runs after this
integration. Preserve the exact path list from the last working command or read
imports and data paths from the current entry points before narrowing it.

The overview compares the completed configured ALL_D trials against trial 0.
Without an assignment file, it discovers numbered ALL_D trial exports. Each
trial needs an export and matching compute report. The overview lists any
configured trials it excluded. Select a metric to see all locations on one responsive grid. Annual points
are centered on the boxes. The table lists the minimum, the 25th, 50th and
75th percentiles, and the maximum.
Individual trial links open the paired plots. Configuration comparison opens
one page with a separate list of differences from trial 0 for each trial. The
output is under `por_csv_plots/<run-id>/index.html`. Each comparison includes
box and duration plots, stacked annual reservoir elevation and outflow plots,
system metrics duplicated on a system page, Salem and Albany pages for the
2008 BiOp and HD531 regimes, model settings, annual CSV, and source provenance.
It uses the existing plot layout and does not open DSS. Eugene is excluded.
Flood exceedance count axes start at zero.

## Interpretation and provenance

- The BiOp metric uses the fixed minimum-flow component. The combined metric uses
  each compute's captured minimum-flow and withdrawal tables. It screens daily
  outflows against the summed schedule and requires both captured tables.
- Flood metrics use October through September water years. Other annual
  metrics use January through December calendar years. System maximum storage
  takes the calendar-year maximum of each day's summed
  storage above Min Con. Each reservoir's Min Con is the lowest conservation
  rule curve elevation, converted to storage with its captured elevation–storage
  rating. Negative values are floored at zero. Memorial Day and Labor Day report storage and count ramps
  strictly below the daily pool elevation, by reservoir and for the system.
  These screens use the holiday date and pool elevation.
- Stacked plots use August–July display years, with storage above Min Con on
  the left and elevation on the right. Control-point exceedances use bankfull.
  Thresholds prefer the compute JSON, then the watershed plotting script for
  Harrisburg, Jefferson, Salem and Albany, then the report CSV.
- The elevation screen counts days strictly above the Lookout Point (887.5 ft)
  and Detroit (1,541 ft) spillway crests from BasicProjectData.csv, and Cougar’s
  1,571 ft minimum temperature tower elevation.

- Included CSVs must share the same daily timestamps. The pipeline interprets
  daily midnight timestamps as interval end and shifts them back one day.
  Completeness checks retain partial years without presenting them as complete.
- The CSV names identify their trials but contain no compute ID. The launcher
  matches each CSV to the latest report for its full F-part and checks a
  two-minute write-time tolerance. Review the selected filenames, compute IDs,
  and captured configuration names before interpreting results. Retain a copy
  of both files when another compute would overwrite a CSV.
- Hydropower is a powerhouse-first estimate derived from pool elevation,
  reported powerhouse capacity and total outflow. It is estimated throughput.
  **Days above Max Evac** counts total outflow strictly above the exported
  curve at previous pool elevation without zone gating. Use the exported
  limit definition when interpreting this screen. Rule activation requires
  separate evidence.
- Model settings use the compute's captured configuration and compare table
  content or checksums. Differences in snapshot paths alone do not flag
  matching tables. The input-mapping comparison follows saved ResSim links
  and reads mapping references, which can change after compute. The
  `--baseline-fits` and `--alternative-fits` options on
  [run_csv_por_plots.py](Post_Process_Metrics/run_csv_por_plots.py) can identify
  exact saved mapping files for an individual comparison.
- Earlier DSS-based commands remain available for existing callers. The new
  CSV entry point is the one to use for this workflow.

## Validation

The full comparison was smoke-tested with three CSV and report fixtures,
including both plot sets and their settings pages. The user then confirmed the
output from the three Windows POR computes looked good.
