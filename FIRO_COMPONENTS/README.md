# FIRO Components

Build baseline FIRO-space allocations and daily component/envelope curves,
calculate a separate redistribution case, and review the resulting geometry.

For a plain-language description of parameter searches and allocation optimization,
see [How optimization works](HOW_OPTIMIZATION_WORKS.md).

## Final curves

For the progressive WAT CSVs and plots, see the [output guide](outputs/README.md).
In the optional system-alternative workflow, each
`alternative_XX_combined_curves.csv` contains the final capped combined curves
for all reservoirs in that alternative, after reallocation. Before-reallocation
versions are in `outputs/final/baseline/`. Use `combined_offset_kaf` for FIRO space
above the rule curve and `combined_storage_kaf` for total storage.
Both `model` and `all` rebuild these final files. Alternative 5 has no curve output.

All intermediate tables, QA reports, plots and comparison data are kept separately
in `outputs/diagnostics/`.

## System-alternative review

To recreate the local system-alternative plots and diagnostics, run
`python FIRO_COMPONENTS/run.py all` from the repository root. Then open
`outputs/diagnostics/review/index.html`. It links to:

- **Utilization overview:** the default reservoir/control-point daily overview.
- **Controller diagnostics:** constraint status and the component controlling each envelope.
- **Component detail:** individual component storage/offset plots with navigation.
- **Allocation and QA tables:** baseline versus redistributed allocation summaries.

Each retained daily chart has a **Before reallocation / After reallocation**
selector. After reallocation is the initial default; your selection is remembered
when browser storage is available. The component shapes are recalculated from
each allocation case, including timing, capped envelopes and status ribbons.
The project/alternative allocation amounts are shown above each chart.
All daily control-point loading is an unrouted storage-space screen, without
travel time, attenuation, local inflows or operational release simulation.

## Run

On Windows, use the existing `hydro13Nov2026` Python environment. Its NumPy,
pandas, Matplotlib and Plotly versions are compatible with FIRO Components.
The published JYTHON environment spec does not include SciPy. Check for
SciPy 1.17.1 and, if needed, install only that package in the environment
with `python -m pip install --no-deps scipy==1.17.1`.

For a separate Python environment, install the requirements from the repository
root. Run the full build from the same directory:

```sh
python -m pip install -r FIRO_COMPONENTS/requirements.txt
python FIRO_COMPONENTS/run.py all
```

The default builds final curves and the complete interactive review, then removes
unneeded intermediate exports. Use `model` for numerical/final results only, or
`review` to rebuild the plots from saved allocation inputs. Review calculations
still run in compact mode; only expendable files are discarded after success.
Existing plots are not refreshed by a model-only run; use `review` or `all` afterward.

For additional intermediate/QA CSVs and static diagnostic plots:

```sh
python FIRO_COMPONENTS/run.py all --diagnostics
```

These optional exports live in `outputs/diagnostics/extra/`. A subsequent default
run removes that generated extra folder. Required inputs are consolidated under
`outputs/diagnostics/scenarios/model/`; each before/after folder retains only its
allocations, capped component curves, and reservoir/control-point plot data.
The final combined curves are stored only in `outputs/final/`, with their baseline
counterparts there. The legacy separate capacity-status set is no longer retained.

Commands stop on failure and leave working files available for troubleshooting.
Run stages through `run.py` for automatic staging and cleanup; individual scripts
remain development tools and may require staged intermediate files. Headless
machines should set `MPLBACKEND=Agg`. Keep review folders and their local Plotly
assets together.

## Calculation stages

Numbered tables below identify calculation products; most intermediates are
retained only with `--diagnostics`. The normal run keeps final curves and the
consolidated inputs required to rebuild the review.

| Scripts | Purpose | Outputs |
| --- | --- | --- |
| 01 | Baseline allocation | 20–27 |
| 02 | Component geometry and daily envelopes | 30–34 |
| 03 | Cap and validate curves; static diagnostic plots | 35–39 and plots/ |
| 05 | Separate redistribution optimization | 40–47 |
| 11 | Numerical capacity/status preparation | scenarios/before and after/capacity_status/ |
| 15 (using 14, 13) | Two-case overview and controller diagnostics | review/utilization_ribbon_overview, review/constraint_controller_overview |
| 15 (using 04, 07) | Two-case component detail and navigation | plotly_component_review/ |
| 06 | Allocation/QA summary and review landing page | review/index.html and summary tables |

Recurring rule curves and storage ratings come from `shared/common_data`.
The component model uses the complete 2001 non-leap rule-curve schedule
as its repeating baseline. See the [input guide](data/README.md) and
[preparation records](provenance/README.md).

## Cleanup

Removed redundant backup scripts, the duplicate E/K trial builder and obsolete
source-editing tools. Removed earlier no-routing utilization/alternative overview
and combined-constraint visualization families. The standalone capacity pages
were removed while retaining their numerical preparation for scripts 13/14.

