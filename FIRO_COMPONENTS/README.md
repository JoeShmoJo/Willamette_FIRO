# FIRO Components

Build baseline FIRO-space allocations and daily component/envelope curves,
calculate a separate redistribution case, and review the resulting geometry.

For a plain-language description of parameter searches and allocation optimization,
see [How optimization works](HOW_OPTIMIZATION_WORKS.md).

## Start here

Open `outputs/review/index.html`. It links to:

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

From the repository root, using an activated Python environment:

```sh
python -m pip install -r FIRO_COMPONENTS/requirements.txt
python FIRO_COMPONENTS/run.py model
python FIRO_COMPONENTS/run.py review
```

`all` runs both stages. Commands stop on the first failing script. Running a stage
overwrites its generated outputs. Headless machines should set `MPLBACKEND=Agg`.
Keep the complete review folders together: HTML pages use local Plotly assets.

## What is retained

| Scripts | Purpose | Outputs |
| --- | --- | --- |
| 01 | Baseline allocation | 20–27 |
| 02 | Component geometry and daily envelopes | 30–34 |
| 03 | Cap and validate curves; static diagnostic plots | 35–39 and plots/ |
| 05 | Separate redistribution optimization | 40–47 |
| 11 | Numerical capacity/status/contribution preparation | review/capacity_constraint_review/*.csv |
| 15 (using 14, 13) | Two-case overview and controller diagnostics | review/utilization_ribbon_overview, review/constraint_controller_overview |
| 15 (using 04, 07) | Two-case component detail and navigation | plotly_component_review/ |
| 06 | Allocation/QA summary and review landing page | review/index.html and summary tables |

`00_patch_green_peter_rule_curve.py` is an explicit input-patching operation,
not a routine run step. Saved patch history and preparation records are in `provenance/`; new patch
outputs go to `outputs/input_patches/`. Only six local input tables remain in
`data/`; storage ratings and control-point limits are loaded directly from their
selected sources in `shared/`. See [the input guide](data/README.md) and
[provenance guide](provenance/README.md). The rating source is now shared/common_data/ElevStor.csv, matching the other
analysis workflows. This intentionally supersedes the earlier spreadsheet
source choice; the original pre-cleanup numerical equivalence check described
below applies only to that earlier deduplication. The initial canonical
input/network generation is not fully captured here; do not assume this project
can regenerate those inputs from the shared originals.

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
Scenario-specific numerical outputs live in `outputs/scenarios/before/` and
`after/`, with capacity-status tables in each case's `capacity_status/` folder.
`outputs/scenarios/manifest.json` records source/algorithm hashes.

All 89 retained chart pages contain both cases, rather than linking to a separate
set of reallocated charts. The selector redraws one chart in place. Alternative
1 has meaningful allocation increases at Detroit and Green Peter; the other
modeled alternatives differ only at numerical-tolerance level in the saved run.

For the numerical regression checks after building comparisons:

```sh
python -m unittest discover -s FIRO_COMPONENTS/tests
```