Core calculation logic and existing root allocation/curve CSV outputs were
preserved during input cleanup; source-loading in 01/02 now reuses verified
shared tables. The before/after calculation-chain regression matched all 26
output tables within floating-point rounding. Component-detail HTML
was regenerated with a shared offline Plotly asset and matching filename case.
The capacity-table preparation was checked against its original implementation:
all three resulting tables matched exactly. These checks do not independently
validate the hydrologic assumptions or certify the stored results as current.

Alternative 5 is cataloged but has no component-selection rows and no daily
outputs. F/G components remain deferred. A zero-exception output-stage QA summary
does not resolve every source-data/provisional-model warning; consult the preparation quality and topology reports in `provenance/` as well.

## Reallocation comparison data

`run.py review` rebuilds the two daily curve cases from the baseline allocations
(output 25) and redistributed allocations (output 43). It uses the same geometry
and cap calculations for both, without replacing the original root model CSVs.
The retained plot-support tables live in `outputs/diagnostics/scenarios/before/` and
`after/`, with reservoir/control-point plot data in each case's `capacity_status/` folder.
Repeated combined curves and other intermediate CSVs are not retained in the default run.
`outputs/diagnostics/scenarios/manifest.json` records source/algorithm hashes.

All 89 retained chart pages contain both cases, rather than linking to a separate
set of reallocated charts. The selector redraws one chart in place. Use the allocation summary to compare before and after budgets across alternatives.

For the numerical regression checks after building comparisons:

```sh
python -m unittest discover -s FIRO_COMPONENTS/tests
```

## Optional fixed-allocation WAT comparison

From the repository root, run:

```sh
python FIRO_COMPONENTS/export_wat_components.py
```

The exporter rebuilds an all-project scenario for each implemented code
(A, C, E, H, I, J, K) with the current MAX_FIRO_SPACE constraints. Each CSV
uses the capped after-reallocation storage converted to elevation using the
same rating table as the model. Dates with no positive offset are blank so
the FIRO-space rule stands down. The CSVs are written to
`outputs/diagnostics/legacy_fixed_allocation/`, with `Month,Day` and one column per modeled
reservoir. See [component definitions](HOW_OPTIMIZATION_WORKS.md#component-definitions)
for the geometry and applicable fallbacks. H applies only to Green Peter,
Detroit, and Lookout Point. F and G are deferred.

For each WAT case, reuse `ALL_D` and `POR_1935-2019`. Place the corresponding
CSV under the watershed's `scripts/externalRules/` and set
`firoSpaceConfigCSV` in that WAT alternative's override file. The JYTHON
watershed's `WAT_FIRO_ALTERNATIVES.md` describes the WAT registration and
companion files.

Add `--review` and open `outputs/diagnostics/legacy_fixed_allocation/diagnostics/review/index.html`.
Each alternative has one scrollable page with the exported WAT targets over
the ordinary rule curves. Storage above MinCon is on the left and elevation
is on the right. The page-wide selector switches the evenly spaced axis.
Each page contains a table of the constraint, maximum achieved, and percent
utilized for each reservoir, control point, and shared reservoir limit. The
control-point maximum is the peak of same-day upstream storage offsets.

### Compare proportional scaling for Component K

Run `python FIRO_COMPONENTS/compare_k_scaling.py` to compare whole-day and
whole-hour refill advances. Each run selects the local curve with the most
KAF-days at each reservoir, then checks the selected shapes on the same hourly
grid. The hourly grid interpolates the model's daily rule-curve storage values.
It does not use measured hourly flows.

The highest common retention floor is the smallest ratio of a shared limit to
its combined unscaled offset over all hours, capped at one. The linear program
then maximizes system KAF-days with that floor and separate reservoir scale
factors. It checks all downstream control-point limits and the combined Lookout
Point–Hills Creek cap. Results in
`outputs/diagnostics/k_scaling_comparison/` include the limiting time, local
advances, final retained fractions, and loading at each shared limit.

This comparison scales storage offsets from the selected K shapes and can
change their exact time-shift geometry. It does not replace the standard WAT
component CSVs.

Add `--all-components` to compare A, C, E, H, I, and J in addition to the
two K runs. For components other than K, the comparison searches 24 evenly
spaced local storage budgets through the existing component builders and
keeps the feasible curve with the most KAF-days among those samples. Use
`--samples` to refine that search. H includes only Green Peter, Detroit,
and Lookout Point.

The progressive method starts at the common floor. It freezes reservoirs
with positive offsets at each binding control point and time and raises
the remaining reservoirs together until they reach another limit. The reports
show common and progressive fractions, KAF-days, peak space, and shared
control-point loads. The original total-area linear program is retained as
a comparison column. All runs use unrouted storage offsets.

See [Progressive FIRO scaling](PROGRESSIVE_FIRO.md) for the worked example and WAT installation workflow.
